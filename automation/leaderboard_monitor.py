#!/usr/bin/env python3
"""
🤖 LEVEL 5 AUTOMATION: Leaderboard Monitor
Unlocked at Level 5 - Smart money copy bot

Monitors Kalshi leaderboard every 30 minutes and auto-executes on consensus
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.leaderboard_tracker import KalshiLeaderboardTracker
import time
from datetime import datetime


def monitor_leaderboard(interval_minutes=30):
    """
    Monitor leaderboard and execute on consensus
    
    1. Fetch top 10 traders
    2. Check their current positions
    3. Detect 3+ trader consensus
    4. Auto-execute within 1 hour
    5. Track performance
    """
    print("🤖 LEADERBOARD MONITOR - Level 5 Automation")
    print("="*70)
    print(f"Monitoring every {interval_minutes} minutes")
    print("Auto-execute on 3+ trader consensus\n")
    
    tracker = KalshiLeaderboardTracker()
    cycle = 0
    
    while True:
        cycle += 1
        timestamp = datetime.utcnow().strftime("%H:%M UTC")
        print(f"[{timestamp}] Cycle #{cycle}")
        
        # Get consensus picks
        consensus = tracker.get_consensus_picks(min_traders=3)
        
        if consensus:
            print(f"\n🚨 {len(consensus)} CONSENSUS PICKS DETECTED:")
            
            for pick in consensus:
                print(f"\n  📊 {pick['ticker']}")
                print(f"     Side: {pick['side'].upper()}")
                print(f"     Traders: {pick['trader_count']} ({', '.join(pick['traders'])})")
                print(f"     Avg entry: {pick['avg_entry_price']*100:.1f}¢")
                
                # Calculate position size
                bankroll = 1000  # Would load from status
                position_size = bankroll * 0.10
                contracts = int(position_size / pick['avg_entry_price'])
                
                print(f"\n     💰 AUTO-EXECUTE:")
                print(f"        Buy {contracts} contracts at ≤{pick['avg_entry_price']*100:.0f}¢")
                print(f"        Risk: ${position_size:.0f}")
                print(f"        Max profit: ${contracts * (1 - pick['avg_entry_price']):.0f}")
                
                # Would execute here
                # client.place_order(...)
                
                print(f"     ✅ Order placed (simulated)")
        else:
            print(f"  ✓ No consensus found")
        
        print(f"\n⏰ Next check in {interval_minutes} minutes")
        print("-"*70)
        
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    print("🤖 Level 5 Automation: LEADERBOARD MONITOR")
    print("Requires: Level 5 unlocked")
    print("Schedule: Continuous (every 30 min)\n")
    
    # Check level
    import json
    with open("../../level_status.json", 'r') as f:
        status = json.load(f)
    
    if status['current_level'] < 5:
        print(f"❌ LOCKED - Current level: {status['current_level']}")
        print(f"   Unlock at Level 5")
        print(f"   Progress: {status['evolution_progress']}")
        exit(1)
    
    print("✅ Level 5 unlocked - Starting monitor...\n")
    
    try:
        monitor_leaderboard(interval_minutes=30)
    except KeyboardInterrupt:
        print("\n\n👋 Monitor stopped")
