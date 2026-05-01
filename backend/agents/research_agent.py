"""
ResearchAgent — Gemini 2.5 Flash deep-research loop (30-minute cadence).

Responsibilities:
  1. Every 30 min: fetch Alpaca news + TA snapshot → produce a ResearchBrief
     using Gemini 2.5 Flash (1500-token budget).
  2. Expose get_latest_brief() so ScannerAgent can inject the brief into its
     Tier 1 discovery prompt for better symbol selection.
  3. Every 5 min (via news poll in main.py): analyze_breaking_news() uses
     Gemini 2.5 Flash (250-token budget) to detect urgent signals and forward
     them to the orchestrator's process_signal() pipeline.
"""

import asyncio
import json
import logging
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel, Field
from config import (
    settings,
    GEMINI_FLASH_MODEL,
    GEMINI_FLASH_COST_IN,
    GEMINI_FLASH_COST_OUT,
)

logger = logging.getLogger(__name__)

# Pricing aliases — sourced from config constants
_GEMINI_25_FLASH_IN  = GEMINI_FLASH_COST_IN
_GEMINI_25_FLASH_OUT = GEMINI_FLASH_COST_OUT

# Minimum "Edge" required to forward a signal: Model Probability - Market Implied Probability
MIN_EDGE = settings.min_edge

# Alpaca news endpoint — sourced from config
_ALPACA_NEWS_URL = settings.alpaca_news_endpoint

# Symbols covered in research brief
from agents.scanner_agent import get_universe, expand_universe, _load_knowledge_context  # noqa: E402


# ---------------------------------------------------------------------------
# Pydantic output schemas
# ---------------------------------------------------------------------------

class SymbolSentiment(BaseModel):
    symbol: str
    sentiment: str          # BULLISH | BEARISH | NEUTRAL
    confidence: float       # 0.0–1.0 — LLM conviction
    rationale: str
    model_probability: float = 0.5   # P(directional move) as estimated by LLM (0.0–1.0)
    market_implied_probability: float = 0.5  # Baseline (0.5 = no edge; updated from momentum z-score)
    edge: float = 0.0       # model_probability - market_implied_probability; must exceed MIN_EDGE to trade


class ResearchBrief(BaseModel):
    sentiment_by_symbol: list[SymbolSentiment] = Field(default_factory=list)
    macro_theme: str = ""
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_focus: list[str] = Field(default_factory=list)
    generated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_RESEARCH_SYSTEM_PROMPT = (
    "You are a quantitative crypto market analyst. Analyze the provided news, "
    "technical data, and recent trade performance to produce a structured research brief.\n\n"
    "Guidelines:\n"
    "- sentiment_by_symbol: assess each symbol based on news + TA (only include symbols "
    "  from the provided universe with meaningful signals)\n"
    "  For each symbol also provide:\n"
    "    * model_probability: your estimated probability (0.0–1.0) that the asset moves "
    "      in the direction of your sentiment within the next 4 hours\n"
    "    * market_implied_probability: baseline expectation (0.5 = no edge; adjust up/down "
    "      based on momentum z-score, ATR, and options skew if available)\n"
    "    * edge: model_probability - market_implied_probability (positive = bullish edge, "
    "      negative = bearish edge). Only include symbols where abs(edge) >= 0.04\n"
    "- macro_theme: 1 sentence on the dominant macro narrative (risk-on/off, BTC cycle, Fed)\n"
    "- catalysts: up to 4 specific actionable positives (regulatory wins, technical breakouts, "
    "  narrative momentum)\n"
    "- risks: up to 4 key risks (macro headwinds, on-chain metrics, regulatory threats)\n"
    "- recommended_focus: ordered list of up to 8 symbols to prioritise for active trading, "
    "  combining news sentiment with TA signal quality\n\n"
    "Be specific and concise. Use numbers where available. No generic disclaimers."
)


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------

class ResearchAgent:
    RESEARCH_INTERVAL    = 1800   # 30 min between deep research cycles
    BRIEF_TTL            = 1680   # 28 min — expires before next 30-min cycle, no stale window
    WARMUP_DELAY         = 20     # seconds before first cycle
    BREAKING_THRESHOLD   = 0.75   # min confidence to forward as signal

    def __init__(
        self,
        push_fn: Callable[[dict], None],
        get_buffer_fn: Callable,
        signal_callback: Optional[Callable] = None,
    ):
        self._push            = push_fn
        self._get_buffer      = get_buffer_fn
        self._signal_callback = signal_callback
        self._latest_brief: Optional[ResearchBrief] = None
        self._brief_ts: Optional[datetime] = None
        self._running         = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @staticmethod
    def compute_edge(model_prob: float, market_implied_prob: float) -> float:
        """Edge = Model Probability - Market Implied Probability. Must exceed MIN_EDGE to trade."""
        return round(model_prob - market_implied_prob, 6)

    @staticmethod
    def _backfill_edge(brief: "ResearchBrief") -> None:
        """Fills in edge field for any SymbolSentiment where LLM left it at default."""
        for ss in brief.sentiment_by_symbol:
            if ss.edge == 0.0 and ss.model_probability != 0.5:
                ss.edge = ResearchAgent.compute_edge(ss.model_probability, ss.market_implied_probability)

    @staticmethod
    def _backfill_market_implied(brief: "ResearchBrief", mip_map: dict) -> None:
        """Replace default 0.5 market_implied_probability with sigmoid(momentum_z) values.

        mip_map: {symbol: market_implied_prob} computed from actual price data.
        """
        for ss in brief.sentiment_by_symbol:
            if ss.symbol in mip_map:
                ss.market_implied_probability = mip_map[ss.symbol]

    def get_latest_brief(self) -> Optional[ResearchBrief]:
        """Returns the most recent brief if it is still within TTL, else None."""
        if self._latest_brief is None or self._brief_ts is None:
            return None
        age = (datetime.now(timezone.utc) - self._brief_ts).total_seconds()
        return self._latest_brief if age < self.BRIEF_TTL else None

    async def run(self) -> None:
        """Main 30-minute research loop."""
        from strategy.equity_algorithms import _is_market_hours
        self._running = True
        await asyncio.sleep(self.WARMUP_DELAY)
        logger.info("[RESEARCH] Agent started — Gemini 2.5 Flash, 30-min cadence")
        while self._running:
            if not _is_market_hours():
                await asyncio.sleep(300)
                continue
            try:
                await self._run_research_cycle()
            except Exception as exc:
                logger.warning("[RESEARCH] Cycle error: %s", exc)
            await asyncio.sleep(self.RESEARCH_INTERVAL)

    async def analyze_breaking_news(self, news_items: list[dict]) -> None:
        """
        Fast-path: analyze up to 10 fresh news items with Gemini 2.0 Flash
        and forward strong signals to the orchestrator's process_signal().
        """
        if not news_items or not self._signal_callback:
            return
        try:
            from agents.factory import swarm_factory
            from langchain_core.messages import HumanMessage, SystemMessage

            model = swarm_factory.build_model(model_level="fast", max_tokens=250)
            if not model:
                return

            system = (
                "Analyze these breaking crypto news items for trading signals. "
                "For each relevant symbol (BTC/USD, ETH/USD, SOL/USD, etc.), output JSON: "
                '[{"symbol": "BTC/USD", "sentiment": "BULLISH", "confidence": 0.85, '
                '"rationale": "one sentence"}] '
                "Only include symbols with confidence > 0.7. No markdown, no preamble."
            )
            news_str = "\n".join(
                f"- {n.get('headline', '')} ({n.get('source', '')})"
                for n in news_items[:10]
            )
            from agents.factory import gemini_ainvoke
            response = await gemini_ainvoke(model, [
                SystemMessage(content=system),
                HumanMessage(content=news_str),
            ], tier="fast")
            raw = response.content.strip()
            match = re.search(r'\[.*?\]', raw, re.DOTALL)
            if not match:
                return
            signals = json.loads(match.group(0))
            for sig in signals:
                confidence = float(sig.get("confidence", 0))
                if confidence >= self.BREAKING_THRESHOLD:
                    symbol = sig.get("symbol", "")
                    if not symbol:
                        continue
                    event = {
                        "asset":      symbol,
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                        "source":     "research_breaking_news",
                        "sentiment":  sig.get("sentiment"),
                        "rationale":  sig.get("rationale", ""),
                        "confidence": confidence,
                        **self._compute_ta_fields(symbol),
                    }
                    # XGBoost gate: breaking news must pass the same probability gate
                    # as regular TA signals before reaching the orchestrator.
                    try:
                        from predict.feature_extractor import extract_features, compute_market_implied_prob
                        from predict.xgboost_classifier import xgb_classifier
                        _feats = extract_features(event)
                        _mkt_p = compute_market_implied_prob(_feats)
                        _gate  = xgb_classifier.gate(_feats, _mkt_p)
                        if not _gate["approved"]:
                            logger.info(
                                "[RESEARCH] Breaking news %s rejected by XGBoost "
                                "(p=%.3f edge=%.3f reason=%s)",
                                symbol, _gate["xgboost_prob"], _gate["edge"], _gate["reason"],
                            )
                            continue
                    except Exception as _xgb_exc:
                        logger.debug("[RESEARCH] Breaking news XGBoost gate skipped: %s", _xgb_exc)
                    asyncio.create_task(self._signal_callback(event))
                    logger.info("[RESEARCH] Breaking signal: %s %.0f%% %s",
                                symbol, confidence * 100, sig.get("sentiment"))
        except Exception as exc:
            logger.debug("[RESEARCH] Breaking news analysis failed: %s", exc)

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Private — research cycle
    # ------------------------------------------------------------------

    async def _run_research_cycle(self) -> None:
        alpaca_items = await self._fetch_news_items()
        rss_items    = await self._fetch_rss_items(get_universe())

        # Merge and deduplicate by first 60 chars of headline, cap at 40 items
        seen: set[str] = set()
        news_items: list[dict] = []
        for item in alpaca_items + rss_items:
            key = item.get("headline", "")[:60].lower().strip()
            if key and key not in seen:
                seen.add(key)
                news_items.append(item)
            if len(news_items) >= 40:
                break

        buffer = self._get_buffer()
        ta_summary, mip_map = self._build_ta_summary(buffer)
        trade_perf = await self._fetch_recent_performance()

        brief = await self._gemini_deep_research(news_items, ta_summary, trade_perf)
        if brief is None:
            logger.debug("[RESEARCH] Cycle produced no brief (LLM unavailable)")
            self._push({
                "type":      "research",
                "symbol":    "SYSTEM",
                "text":      "[RESEARCH] Research cycle skipped — LLM unavailable or budget exhausted",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        brief.generated_at = datetime.now(timezone.utc).isoformat()
        self._backfill_market_implied(brief, mip_map)
        self._backfill_edge(brief)
        self._latest_brief = brief
        self._brief_ts     = datetime.now(timezone.utc)

        await self._persist_brief(brief)

        # Log edge-qualified signals
        edge_signals = [
            ss for ss in brief.sentiment_by_symbol
            if abs(ss.edge) >= MIN_EDGE
        ]
        if edge_signals:
            logger.info("[RESEARCH] Edge-qualified signals (%d): %s", len(edge_signals),
                        [(ss.symbol, f"{ss.edge:+.3f}") for ss in edge_signals])

        # Feed recommended symbols back into the dynamic scanner universe
        if brief.recommended_focus:
            expand_universe(brief.recommended_focus)

        self._push({
            "type":        "research",
            "macro_theme": brief.macro_theme,
            "focus":       brief.recommended_focus[:5],
            "timestamp":   brief.generated_at,
        })
        logger.info("[RESEARCH] Cycle complete — focus: %s | macro: %s",
                    brief.recommended_focus[:3], brief.macro_theme[:80])

    async def _gemini_deep_research(
        self,
        news_items: list[dict],
        ta_summary: str,
        trade_perf: str,
    ) -> Optional[ResearchBrief]:
        try:
            from agents.factory import swarm_factory
            from langchain_core.messages import HumanMessage, SystemMessage

            model = swarm_factory.build_model(model_level="research", max_tokens=1500)
            if not model:
                return None

            try:
                structured = model.with_structured_output(ResearchBrief)
            except (NotImplementedError, TypeError):
                logger.debug("[RESEARCH] with_structured_output not supported")
                return None

            user_payload = json.dumps({
                "news":             [{"headline": n.get("headline", ""), "source": n.get("source", "")}
                                     for n in news_items[:25]],
                "ta_summary":       ta_summary,
                "trade_performance": trade_perf,
                "universe":         get_universe(),
                "timestamp":        datetime.now(timezone.utc).isoformat(),
            }, default=str)

            knowledge_ctx = _load_knowledge_context(20)
            system_content = (
                _RESEARCH_SYSTEM_PROMPT + "\n\n" + knowledge_ctx
                if knowledge_ctx else _RESEARCH_SYSTEM_PROMPT
            )

            from agents.factory import gemini_ainvoke
            result: ResearchBrief = await gemini_ainvoke(structured, [
                SystemMessage(content=system_content),
                HumanMessage(content=user_payload),
            ], tier="research")

            # TODO: structured LLM (with_structured_output) returns a Pydantic model,
            # not a raw AIMessage — usage_metadata is not accessible here.
            # Token cost logging for research cycles is currently skipped.

            return result

        except Exception as exc:
            logger.warning("[RESEARCH] Gemini deep research failed: %s", exc)
            self._push({
                "type":      "research",
                "symbol":    "SYSTEM",
                "text":      f"[RESEARCH] Gemini API error — research paused: {type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return None

    async def _fetch_news_items(self) -> list[dict]:
        """Direct Alpaca News REST call — avoids internal HTTP round-trip."""
        key    = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET", "")
        if not key:
            return []
        try:
            import requests as _req
            # Build ticker list from current dynamic universe (strip /USD for crypto)
            tickers = ",".join(
                s.replace("/USD", "") for s in get_universe()[:20]
            )
            resp = _req.get(
                _ALPACA_NEWS_URL,
                params={"symbols": tickers, "limit": 30, "sort": "desc"},
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
                timeout=8,
            )
            if resp.ok:
                return resp.json().get("news", [])
        except Exception as exc:
            logger.debug("[RESEARCH] News fetch failed: %s", exc)
        return []

    async def _fetch_rss_items(self, symbols: list[str]) -> list[dict]:
        """
        Fetches financial news from 3 RSS feeds using stdlib only (no new pip deps).
        Filters items where a bare ticker appears in title or summary.
        All errors caught silently — cycle continues with Alpaca-only news on failure.
        """
        feeds = [
            ("Yahoo Finance",    "https://finance.yahoo.com/rss/topfinstories"),
            ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
            ("Seeking Alpha",    "https://seekingalpha.com/market_currents.xml"),
        ]
        bare = {s.replace("/USD", "").replace("/", "") for s in symbols}
        items: list[dict] = []
        loop = asyncio.get_event_loop()

        for feed_name, url in feeds:
            try:
                def _fetch(u=url):
                    req = urllib.request.Request(
                        u, headers={"User-Agent": "AlpacaBot/1.0 RSS reader"}
                    )
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        return resp.read()

                raw_bytes = await loop.run_in_executor(None, _fetch)
                root = ET.fromstring(raw_bytes.decode("utf-8", errors="replace"))

                ns = {"atom": "http://www.w3.org/2005/Atom"}
                raw_items = root.findall(".//item") or root.findall(".//atom:entry", ns)

                for item in raw_items[:20]:
                    title   = (item.findtext("title") or
                               item.findtext("atom:title", namespaces=ns) or "").strip()
                    summary = (item.findtext("description") or
                               item.findtext("atom:summary", namespaces=ns) or "").strip()
                    link    = (item.findtext("link") or "").strip()

                    combined = (title + " " + summary).upper()
                    if any(sym in combined for sym in bare):
                        items.append({"headline": title, "source": feed_name, "url": link})

                logger.debug("[RESEARCH] RSS %s: %d relevant items", feed_name, len(items))
            except Exception as exc:
                logger.debug("[RESEARCH] RSS feed %s failed: %s", feed_name, exc)

        return items

    def _compute_ta_fields(self, symbol: str) -> dict:
        """Compute TA indicator snapshot for enriching breaking-news signals."""
        try:
            import pandas as pd  # noqa: F401 — available project-wide
            buffer = self._get_buffer()
            if buffer is None:
                return {}
            df = buffer.get_candles(symbol, "5Min")
            if df is None or df.empty or len(df) < 20:
                return {}
            closes  = df["close"]
            volumes = df["volume"]
            n = len(closes)

            ema50  = float(closes.ewm(span=50,  adjust=False).mean().iloc[-1]) if n >= 50  else 0.0
            ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1]) if n >= 200 else 0.0

            rsi_val: Optional[float] = None
            if n >= 15:
                deltas   = closes.diff().dropna().tolist()[-14:]
                avg_gain = sum(d for d in deltas if d > 0) / 14
                avg_loss = sum(-d for d in deltas if d < 0) / 14
                rsi_val  = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

            avg_vol   = float(volumes.iloc[-20:].mean()) if n >= 20 else 0.0
            vol_ratio = float(volumes.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

            return {
                "ema_50":             round(ema50, 4),
                "ema_200":            round(ema200, 4),
                "rsi_14":             round(rsi_val, 2) if rsi_val is not None else 0.0,
                "volume_surge_ratio": round(vol_ratio, 3),
                "conditions": {
                    "golden_cross": ema50 > ema200 and ema200 > 0,
                    "rsi_gate":     rsi_val is not None and 40 < rsi_val < 60,
                    "volume_surge": vol_ratio > 1.5,
                },
            }
        except Exception:
            return {}

    def _build_ta_summary(self, buffer) -> tuple:
        """Compact per-symbol price/ema/momentum snapshot for the research prompt.

        Returns:
            (summary_str, mip_map) where mip_map = {symbol: market_implied_prob}
            computed as sigmoid(momentum_z * 0.5) — dampened to avoid extreme values.
        """
        if buffer is None:
            return "Buffer unavailable.", {}
        lines = []
        mip_map: dict = {}
        for symbol in get_universe():
            try:
                df = buffer.get_candles(symbol, "1Min")
                if df is None or df.empty or len(df) < 20:
                    lines.append(f"{symbol}: <20 bars")
                    continue
                closes = df["close"].tolist()
                price  = closes[-1]
                window = closes[-20:]
                ema20  = sum(window) / 20
                std20  = (sum((c - ema20) ** 2 for c in window) / 20) ** 0.5
                momentum_z = max(-4.0, min(4.0, (price - ema20) / std20)) if std20 > 0 else 0.0
                mip = round(1.0 / (1.0 + math.exp(-momentum_z)), 4)
                mip_map[symbol] = mip
                trend = "above" if price > ema20 else "below"
                lines.append(
                    f"{symbol}: ${price:,.2f} {trend} EMA20 (${ema20:,.2f}) "
                    f"mom_z={momentum_z:.2f} mip={mip:.3f}"
                )
            except Exception:
                lines.append(f"{symbol}: error")
        return "\n".join(lines), mip_map

    async def _fetch_recent_performance(self) -> str:
        """Last 10 trade-learning reflection entries (excludes research_brief rows)."""
        try:
            from db.database import _get_session_factory
            from db.models import ReflectionLog
            from sqlalchemy import desc, select

            async with _get_session_factory()() as session:
                rows = (await session.execute(
                    select(ReflectionLog)
                    .where(ReflectionLog.action != "research_brief")
                    .order_by(desc(ReflectionLog.timestamp))
                    .limit(10)
                )).scalars().all()

            if not rows:
                return "No recent trade history."
            return "\n".join(
                f"{r.symbol} {r.action}: {(r.insight or '')[:80]}"
                for r in rows
            )
        except Exception:
            return "Trade history unavailable."

    async def _persist_brief(self, brief: ResearchBrief) -> None:
        """Stores brief summary to ReflectionLog using action='research_brief'."""
        try:
            from db.database import _get_session_factory
            from db.models import ReflectionLog

            payload = json.dumps({
                "macro_theme":       brief.macro_theme,
                "catalysts":         brief.catalysts[:4],
                "risks":             brief.risks[:4],
                "recommended_focus": brief.recommended_focus[:8],
            }, default=str)

            async with _get_session_factory()() as session:
                session.add(ReflectionLog(
                    strategy    = "research_agent",
                    symbol      = "UNIVERSE",
                    action      = "research_brief",
                    insight     = payload[:500],
                    tokens_used = None,
                ))
                await session.commit()
        except Exception as exc:
            logger.debug("[RESEARCH] Persist brief failed: %s", exc)

    async def _log_usage(
        self,
        model_name: str,
        purpose: str,
        price_in: float,
        price_out: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        try:
            from db.database import _get_session_factory
            from db.models import LLMUsage

            cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
            async with _get_session_factory()() as _s:
                _s.add(LLMUsage(
                    model     = model_name,
                    tokens_in = tokens_in,
                    tokens_out= tokens_out,
                    cost_usd  = cost,
                    purpose   = purpose,
                ))
                await _s.commit()
        except Exception:
            pass
