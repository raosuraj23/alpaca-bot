import json
from quant.data_buffer import market_buffer
print("MARKET_BUFFER_SNAPSHOT:")
print(json.dumps(market_buffer.snapshot(), indent=2))
import core.state as s
print("STREAM_SYMBOLS:")
print(json.dumps({"EQUITY_STREAM_SYMBOLS": s.EQUITY_STREAM_SYMBOLS, "CRYPTO_STREAM_SYMBOLS": s.CRYPTO_STREAM_SYMBOLS}, indent=2, default=str))
import zoneinfo, datetime
ET = zoneinfo.ZoneInfo("America/New_York")
print("ET_TIME:")
print(datetime.datetime.now(ET).isoformat())
print("PRESENT_FLAGS:")
print("scanner_agent_present=", bool(s.scanner_agent))
print("crypto_stream_present=", bool(s._crypto_stream_state.get("stream")))
print("equity_stream_present=", bool(s._equity_stream_state.get("stream")))
