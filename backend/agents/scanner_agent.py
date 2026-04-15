"""
Scanner Agent — Market Research + Symbol Discovery + TA Screener + LLM Prioritization
=======================================================================================
Two-tier autonomous loop:

  TIER 1 — Discovery (every 30 min, Sonnet)
    Scans the full crypto universe for new symbols worth adding to the watchlist.
    Uses Sonnet to research current market regime and select top candidates.
    Newly discovered symbols are persisted to WatchlistItem and injected into
    the active scan list.

  TIER 2 — TA Screener (every 5 min, Haiku)
    Scores active symbols with deterministic TA (EMA, RSI, Volume, Bollinger).
    Haiku writes one-line verdicts per symbol.
    Results pushed to SSE stream and persisted to WatchlistItem.

Portfolio integration:
    Position symbols are always included in TIER 2 so held assets are
    continuously monitored for exit signals.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Base watchlist — always scanned regardless of discovery
SCAN_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Extended universe evaluated during TIER 1 discovery
UNIVERSE_SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD",
    "AVAX/USD", "LINK/USD", "UNI/USD",
    "DOGE/USD", "ADA/USD", "LTC/USD",
    "DOT/USD", "BCH/USD", "ATOM/USD",
]

SCAN_INTERVAL      = 300   # 5 min — TA screener cadence
DISCOVERY_INTERVAL = 1800  # 30 min — Sonnet market research cadence
WARMUP_DELAY       = 30    # Let streams populate the buffer first
MAX_ACTIVE_SYMBOLS = 8     # Cap to control LLM cost and stream connections


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScannerAgent:
    """
    Two-tier scanner.

    Tier 1 (30 min): Sonnet evaluates the UNIVERSE_SYMBOLS universe,
    scores TA signals, and selects the top MAX_ACTIVE_SYMBOLS for active monitoring.

    Tier 2 (5 min): Haiku scores active symbols and writes verdicts.
    Results pushed to SSE + persisted to DB.
    """

    def __init__(
        self,
        push_fn: Callable[[dict], None],
        get_buffer_fn: Callable,
    ):
        self._push        = push_fn
        self._get_buffer  = get_buffer_fn
        self._running     = False
        self._last_scan:      Optional[datetime] = None
        self._last_discovery: Optional[datetime] = None
        self._results:        list[dict] = []
        # Active symbol set — starts from base, expanded by discovery
        self._active_symbols: list[str] = list(SCAN_SYMBOLS)

    def get_last_results(self) -> list[dict]:
        """Returns the most recent scan results for REST polling."""
        return self._results

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def run(self):
        """Background entry point — runs both tiers concurrently."""
        self._running = True
        await asyncio.sleep(WARMUP_DELAY)
        logger.info("[SCANNER] Agent started (scan=%ds, discovery=%ds)", SCAN_INTERVAL, DISCOVERY_INTERVAL)
        await asyncio.gather(
            self._scan_loop(),
            self._discovery_loop(),
        )

    async def _scan_loop(self):
        """TIER 2 — TA screener runs every SCAN_INTERVAL seconds."""
        while self._running:
            try:
                await self._scan()
            except Exception as e:
                logger.warning("[SCANNER] Scan error: %s", e)
            await asyncio.sleep(SCAN_INTERVAL)

    async def _discovery_loop(self):
        """TIER 1 — market research runs every DISCOVERY_INTERVAL seconds."""
        # Wait for first TA scan before doing discovery
        await asyncio.sleep(SCAN_INTERVAL + 10)
        while self._running:
            try:
                await self._discover_symbols()
            except Exception as e:
                logger.warning("[SCANNER] Discovery error: %s", e)
            await asyncio.sleep(DISCOVERY_INTERVAL)

    async def run_once(self) -> list[dict]:
        """On-demand scan triggered by the REST endpoint. Returns results."""
        await self._scan()
        return self._results

    # ------------------------------------------------------------------
    # TIER 1 — Symbol discovery via Sonnet market research
    # ------------------------------------------------------------------

    async def _discover_symbols(self):
        """
        Evaluates the full UNIVERSE_SYMBOLS with TA, then asks Sonnet to
        select the top MAX_ACTIVE_SYMBOLS based on market research and
        current conditions. Updates self._active_symbols.
        """
        buffer = self._get_buffer()
        if buffer is None:
            return

        # Score every universe symbol deterministically
        universe_scored = []
        for symbol in UNIVERSE_SYMBOLS:
            result = self._score_symbol(symbol, buffer)
            if result is not None:
                universe_scored.append(result)

        if not universe_scored:
            logger.debug("[SCANNER] Discovery: insufficient bars for universe scoring")
            return

        # Also include current position symbols
        position_symbols = await self._get_position_symbols()
        for sym in position_symbols:
            if not any(s["symbol"] == sym for s in universe_scored):
                result = self._score_symbol(sym, buffer)
                if result:
                    universe_scored.append(result)

        # Sonnet ranks and selects the best symbols
        selected = await self._sonnet_research(universe_scored, position_symbols)

        # Merge with base symbols (base always included)
        merged = list(dict.fromkeys(SCAN_SYMBOLS + selected + position_symbols))
        self._active_symbols = merged[:MAX_ACTIVE_SYMBOLS]

        now = _utcnow()
        self._last_discovery = now

        self._push({
            "type":      "discover",
            "text":      f"[DISCOVERY] Active watchlist updated: {', '.join(self._active_symbols)}",
            "symbols":   self._active_symbols,
            "timestamp": now.isoformat(),
        })

        logger.info("[SCANNER] Discovery complete — active: %s", self._active_symbols)

    async def _sonnet_research(self, scored: list[dict], held_symbols: list[str]) -> list[str]:
        """
        Asks Sonnet to select the top symbols from the universe based on:
          - Current TA scores and signals
          - Portfolio holdings (must monitor held positions)
          - Market regime (trending / ranging / volatile)

        Returns an ordered list of symbol strings.
        """
        try:
            from agents.factory import swarm_factory
            model = swarm_factory.build_model(model_level="smart")
            if not model:
                raise RuntimeError("smart model unavailable")

            from langchain_core.messages import SystemMessage, HumanMessage

            held_str = ", ".join(held_symbols) if held_symbols else "none"
            universe_str = "\n".join(
                f"  {s['symbol']:12s}  score={s['score']:+.2f}  signal={s['signal']:8s}  "
                f"price=${s['price']:,.2f}  RSI={s.get('rsi') or 'N/A'}"
                for s in sorted(scored, key=lambda x: abs(x["score"]), reverse=True)
            )

            response = model.invoke(
                [
                    SystemMessage(content=(
                        "You are a quantitative crypto portfolio manager. "
                        "Your task is to select the best symbols to actively monitor and trade "
                        f"from the universe below. Constraints:\n"
                        f"- Always include held positions: {held_str}\n"
                        f"- Select no more than {MAX_ACTIVE_SYMBOLS} symbols total\n"
                        f"- Prioritise symbols with strong directional signals (BUY or SELL)\n"
                        f"- Avoid correlated pairs (e.g. do not select both BTC and multiple ETH forks)\n"
                        f"- Consider liquidity: prefer BTC, ETH, SOL over micro-caps\n\n"
                        "Respond ONLY with a comma-separated list of symbols in priority order. "
                        "Example: BTC/USD, ETH/USD, SOL/USD"
                    )),
                    HumanMessage(content=f"Universe TA scores:\n{universe_str}"),
                ],
                max_tokens=100,
            )

            # Parse comma-separated symbol list from response
            raw = response.content.strip()
            selected: list[str] = []
            for token in raw.replace("\n", ",").split(","):
                sym = token.strip().upper()
                # Normalise: "BTCUSD" -> "BTC/USD", "BTC/USD" stays
                if "/" not in sym and len(sym) > 3:
                    sym = sym.replace("USD", "/USD")
                if sym and any(s["symbol"] == sym for s in scored):
                    selected.append(sym)
                if len(selected) >= MAX_ACTIVE_SYMBOLS:
                    break

            # Log cost
            try:
                usage = getattr(response, "usage_metadata", None) or {}
                t_in  = usage.get("input_tokens", 0)
                t_out = usage.get("output_tokens", 0)
                cost  = (t_in * 3.00 + t_out * 15.00) / 1_000_000  # Sonnet pricing
                from db.database import _get_session_factory
                from db.models import LLMUsage
                async with _get_session_factory()() as _s:
                    _s.add(LLMUsage(
                        model="claude-sonnet-4-6",
                        tokens_in=t_in,
                        tokens_out=t_out,
                        cost_usd=cost,
                        purpose="scanner_discovery",
                    ))
                    await _s.commit()
            except Exception as _le:
                logger.debug("[SCANNER] Sonnet cost log failed: %s", _le)

            logger.info("[SCANNER] Sonnet selected: %s", selected)
            return selected

        except Exception as e:
            logger.debug("[SCANNER] Sonnet research unavailable: %s", e)
            # Fallback: pick top-scoring symbols by abs(score)
            top = sorted(scored, key=lambda x: abs(x["score"]), reverse=True)
            return [s["symbol"] for s in top[:MAX_ACTIVE_SYMBOLS]]

    # ------------------------------------------------------------------
    # TIER 2 — TA screener
    # ------------------------------------------------------------------

    async def _get_position_symbols(self) -> list[str]:
        """Returns symbols currently held in the portfolio."""
        try:
            from agents.orchestrator import trading_client
            if trading_client is None:
                return []
            positions = trading_client.get_all_positions()
            return [p.symbol for p in positions]
        except Exception:
            return []

    async def _scan(self):
        buffer = self._get_buffer()
        if buffer is None:
            return

        # Always include position symbols so held assets are continuously monitored
        position_symbols = await self._get_position_symbols()
        symbols_to_scan  = list(dict.fromkeys(self._active_symbols + position_symbols))

        scored = []
        for symbol in symbols_to_scan:
            result = self._score_symbol(symbol, buffer)
            if result is not None:
                scored.append(result)

        if not scored:
            return

        scored.sort(key=lambda x: abs(x["score"]), reverse=True)
        haiku_verdicts = await self._haiku_rank(scored)

        now = _utcnow()
        self._last_scan = now
        self._results = [
            {
                "symbol":    s["symbol"],
                "score":     round(s["score"], 4),
                "signal":    s["signal"],
                "price":     s.get("price", 0),
                "rsi":       s.get("rsi"),
                "vol_surge": s.get("vol_surge"),
                "summary":   s["summary"],
                "verdict":   haiku_verdicts.get(s["symbol"], s["summary"]),
                "timestamp": now.isoformat(),
            }
            for s in scored
        ]

        top = self._results[0] if self._results else None
        if top:
            self._push({
                "type":      "scanner",
                "symbol":    top["symbol"],
                "text":      f"[SCANNER] Top pick: {top['symbol']} score={top['score']:+.3f} — {top['verdict']}",
                "results":   self._results,
                "timestamp": now.isoformat(),
            })

        await self._persist(self._results)
        logger.info("[SCANNER] Scan done — top: %s score=%+.3f",
                    top["symbol"] if top else "?", top["score"] if top else 0)

    # ------------------------------------------------------------------
    # TA scoring
    # ------------------------------------------------------------------

    def _score_symbol(self, symbol: str, buffer) -> Optional[dict]:
        """
        Composite TA score. Returns None if fewer than 20 bars in buffer.

        Score components:
          EMA trend  : +1.0 if price > EMA20, -1.0 if below
          RSI(14)    : +1.0 if 45<RSI<65, -0.5 if >70 or <30
          Volume     : +0.5 if vol_surge > 1.5x 20-bar average
          Bollinger  : +0.5 if price in lower 25% of band (mean-reversion buy zone)
                       -0.3 if price in upper 75%+
        """
        try:
            bars = buffer.get_bars(symbol)
            if not bars or len(bars) < 20:
                return None

            closes  = [b["close"]  for b in bars]
            volumes = [b["volume"] for b in bars]

            price     = closes[-1]
            ema20     = sum(closes[-20:]) / 20
            avg_vol   = sum(volumes[-20:]) / 20 if volumes else 0
            vol_surge = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

            rsi = self._rsi(closes, 14)

            std20    = (sum((c - ema20) ** 2 for c in closes[-20:]) / 20) ** 0.5
            upper    = ema20 + 2 * std20
            lower    = ema20 - 2 * std20
            band_pct = (price - lower) / (upper - lower) if upper != lower else 0.5

            score   = 0.0
            signals = []

            if price > ema20 * 1.001:
                score += 1.0
                signals.append("above EMA20")
            elif price < ema20 * 0.999:
                score -= 1.0
                signals.append("below EMA20")

            if rsi is not None:
                if 45 < rsi < 65:
                    score += 1.0
                    signals.append(f"RSI {rsi:.0f}")
                elif rsi >= 70:
                    score -= 0.5
                    signals.append(f"RSI {rsi:.0f} overbought")
                elif rsi <= 30:
                    score -= 0.5
                    signals.append(f"RSI {rsi:.0f} oversold")

            if vol_surge > 1.5:
                score += 0.5
                signals.append(f"vol {vol_surge:.1f}x")

            if band_pct < 0.25:
                score += 0.5
                signals.append("BB lower zone")
            elif band_pct > 0.75:
                score -= 0.3
                signals.append("BB upper zone")

            signal  = "BUY" if score > 1.0 else "SELL" if score < -1.0 else "NEUTRAL"
            summary = f"${price:,.2f} | " + ", ".join(signals[:3]) if signals else f"${price:,.2f}"

            return {
                "symbol":    symbol,
                "score":     score,
                "signal":    signal,
                "summary":   summary,
                "price":     price,
                "rsi":       round(rsi, 1) if rsi is not None else None,
                "vol_surge": round(vol_surge, 2),
                "band_pct":  round(band_pct, 3),
            }

        except Exception as e:
            logger.debug("[SCANNER] Score error %s: %s", symbol, e)
            return None

    def _rsi(self, closes: list, period: int = 14) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        deltas  = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        recent  = deltas[-period:]
        avg_gain = sum(d for d in recent if d > 0) / period
        avg_loss = sum(-d for d in recent if d < 0) / period
        if avg_loss == 0:
            return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))

    # ------------------------------------------------------------------
    # LLM verdict (Haiku — fast tier)
    # ------------------------------------------------------------------

    async def _haiku_rank(self, scored: list[dict]) -> dict[str, str]:
        """Haiku produces a one-line verdict per symbol. Falls back to TA summary."""
        verdicts: dict[str, str] = {}
        try:
            from agents.factory import swarm_factory
            model = swarm_factory.build_model(model_level="fast")
            if not model:
                raise RuntimeError("no model")

            from langchain_core.messages import SystemMessage, HumanMessage
            lines = "\n".join(
                f"- {s['symbol']}: score={s['score']:+.2f}, signal={s['signal']}, {s['summary']}"
                for s in scored
            )
            response = model.invoke(
                [
                    SystemMessage(content=(
                        "You are a crypto quant screener. For each symbol, write ONE phrase "
                        "(max 8 words) describing the trade opportunity or risk in USD terms. "
                        "No markdown. Respond as: SYMBOL: verdict"
                    )),
                    HumanMessage(content=f"Rank these signals:\n{lines}"),
                ],
                max_tokens=150,
            )
            for line in response.content.strip().split("\n"):
                if ":" not in line:
                    continue
                sym_raw, _, verdict_text = line.partition(":")
                sym_raw = sym_raw.strip().upper()
                for s in scored:
                    base = s["symbol"].replace("/USD", "").replace("/", "")
                    if base in sym_raw or sym_raw in s["symbol"].upper():
                        verdicts[s["symbol"]] = verdict_text.strip()
                        break

            # Log token usage
            try:
                usage = getattr(response, "usage_metadata", None) or {}
                t_in  = usage.get("input_tokens", 0)
                t_out = usage.get("output_tokens", 0)
                cost  = (t_in * 0.80 + t_out * 4.00) / 1_000_000
                from db.database import _get_session_factory
                from db.models import LLMUsage
                async with _get_session_factory()() as _s:
                    _s.add(LLMUsage(
                        model="claude-haiku-4-5",
                        tokens_in=t_in,
                        tokens_out=t_out,
                        cost_usd=cost,
                        purpose="scanner",
                    ))
                    await _s.commit()
            except Exception as _le:
                logger.debug("[SCANNER] LLM usage log failed: %s", _le)

        except Exception as e:
            logger.debug("[SCANNER] Haiku unavailable: %s", e)

        for s in scored:
            if s["symbol"] not in verdicts:
                verdicts[s["symbol"]] = s["summary"]

        return verdicts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(self, results: list[dict]):
        """Upserts WatchlistItem rows in SQLite."""
        try:
            from db.database import _get_session_factory
            from db.models import WatchlistItem
            from sqlalchemy import select

            async with _get_session_factory()() as session:
                for r in results:
                    row = (await session.execute(
                        select(WatchlistItem).where(WatchlistItem.symbol == r["symbol"])
                    )).scalar_one_or_none()
                    if row:
                        row.score        = r["score"]
                        row.signal       = r["signal"]
                        row.verdict      = r["verdict"]
                        row.last_scanned = _utcnow()
                    else:
                        session.add(WatchlistItem(
                            symbol=r["symbol"],
                            score=r["score"],
                            signal=r["signal"],
                            verdict=r["verdict"],
                            last_scanned=_utcnow(),
                            active=True,
                        ))
                await session.commit()
        except Exception as e:
            logger.warning("[SCANNER] DB persist failed: %s", e)

    def stop(self):
        self._running = False
