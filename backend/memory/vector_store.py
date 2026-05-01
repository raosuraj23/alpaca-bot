"""
Vector Store — Semantic Trade Memory (ChromaDB)
================================================
Embeds every closed round-trip trade as a searchable document.
Before approving any new signal, the orchestrator queries this store to
retrieve the most similar past failures and surface them in the debate prompt.

Storage: persistent ChromaDB at ./chroma_db/ relative to the backend root.
Collection: "trade_memory"

Document format (plain text — ChromaDB default embedding):
    "{symbol} | strategy={strategy} | action={action} | pnl=${net_pnl:.2f} |
     win={win} | confidence={confidence:.2f} | entry=${entry:.4f} |
     exit=${exit:.4f} | hold={hold}min | conditions={conditions}"

Metadata stored alongside each document (for filtering):
    symbol, strategy, win (bool→int), net_pnl, asset_class, timestamp_iso
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_COLLECTION_NAME = "trade_memory"
# Persistent storage next to the backend directory so it survives restarts
_CHROMA_PATH = str(Path(__file__).resolve().parent.parent / "chroma_db")

_client = None
_collection = None


def _get_collection():
    """Lazy-init ChromaDB client and collection. Safe to call repeatedly."""
    global _client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        _client = chromadb.PersistentClient(path=_CHROMA_PATH)
        _collection = _client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("[VECTOR STORE] ChromaDB initialised — %d docs in collection", _collection.count())
    except Exception as exc:
        logger.warning("[VECTOR STORE] ChromaDB init failed (%s) — vector memory disabled", exc)
        _collection = None
    return _collection


def _build_document(trade: dict) -> str:
    """Convert a ClosedTrade-shaped dict into a searchable text document."""
    cond_raw = trade.get("market_conditions") or "{}"
    try:
        cond = json.loads(cond_raw) if isinstance(cond_raw, str) else cond_raw
    except (json.JSONDecodeError, TypeError):
        cond = {}

    parts = [
        f"{trade.get('symbol', '?')} | strategy={trade.get('strategy', '?')}",
        f"action={trade.get('action', 'BUY')} | pnl=${float(trade.get('net_pnl', 0)):.2f}",
        f"win={'yes' if trade.get('win') else 'no'} | confidence={float(trade.get('confidence', 0)):.2f}",
        f"entry=${float(trade.get('avg_entry_price', 0)):.4f} | exit=${float(trade.get('avg_exit_price', 0)):.4f}",
        f"hold={trade.get('hold_duration_min', 0)}min",
    ]
    if cond:
        cond_str = " ".join(f"{k}={v}" for k, v in cond.items())
        parts.append(f"conditions: {cond_str}")
    if trade.get("insight"):
        parts.append(f"insight: {str(trade['insight'])[:200]}")

    return " | ".join(parts)


def embed_trade(trade: dict) -> bool:
    """
    Embed a closed trade into the vector store.
    Call this immediately after a ClosedTrade is committed to the database.

    Args:
        trade: dict with keys matching ClosedTrade columns plus optional
               'strategy' and 'action' from the linked signal.

    Returns True on success, False if ChromaDB is unavailable.
    """
    col = _get_collection()
    if col is None:
        return False

    trade_id = str(trade.get("id") or trade.get("exit_execution_id") or id(trade))
    doc_id = f"trade_{trade_id}"
    document = _build_document(trade)

    metadata = {
        "symbol":      str(trade.get("symbol", "")),
        "strategy":    str(trade.get("strategy", "")),
        "win":         1 if trade.get("win") else 0,
        "net_pnl":     float(trade.get("net_pnl", 0.0)),
        "asset_class": str(trade.get("asset_class", "")),
        "timestamp":   trade.get("exit_time") or datetime.now(timezone.utc).isoformat(),
    }

    try:
        col.upsert(ids=[doc_id], documents=[document], metadatas=[metadata])
        logger.debug("[VECTOR STORE] Embedded trade %s — %s", doc_id, document[:80])
        return True
    except Exception as exc:
        logger.warning("[VECTOR STORE] embed_trade failed: %s", exc)
        return False


def query_similar_failures(symbol: str, strategy: str, n_results: int = 5) -> list[str]:
    """
    Retrieve the most semantically similar past LOSING trades for a given
    symbol+strategy combination. Used by the orchestrator before running
    the dialectical debate to surface repeated mistake patterns.

    Args:
        symbol:    The asset being traded (e.g. "BTC/USD", "NVDA").
        strategy:  The bot/strategy name (e.g. "crypto-breakout").
        n_results: Max number of past trades to surface.

    Returns:
        List of lesson strings — one per past trade — ready to inject into the
        debate prompt as "KB lessons". Empty list if ChromaDB unavailable.
    """
    col = _get_collection()
    if col is None:
        return []

    if col.count() == 0:
        return []

    query_text = f"{symbol} | strategy={strategy} | win=no"

    try:
        results = col.query(
            query_texts=[query_text],
            n_results=min(n_results, col.count()),
            where={"win": {"$eq": 0}},          # only retrieve losses
        )
    except Exception as exc:
        logger.debug("[VECTOR STORE] query failed: %s", exc)
        return []

    docs = (results.get("documents") or [[]])[0]
    metas = (results.get("metadatas") or [[]])[0]

    lessons = []
    for doc, meta in zip(docs, metas):
        pnl = meta.get("net_pnl", 0.0)
        ts  = meta.get("timestamp", "")[:10]
        lessons.append(f"[{ts}] {doc[:180]}  → pnl=${pnl:.2f}")

    return lessons


def query_similar_wins(symbol: str, strategy: str, n_results: int = 3) -> list[str]:
    """
    Retrieve similar WINNING trades — used to reinforce bull thesis in debate.
    """
    col = _get_collection()
    if col is None:
        return []
    if col.count() == 0:
        return []

    query_text = f"{symbol} | strategy={strategy} | win=yes"
    try:
        results = col.query(
            query_texts=[query_text],
            n_results=min(n_results, col.count()),
            where={"win": {"$eq": 1}},
        )
    except Exception as exc:
        logger.debug("[VECTOR STORE] wins query failed: %s", exc)
        return []

    docs = (results.get("documents") or [[]])[0]
    metas = (results.get("metadatas") or [[]])[0]

    wins = []
    for doc, meta in zip(docs, metas):
        pnl = meta.get("net_pnl", 0.0)
        ts  = meta.get("timestamp", "")[:10]
        wins.append(f"[{ts}] {doc[:180]}  → pnl=+${pnl:.2f}")

    return wins


def collection_count() -> int:
    """Returns total embedded trade count; 0 if unavailable."""
    col = _get_collection()
    if col is None:
        return 0
    try:
        return col.count()
    except Exception:
        return 0
