# Legacy Mode Removed

The previous "degenerate/ruthless" configs are intentionally retired.

Use the risk-managed flow:

1. Build alpha signals (`kalshi_signal_pack/generate_signals.py` or `ops/build_flow_alpha.py`)
2. Trade only net-edge opportunities (`automation/auto_trader.py`)
3. Pass hard paper gates (`ops/check_go_live_gate.py`) before live deploy

No strategy should bypass fee/slippage-adjusted net-edge checks.
