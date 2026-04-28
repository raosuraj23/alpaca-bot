"""
Scanner Agent — Market Research + Symbol Discovery + TA Screener + LLM Prioritization
=======================================================================================
Two-tier autonomous loop:

  TIER 1 — Discovery (every 30 min, Sonnet)
    Scans the full crypto universe for new symbols worth adding to the watchlist.
    Uses Sonnet to research current market regime and select top candidates.
    Newly discovered symbols are persisted to WatchlistItem and injected into
    the active scan list.

  TIER 2 — TA Screener (every 5 min, AI)
    Scores active symbols with deterministic TA (EMA, RSI, Volume, Bollinger).
    AI writes one-line verdicts per symbol.
    Results pushed to SSE stream and persisted to WatchlistItem.

Portfolio integration:
    Position symbols are always included in TIER 2 so held assets are
    continuously monitored for exit signals.
"""

import asyncio
import json
import logging
import pathlib
import pandas as pd
from datetime import datetime, timezone
from typing import Callable, Optional
from config import GEMINI_FLASH_MODEL, GEMINI_FLASH_COST_IN, GEMINI_FLASH_COST_OUT

logger = logging.getLogger(__name__)

# Absolute bootstrap — always monitored regardless of discovery
SCAN_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Seed universes — starting point only; universe grows at runtime via expand_universe()
_CRYPTO_SEED: list[str] = [
    "BTC/USD", "ETH/USD", "SOL/USD",
    "AVAX/USD", "LINK/USD", "UNI/USD",
    "DOGE/USD", "ADA/USD", "LTC/USD",
    "DOT/USD", "BCH/USD", "ATOM/USD",
]
_EQUITY_SEED: list[str] = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
    "TSLA", "AMZN", "GOOGL", "META", "AMD",
    "NFLX", "INTC", "JPM", "BAC", "GS",
]

# Module-level mutable universe — grows as research/scanner surface new symbols
_dynamic_universe: set[str] = set(_CRYPTO_SEED + _EQUITY_SEED)

_KB_PATH = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "failure_log.jsonl"


def _load_knowledge_context(n: int = 20) -> str:
    """
    Reads the last N entries from backend/knowledge/failure_log.jsonl.
    Returns a compact string for injection into LLM prompts, or "" if file absent/empty.
    """
    if not _KB_PATH.exists():
        return ""
    try:
        lines = _KB_PATH.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            return ""
        entries = []
        for line in lines[-n:]:
            try:
                rec = json.loads(line)
                ke = rec.get("knowledge_entry", "").strip()
                if ke:
                    entries.append(
                        f"[{rec.get('failure_class', '?')}] {rec.get('symbol', '?')}: {ke}"
                    )
            except Exception:
                pass
        if not entries:
            return ""
        return "Past failure knowledge (apply to avoid repeat mistakes):\n" + "\n".join(entries)
    except Exception:
        return ""


def expand_universe(symbols: list[str], engine=None) -> None:
    """Add newly discovered symbols to the active evaluation universe.

    Called by ResearchAgent after each brief and by ScannerAgent after discovery.
    Thread-safe for asyncio single-threaded event loop.

    If engine is provided, brand-new (non-seed) symbols are quarantined via
    engine.add_to_pending() so the Portfolio Director can assign them a strategy
    before any trades are placed.
    """
    new = [s for s in symbols if s and s not in _dynamic_universe]
    if new:
        logger.info("[SCANNER] Universe expanded: +%s", new)
        _dynamic_universe.update(new)
        if engine is not None:
            for sym in new:
                engine.add_to_pending(sym)


def get_universe() -> list[str]:
    """Current evaluation universe as a stable list (seed order preserved, new appended)."""
    seed_order = _CRYPTO_SEED + _EQUITY_SEED
    extras = sorted(_dynamic_universe - set(seed_order))
    return seed_order + extras


# Back-compat alias imported by research_agent.py — always reflects current dynamic universe
UNIVERSE_SYMBOLS = get_universe()

SCAN_INTERVAL      = 300   # 5 min — TA screener cadence
DISCOVERY_INTERVAL = 1800  # 30 min — Sonnet market research cadence
WARMUP_DELAY       = 30    # Let streams populate the buffer first
MAX_ACTIVE_SYMBOLS = 8     # Cap to control LLM cost and stream connections


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Anomaly detection — Step 1 of the Agentic 5-Step Pipeline
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AnomalyFlag:
    symbol: str
    flag_type: Literal["PRICE_SPIKE", "VOLUME_SURGE", "WIDE_SPREAD"]
    price_move_pct: float = 0.0    # absolute % move vs. previous bar
    volume_ratio_7d: float = 1.0   # current volume / 7-day rolling average
    spread_bps: float = 0.0        # bid-ask spread in basis points (if quote data available)
    description: str = ""


def detect_anomalies(symbol: str, bars: list[dict]) -> list[AnomalyFlag]:
    """
    Scan recent OHLCV bars for hard-threshold anomalies.

    Rules:
      PRICE_SPIKE  — single-bar close move > 10% (absolute)
      VOLUME_SURGE — current bar volume > 2× 7-day (7*24*60 min bars) average
    """
    flags: list[AnomalyFlag] = []
    if len(bars) < 2:
        return flags

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]

    # PRICE_SPIKE: latest close vs. previous close
    prev, curr = closes[-2], closes[-1]
    if prev > 0:
        move_pct = abs((curr - prev) / prev) * 100
        if move_pct > 10.0:
            flags.append(AnomalyFlag(
                symbol=symbol,
                flag_type="PRICE_SPIKE",
                price_move_pct=round(move_pct, 3),
                description=f"{symbol} moved {move_pct:+.2f}% in last bar (prev=${prev:.2f} → ${curr:.2f})",
            ))

    # VOLUME_SURGE: vs. 7-day rolling average (up to 10080 1-min bars)
    lookback = min(len(volumes) - 1, 10_080)
    if lookback >= 20:
        avg_vol_7d = sum(volumes[-lookback:-1]) / lookback
        if avg_vol_7d > 0:
            ratio = volumes[-1] / avg_vol_7d
            if ratio > 2.0:
                flags.append(AnomalyFlag(
                    symbol=symbol,
                    flag_type="VOLUME_SURGE",
                    volume_ratio_7d=round(ratio, 2),
                    description=f"{symbol} volume {ratio:.1f}× 7-day avg (current={volumes[-1]:,.0f})",
                ))

    return flags


class ScannerAgent:
    """
    Two-tier scanner.

    Tier 1 (30 min): Sonnet evaluates the UNIVERSE_SYMBOLS universe,
    scores TA signals, and selects the top MAX_ACTIVE_SYMBOLS for active monitoring.

    Tier 2 (5 min): AI scores active symbols and writes verdicts.
    Results pushed to SSE + persisted to DB.
    """

    def __init__(
        self,
        push_fn: Callable[[dict], None],
        get_buffer_fn: Callable,
        get_research_fn: Optional[Callable] = None,
        set_equity_symbols_fn: Optional[Callable] = None,
    ):
        self._push                  = push_fn
        self._get_buffer            = get_buffer_fn
        self._get_research          = get_research_fn
        self._set_equity_symbols_fn = set_equity_symbols_fn
        self._running     = False
        self._last_scan:      Optional[datetime] = None
        self._last_discovery: Optional[datetime] = None
        self._results:        list[dict] = []
        # Active symbol set — starts from top seeds across both asset classes
        self._active_symbols: list[str] = list(
            dict.fromkeys(_CRYPTO_SEED[:6] + _EQUITY_SEED[:6])
        )

    def get_last_results(self) -> list[dict]:
        """Returns the most recent scan results for REST polling."""
        return self._results

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def run(self):
        """Background entry point — runs both tiers concurrently."""
        self._running = True
        await self._seed_buffer_with_history()
        await asyncio.sleep(WARMUP_DELAY)
        logger.info("[SCANNER] Agent started (scan=%ds, discovery=%ds)", SCAN_INTERVAL, DISCOVERY_INTERVAL)
        await asyncio.gather(
            self._scan_loop(),
            self._discovery_loop(),
        )

    async def _seed_buffer_with_history(self) -> None:
        """
        Pre-populate the OHLCV buffer with 1-min REST bars for every seed symbol.
        Without this, only live-streamed symbols have enough bars for TA scoring,
        which locks the scanner permanently to BTC/ETH/SOL.
        Fetches 120 1-min bars (~2 hours) per symbol — enough for EMA20, RSI14, BBands.
        """
        try:
            from config import settings
            from datetime import timedelta
            from alpaca.data.timeframe import TimeFrame

            api_key    = settings.alpaca_api_key_id
            api_secret = settings.alpaca_api_secret_key
            universe   = get_universe()
            crypto_syms  = [s for s in universe if "/" in s]
            equity_syms  = [s for s in universe if "/" not in s]
            end   = datetime.now(timezone.utc)
            start = end - timedelta(hours=3)
            buf   = self._get_buffer()

            if buf is None:
                return

            # Crypto bars
            if crypto_syms:
                try:
                    from alpaca.data.historical import CryptoHistoricalDataClient
                    from alpaca.data.requests import CryptoBarsRequest
                    client = CryptoHistoricalDataClient(api_key, api_secret)
                    req    = CryptoBarsRequest(
                        symbol_or_symbols=crypto_syms,
                        timeframe=TimeFrame.Minute,
                        start=start, end=end,
                    )
                    bars_df = client.get_crypto_bars(req).df
                    if not bars_df.empty:
                        for sym in bars_df.index.get_level_values(0).unique():
                            sym_df = bars_df.xs(sym, level=0) if isinstance(bars_df.index, pd.MultiIndex) else bars_df
                            buf.ingest_ohlcv_df(sym, sym_df)
                            logger.info("[SCANNER] Seeded buffer: %s (%d bars)", sym, len(sym_df))
                except Exception as e:
                    logger.warning("[SCANNER] Crypto history seed failed: %s", e)

            # Equity bars (market hours only — may return empty outside session)
            if equity_syms:
                try:
                    from alpaca.data.historical import StockHistoricalDataClient
                    from alpaca.data.requests import StockBarsRequest
                    from alpaca.data.enums import DataFeed
                    client = StockHistoricalDataClient(api_key, api_secret)
                    req    = StockBarsRequest(
                        symbol_or_symbols=equity_syms,
                        timeframe=TimeFrame.Minute,
                        start=start, end=end,
                        feed=DataFeed.IEX,
                    )
                    bars_df = client.get_stock_bars(req).df
                    if not bars_df.empty:
                        for sym in bars_df.index.get_level_values(0).unique():
                            sym_df = bars_df.xs(sym, level=0) if isinstance(bars_df.index, pd.MultiIndex) else bars_df
                            buf.ingest_ohlcv_df(sym, sym_df)
                            logger.info("[SCANNER] Seeded buffer: %s (%d bars)", sym, len(sym_df))
                except Exception as e:
                    logger.warning("[SCANNER] Equity history seed failed: %s", e)

        except Exception as e:
            logger.warning("[SCANNER] Buffer seed skipped: %s", e)

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

        # Score every universe symbol deterministically (uses live dynamic universe)
        universe_scored = []
        for symbol in get_universe():
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

        # Build research context from ResearchAgent if available and fresh
        research_context = ""
        if self._get_research:
            ra = self._get_research()
            if ra:
                brief = ra.get_latest_brief()
                if brief:
                    research_context = (
                        f"\n\nResearch Intelligence (Gemini 2.5 Flash, {brief.generated_at}):\n"
                        f"Macro: {brief.macro_theme}\n"
                        f"Catalysts: {', '.join(brief.catalysts[:3])}\n"
                        f"Risks: {', '.join(brief.risks[:3])}\n"
                        f"Recommended focus: {', '.join(brief.recommended_focus)}\n"
                        f"Sentiments: {'; '.join(f'{s.symbol}={s.sentiment}({s.confidence:.0%})' for s in brief.sentiment_by_symbol)}"
                    )

        # Gemini 2.0 Flash ranks and selects the best symbols
        selected = await self._gemini_discovery(universe_scored, position_symbols, research_context)

        # Discovery drives active list; position symbols always appended; fall back to seeds
        merged = list(dict.fromkeys(selected + position_symbols))
        if not merged:
            merged = list(dict.fromkeys(_CRYPTO_SEED[:3] + _EQUITY_SEED[:3]))
        self._active_symbols = merged[:MAX_ACTIVE_SYMBOLS]

        # Notify engine of any newly discovered equity symbols
        equity_discovered = [s for s in self._active_symbols if "/" not in s]
        if equity_discovered and self._set_equity_symbols_fn:
            self._set_equity_symbols_fn(equity_discovered)

        now = _utcnow()
        self._last_discovery = now

        self._push({
            "type":      "discover",
            "text":      f"[DISCOVERY] Active watchlist updated: {', '.join(self._active_symbols)}",
            "symbols":   self._active_symbols,
            "timestamp": now.isoformat(),
        })

        logger.info("[SCANNER] Discovery complete — active: %s", self._active_symbols)

    async def _gemini_discovery(
        self,
        scored: list[dict],
        held_symbols: list[str],
        research_context: str = "",
    ) -> list[str]:
        """
        Asks Gemini 2.0 Flash to select the top symbols from a pre-scored list.
        Injects research context from ResearchAgent when available.
        Budget: 800 output tokens.
        """
        try:
            from agents.factory import swarm_factory
            model = swarm_factory.build_model(model_level="discovery", max_tokens=800)
            if not model:
                raise RuntimeError("discovery model unavailable")

            from langchain_core.messages import HumanMessage, SystemMessage

            held_str = ", ".join(held_symbols) if held_symbols else "none"
            universe_str = "\n".join(
                f"  {s['symbol']:12s}  score={s['score']:+.2f}  signal={s['signal']:8s}  "
                f"price=${s['price']:,.2f}  RSI={s.get('rsi') or 'N/A'}"
                for s in sorted(scored, key=lambda x: abs(x["score"]), reverse=True)
            )
            knowledge_ctx = _load_knowledge_context(20)
            knowledge_section = f"\n\n{knowledge_ctx}" if knowledge_ctx else ""

            response = await model.ainvoke([
                SystemMessage(content=(
                    "You are a quantitative multi-asset portfolio manager covering crypto and US equities. "
                    "Select the best symbols to actively monitor and trade from the scored universe.\n"
                    f"Constraints:\n"
                    f"- Always include held positions: {held_str}\n"
                    f"- Select no more than {MAX_ACTIVE_SYMBOLS} symbols total\n"
                    f"- Prioritise symbols with strong directional signals (BUY or SELL)\n"
                    f"- Avoid correlated pairs\n"
                    f"- Prioritise high-conviction directional signals across all asset classes\n\n"
                    "Respond ONLY with a comma-separated list of symbols in priority order. "
                    "Example: BTC/USD, AAPL, ETH/USD, SPY"
                )),
                HumanMessage(content=f"Universe TA scores:\n{universe_str}{research_context}{knowledge_section}"),
            ])

            # Parse comma-separated symbol list from response
            raw = response.content.strip()
            selected: list[str] = []
            for token in raw.replace("\n", ",").split(","):
                sym = token.strip().upper()
                # Normalize compact crypto format: "BTCUSD" → "BTC/USD"
                if "/" not in sym and sym.endswith("USD") and len(sym) > 4:
                    sym = sym[:-3] + "/USD"
                if sym and any(s["symbol"] == sym for s in scored):
                    selected.append(sym)
                if len(selected) >= MAX_ACTIVE_SYMBOLS:
                    break

            # Log cost
            try:
                usage = getattr(response, "usage_metadata", None) or {}
                t_in  = usage.get("input_tokens", 0) or usage.get("prompt_token_count", 0)
                t_out = usage.get("output_tokens", 0) or usage.get("candidates_token_count", 0)
                cost  = (t_in * GEMINI_FLASH_COST_IN + t_out * GEMINI_FLASH_COST_OUT) / 1_000_000
                from db.database import _get_session_factory
                from db.models import LLMUsage
                async with _get_session_factory()() as _s:
                    _s.add(LLMUsage(
                        model=GEMINI_FLASH_MODEL,
                        tokens_in=t_in,
                        tokens_out=t_out,
                        cost_usd=cost,
                        purpose="scanner_discovery",
                    ))
                    await _s.commit()
            except Exception as _le:
                logger.debug("[SCANNER] Discovery cost log failed: %s", _le)

            logger.info("[SCANNER] Discovery selected: %s", selected)
            return selected

        except Exception as e:
            logger.debug("[SCANNER] Discovery unavailable: %s", e)
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
        ai_verdicts = await self._ai_rank(scored)

        now = _utcnow()
        self._last_scan = now
        self._results = [
            {
                "symbol":        s["symbol"],
                "score":         round(s["score"], 4),
                "signal":        s["signal"],
                "price":         s.get("price", 0),
                "rsi":           s.get("rsi"),
                "vol_surge":     s.get("vol_surge"),
                "summary":       s["summary"],
                "verdict":       ai_verdicts.get(s["symbol"], s["summary"]),
                "anomaly_flags": s.get("anomaly_flags", []),
                "timestamp":     now.isoformat(),
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
            df = buffer.get_candles(symbol, "1Min")
            if df is None or df.empty or len(df) < 20:
                return None
            bars    = df.to_dict(orient="records")
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

            # Anomaly detection — flags price spikes and volume surges
            anomaly_flags = detect_anomalies(symbol, bars)
            if anomaly_flags:
                for flag in anomaly_flags:
                    logger.warning("[SCANNER] ANOMALY %s: %s", flag.flag_type, flag.description)

            ema_spread = round((ema20 - price) / price, 6) if price > 0 else 0.0
            return {
                "symbol":        symbol,
                "score":         score,
                "signal":        signal,
                "summary":       summary,
                "price":         price,
                "rsi":           round(rsi, 1) if rsi is not None else None,
                "vol_surge":     round(vol_surge, 2),
                "band_pct":      round(band_pct, 3),
                "ema_spread":    ema_spread,
                "anomaly_flags": [{"type": f.flag_type, "description": f.description} for f in anomaly_flags],
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
    # LLM verdict (AI — fast tier)
    # ------------------------------------------------------------------

    async def _ai_rank(self, scored: list[dict]) -> dict[str, str]:
        """AI produces a one-line verdict per symbol. Falls back to TA summary."""
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
            response = await model.ainvoke(
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
                t_in  = usage.get("input_tokens", 0) or usage.get("prompt_token_count", 0)
                t_out = usage.get("output_tokens", 0) or usage.get("candidates_token_count", 0)
                cost  = (t_in * GEMINI_FLASH_COST_IN + t_out * GEMINI_FLASH_COST_OUT) / 1_000_000
                from db.database import _get_session_factory
                from db.models import LLMUsage
                async with _get_session_factory()() as _s:
                    _s.add(LLMUsage(
                        model=GEMINI_FLASH_MODEL,
                        tokens_in=t_in,
                        tokens_out=t_out,
                        cost_usd=cost,
                        purpose="scanner_verdict",
                    ))
                    await _s.commit()
            except Exception as _le:
                logger.debug("[SCANNER] LLM usage log failed: %s", _le)

        except Exception as e:
            logger.debug("[SCANNER] AI unavailable: %s", e)

        for s in scored:
            if s["symbol"] not in verdicts:
                verdicts[s["symbol"]] = s["summary"]

        return verdicts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist(self, results: list[dict]):
        """Upserts WatchlistItem rows in SQLite including TA metrics."""
        try:
            from db.database import _get_session_factory
            from db.models import WatchlistItem
            from sqlalchemy import select

            async with _get_session_factory()() as session:
                for r in results:
                    sym = r["symbol"]
                    ac = "CRYPTO" if "/" in sym else "EQUITY"
                    row = (await session.execute(
                        select(WatchlistItem).where(WatchlistItem.symbol == sym)
                    )).scalar_one_or_none()
                    if row:
                        row.score        = r["score"]
                        row.signal       = r["signal"]
                        row.verdict      = r["verdict"]
                        row.last_scanned = _utcnow()
                        row.asset_class  = ac
                        row.rsi          = r.get("rsi")
                        row.ema_spread   = r.get("ema_spread")
                        row.volume_ratio = r.get("vol_surge")
                        row.bb_position  = r.get("band_pct")
                    else:
                        session.add(WatchlistItem(
                            symbol=sym,
                            score=r["score"],
                            signal=r["signal"],
                            verdict=r["verdict"],
                            last_scanned=_utcnow(),
                            active=True,
                            asset_class=ac,
                            rsi=r.get("rsi"),
                            ema_spread=r.get("ema_spread"),
                            volume_ratio=r.get("vol_surge"),
                            bb_position=r.get("band_pct"),
                        ))
                await session.commit()
        except Exception as e:
            logger.warning("[SCANNER] DB persist failed: %s", e)

    def stop(self):
        self._running = False
