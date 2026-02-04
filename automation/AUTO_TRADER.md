# Auto-Trader (Refactored)

The auto-trader is now **alpha-gated** and risk-managed:

- Trades only tickers present in `data/alpha_signals.json`
- Uses fee/slippage-adjusted edge (`fair_prob - entry_price - costs`) for both YES and NO
- Sizes with fractional Kelly + hard caps
- Exits with take-profit, stop-loss, time-stop, and edge-reversal
- Persists full state + performance stats in `data/auto_trader_state.json`

## Alpha Signal Input

Use strict signal generation (requires real Kalshi ticker + fair_yes_probability + confidence):

```bash
python3 kalshi_signal_pack/generate_signals.py \
  --input RareCandy/exports/rarecandy_last_20260204T014118Z.csv \
  --top_k 20 \
  --output /tmp/signals.csv \
  --tg /tmp/telegram_message.txt \
  --bankroll 100 \
  --alpha data/alpha_signals.json
```

Or generate from public flow data:

```bash
python3 ops/build_flow_alpha.py --alpha-out data/alpha_signals.json
```

Capture/replay harness for deterministic paper tests:

```bash
python3 ops/capture_trades_snapshots.py --out data/trades_snapshots.jsonl
python3 ops/replay_trades_backtest.py --snapshot-file data/trades_snapshots.jsonl --state-out data/auto_trader_state.json
```

Parameter sweep (ranked by holdout expectancy/profit factor/drawdown):

```bash
python3 ops/sweep_replay_params.py \
  --snapshot-file data/trades_snapshots.jsonl \
  --out data/replay_sweeps/latest.json \
  --top-n 20
```

Calibrate fair probabilities from sweep results:

```bash
python3 ops/calibrate_alpha.py \
  --replay-results data/replay_sweeps/latest.json \
  --out data/alpha_calibration.json
```

## Run

Paper mode (default):

```bash
python3 automation/auto_trader.py --run-once
python3 automation/auto_trader.py
```

Live mode:

```bash
python3 automation/auto_trader.py --live --run-once
python3 automation/auto_trader.py --live
```

## Performance Report

```bash
python3 ops/report_auto_trader_performance.py
```

Daily quant PM report (signal quality, execution costs, gate trajectory, GO/NO-GO):

```bash
python3 ops/quant_pm_report.py \
  --state data/auto_trader_state.json \
  --alpha data/alpha_signals.json \
  --output data/quant_pm_report.md \
  --json-output data/quant_pm_report.json
```

## Go-Live Gate

Stay in paper until:
- trades >= 300
- expectancy > 0
- profit_factor >= 1.15
- controlled drawdown
- cost telemetry coverage >= 95%
- holdout expectancy > 0 for trailing 100 and 200 trades
- no single ticker contributes > 25% of absolute PnL

```bash
python3 ops/check_go_live_gate.py --state data/auto_trader_state.json
./deploy_auto_trader.sh live
```

## One-Command Pipeline

```bash
python3 ops/run_quant_pipeline.py \
  --alpha-source flow \
  --paper-mode run-once \
  --emit-json-report
```

Continuous build loop until gates pass (paper-only by default):

```bash
python3 ops/continuous_build_until_pass.py \
  --env prod \
  --snapshot-file data/trades_snapshots.jsonl \
  --capture-cycles 30 \
  --capture-interval-seconds 30 \
  --sweep-max-runs 200 \
  --required-consecutive-pass 2
```

Replay pipeline:

```bash
python3 ops/run_quant_pipeline.py \
  --alpha-source flow \
  --paper-mode replay \
  --snapshot-file data/trades_snapshots.jsonl
```
