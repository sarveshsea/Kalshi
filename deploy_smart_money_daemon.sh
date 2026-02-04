#!/bin/bash
# Deploy market-flow smart-money daemon in tmux background.

SESSION="kalshi-daemon"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Kill existing session if running
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION

# Set up environment and run daemon
tmux send-keys -t $SESSION "cd \"$ROOT_DIR\"" C-m
tmux send-keys -t $SESSION "python3 automation/smart_money_daemon.py --paper-bankroll 250 --max-position 20 --max-trades 12 --interval-seconds 60" C-m

echo "✅ Market-flow smart-money daemon deployed"
echo "   Session: $SESSION"
echo "   Monitoring: Every 60 seconds"
echo "   Mode: Paper (default)"
echo ""
echo "Commands:"
echo "  tmux attach -t $SESSION    # View live feed"
echo "  tmux kill-session -t $SESSION    # Stop daemon"
echo ""
echo "🔥 Market-flow mode active"
