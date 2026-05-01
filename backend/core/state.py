import os
import json
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# In-memory queues
_log_queue: Optional[asyncio.Queue] = None
_reflection_queue: Optional[asyncio.Queue] = None

def _get_log_queue() -> asyncio.Queue:
    global _log_queue
    if _log_queue is None:
        _log_queue = asyncio.Queue(maxsize=500)
    return _log_queue

def _get_reflection_queue() -> asyncio.Queue:
    global _reflection_queue
    if _reflection_queue is None:
        _reflection_queue = asyncio.Queue(maxsize=500)
    return _reflection_queue

def _push_log(msg: str):
    try:
        _get_log_queue().put_nowait(json.dumps({"log": msg}))
    except asyncio.QueueFull:
        pass

def _push_reflection(data: dict):
    try:
        _get_reflection_queue().put_nowait(json.dumps(data))
    except asyncio.QueueFull:
        pass

# Crypto Stream State
_crypto_stream_state = {
    "stream": None,
    "bar_callback": None,
    "quote_callback": None,
}
_equity_stream_state = {
    "stream": None,
    "callback": None,
}

# Shared symbol lists, updated at startup and by discovery.
CRYPTO_STREAM_SYMBOLS: list[str] = []
EQUITY_STREAM_SYMBOLS: list[str] = []

# Entry prices / times persisted across restarts
_ENTRY_PRICES_FILE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "_entry_prices.json"))
_entry_prices: dict[tuple, float] = {}
_entry_times: dict[tuple, str] = {}

def _load_entry_prices() -> tuple[dict[tuple, float], dict[tuple, str]]:
    prices: dict[tuple, float] = {}
    times: dict[tuple, str] = {}
    try:
        with open(_ENTRY_PRICES_FILE, "r") as f:
            raw = json.load(f)

        if "prices" in raw and isinstance(raw["prices"], dict):
            price_map = raw["prices"]
            time_map = raw.get("times", {})
        else:
            price_map = raw
            time_map = {}

        for k, v in price_map.items():
            parts = k.split("|", 1)
            if len(parts) == 2:
                prices[(parts[0], parts[1])] = float(v)
        for k, v in time_map.items():
            parts = k.split("|", 1)
            if len(parts) == 2:
                times[(parts[0], parts[1])] = str(v)

        logger.info("[ENTRY PRICES] Restored %d open positions from disk", len(prices))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("[ENTRY PRICES] Failed to restore from disk: %s", e)
    return prices, times

def persist_entry_prices(entry_prices: dict[tuple, float], entry_times: dict[tuple, str]) -> None:
    try:
        raw = {
            "prices": {f"{b}|{s}": p for (b, s), p in entry_prices.items()},
            "times": {f"{b}|{s}": t for (b, s), t in entry_times.items()},
        }
        with open(_ENTRY_PRICES_FILE, "w") as f:
            json.dump(raw, f)
    except Exception as e:
        logger.warning("[ENTRY PRICES] Failed to persist to disk: %s", e)

# Persistent state containers
scanner_agent = None
research_agent = None
reflection_engine = None

# Load persisted entry prices at import time.
_entry_prices, _entry_times = _load_entry_prices()

# Clients List
connected_clients = []
_clients_lock = None

def _get_clients_lock():
    global _clients_lock
    if _clients_lock is None:
        _clients_lock = asyncio.Lock()
    return _clients_lock
