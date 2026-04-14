name: deploy-strategy

steps:
  - agent: trading-engine-agent
    action: implement_strategy

  - agent: risk-agent
    action: apply_risk_rules

  - agent: ai-insights-agent
    action: generate_explanations

  - agent: ui-agent
    action: create_control_panel

  - agent: testing-agent
    action: simulate_trades