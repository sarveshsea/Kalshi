#!/bin/bash
# Deploy Kalshi Smart Money Daemon in tmux background

SESSION="kalshi-daemon"

# Kill existing session if running
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION

# Set up environment and run daemon
tmux send-keys -t $SESSION "cd /root/.openclaw/workspace/Kalshi" C-m
tmux send-keys -t $SESSION "export KALSHI_API_KEY_ID=e456cf0a-f5c6-4422-b37d-60e1cf6708fd" C-m
tmux send-keys -t $SESSION "export KALSHI_PRIVATE_KEY_PATH=/root/.openclaw/workspace/Kalshi/kalshi_private_key.pem" C-m
tmux send-keys -t $SESSION "python3 automation/smart_money_daemon.py --stake 15 --max-trades 10" C-m

echo "✅ Kalshi Smart Money Daemon deployed"
echo "   Session: $SESSION"
echo "   Monitoring: Every 30 seconds"
echo "   Auto-execute: Disabled (manual signals for now)"
echo ""
echo "Commands:"
echo "  tmux attach -t $SESSION    # View live feed"
echo "  tmux kill-session -t $SESSION    # Stop daemon"
echo ""
echo "🔥 ZERO LATENCY MODE ACTIVE"
