#!/bin/bash
# Deploy Kalshi Auto-Trader - AUTONOMOUS EXECUTION

SESSION="kalshi-auto-trader"

echo "🤖 DEPLOYING KALSHI AUTO-TRADER"
echo ""
echo "⚠️  WARNING: This will AUTO-EXECUTE trades based on signals"
echo ""
echo "Safety Limits:"
echo "  • Max position: \$15/trade"
echo "  • Max daily: 10 trades"
echo "  • Min confidence: 70%"
echo "  • Max exposure: \$150 total"
echo ""
read -p "Deploy auto-trader? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "❌ Deployment cancelled"
    exit 1
fi

# Kill existing session
tmux kill-session -t $SESSION 2>/dev/null

# Create new session
tmux new-session -d -s $SESSION

# Set up and run
tmux send-keys -t $SESSION "cd /root/.openclaw/workspace/Kalshi" C-m
tmux send-keys -t $SESSION "export KALSHI_API_KEY_ID=e456cf0a-f5c6-4422-b37d-60e1cf6708fd" C-m
tmux send-keys -t $SESSION "export KALSHI_PRIVATE_KEY_PATH=/root/.openclaw/workspace/Kalshi/kalshi_private_key.pem" C-m
tmux send-keys -t $SESSION "python3 automation/auto_trader.py --enabled --max-position 15 --max-trades 10 --min-confidence 0.70 --max-exposure 150" C-m

echo ""
echo "✅ Kalshi Auto-Trader DEPLOYED"
echo "   Session: $SESSION"
echo "   Status: AUTONOMOUS EXECUTION ACTIVE"
echo ""
echo "Commands:"
echo "  tmux attach -t $SESSION              # View live feed"
echo "  tmux kill-session -t $SESSION        # STOP auto-trading"
echo "  cat data/auto_trader_state.json      # Check status"
echo ""
echo "🔥 AUTO-TRADING IS NOW ACTIVE"
echo "   Scanning every 60 seconds"
echo "   Will execute trades automatically when 70%+ confidence"
echo ""
