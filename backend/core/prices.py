import os
import json
import logging

logger = logging.getLogger(__name__)

_ENTRY_PRICES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_entry_prices.json")

def _load_entry_prices() -> "tuple[dict, dict]":
    """Restores entry prices and times from disk so restarts don't lose open-position cost basis."""
    prices: dict[tuple, float] = {}
    times:  dict[tuple, str]   = {}
    try:
        with open(_ENTRY_PRICES_FILE, "r") as f:
            raw = json.load(f)

        if "prices" in raw and isinstance(raw["prices"], dict):
            price_map = raw["prices"]
            time_map  = raw.get("times", {})
        else:
            price_map = raw
            time_map  = {}

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

def _persist_entry_prices(entry_prices: dict, entry_times: dict):
    """Writes current entry-price and entry-time maps to disk after every fill."""
    try:
        raw = {
            "prices": {f"{b}|{s}": p for (b, s), p in entry_prices.items()},
            "times":  {f"{b}|{s}": t for (b, s), t in entry_times.items()},
        }
        with open(_ENTRY_PRICES_FILE, "w") as f:
            json.dump(raw, f)
    except Exception as e:
        logger.warning("[ENTRY PRICES] Failed to persist to disk: %s", e)

# Singleton instances
entry_prices, entry_times = _load_entry_prices()
