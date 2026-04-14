name: build-dashboard

steps:
  - agent: orchestrator-agent
    action: decompose_task

  - parallel:
      - agent: ui-agent
        action: build_layout

      - agent: charting-agent
        action: create_charts

      - agent: realtime-data-agent
        action: setup_streams

  - agent: orchestrator-agent
    action: merge_outputs

  - agent: testing-agent
    action: validate_ui