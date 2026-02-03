"""
Track Kalshi leaderboard and alert on consensus picks
Run this daily to follow smart money
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.leaderboard_tracker import KalshiLeaderboardTracker
import argparse


def main():
    parser = argparse.ArgumentParser(description="Track Kalshi leaderboard smart money")
    parser.add_argument("--top", type=int, default=10, help="Number of top traders to track")
    parser.add_argument("--min-consensus", type=int, default=3, help="Min traders for consensus")
    args = parser.parse_args()
    
    tracker = KalshiLeaderboardTracker()
    
    print(f"📊 Tracking top {args.top} Kalshi traders...")
    print(f"🎯 Consensus threshold: {args.min_consensus}+ traders\n")
    
    # Get consensus picks
    consensus = tracker.get_consensus_picks(min_traders=args.min_consensus)
    
    if not consensus:
        print("No consensus picks found.")
        print("Smart money is divided - wait for clearer signals.\n")
        return
    
    print(f"🚨 {len(consensus)} SMART MONEY CONSENSUS PICKS:\n")
    print("="*70)
    
    for i, pick in enumerate(consensus, 1):
        print(f"\n{i}. Market: {pick['ticker']}")
        print(f"   Side: {pick['side'].upper()}")
        print(f"   Sharp traders: {pick['trader_count']}")
        print(f"   Avg entry price: {pick['avg_entry_price']*100:.1f}¢")
        print(f"   Traders: {', '.join(pick['traders'])}")
        
        # Calculate recommended position size
        bankroll = 1000  # Adjust to your bankroll
        position_size = bankroll * 0.10  # 10% per position
        contracts = int(position_size / pick['avg_entry_price'])
        
        print(f"\n   💰 Recommended: Buy {contracts} contracts at ≤{pick['avg_entry_price']*100:.0f}¢")
        print(f"   Risk: ${position_size:.0f} | Max profit: ${contracts * (1 - pick['avg_entry_price']):.0f}")
    
    print("\n" + "="*70)
    print("\n✅ Action: Copy these positions on Kalshi")
    print("⏰ Check back tomorrow for new consensus picks\n")


if __name__ == "__main__":
    main()
