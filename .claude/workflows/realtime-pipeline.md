name: realtime-pipeline

steps:
  - agent: realtime-data-agent
    action: design_websocket

  - agent: trading-engine-agent
    action: consume_market_data

  - agent: ai-insights-agent
    action: analyze_stream

  - agent: ui-agent
    action: bind_data_to_ui