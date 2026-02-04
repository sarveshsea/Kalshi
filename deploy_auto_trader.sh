#!/bin/bash
# Deploy Kalshi Auto-Trader in tmux.

set -euo pipefail

SESSION="kalshi-auto-trader"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-paper}" # paper | live

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

echo "🤖 Deploying Kalshi Auto-Trader"
echo "Workspace: $ROOT_DIR"
echo "Mode: $MODE"
echo ""

if [[ "$MODE" != "paper" && "$MODE" != "live" ]]; then
  echo "Usage: $0 [paper|live]"
  exit 1
fi

if [[ "$MODE" == "live" ]]; then
  if [[ -z "${KALSHI_API_KEY_ID:-}" || -z "${KALSHI_PRIVATE_KEY_PATH:-}" ]]; then
    echo "❌ Live mode requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in env/.env"
    exit 1
  fi
  echo "🔒 Checking paper-trading gate before live deploy..."
  if ! python3 "$ROOT_DIR/ops/check_go_live_gate.py" --state "$ROOT_DIR/data/auto_trader_state.json"; then
    echo "❌ Go-live gate failed. Stay in paper mode."
    exit 1
  fi
fi

read -r -p "Start auto-trader in $MODE mode? (yes/no): " confirm
if [[ "$confirm" != "yes" ]]; then
  echo "❌ Deployment cancelled"
  exit 1
fi

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION"

BASE_CMD="python3 automation/auto_trader.py \
  --env prod \
  --max-position 20 \
  --min-position 5 \
  --max-trades 12 \
  --max-exposure 150 \
  --min-confidence 0.65 \
  --min-edge 0.03 \
  --min-net-edge 0.015 \
  --max-spread 0.06 \
  --fee-per-contract 0.008 \
  --slippage-factor 0.35 \
  --take-profit 0.20 \
  --stop-loss 0.12 \
  --max-holding-minutes 240 \
  --interval 30"

if [[ "$MODE" == "live" ]]; then
  CMD="$BASE_CMD --live"
else
  CMD="$BASE_CMD --paper-bankroll 250"
fi

tmux send-keys -t "$SESSION" "cd '$ROOT_DIR'" C-m
tmux send-keys -t "$SESSION" "$CMD" C-m

echo ""
echo "✅ Auto-trader deployed"
echo "Session: $SESSION"
echo "Mode: $MODE"
echo ""
echo "Useful commands:"
echo "  tmux attach -t $SESSION"
echo "  tmux kill-session -t $SESSION"
echo "  cat $ROOT_DIR/data/auto_trader_state.json"
