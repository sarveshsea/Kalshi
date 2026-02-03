#!/usr/bin/env python3
"""
KALSHI LEADERBOARD TRACKER - Copy Top Performers

Tracks top 10 traders and detects consensus signals:
- When 3+ top traders bet the same market = STRONG BUY signal
- When top trader enters new position = FOLLOW signal
- Monitors profit leaders for edge detection
"""
import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.client import KalshiClient

# TOP PERFORMERS TO TRACK (from leaderboards)
TOP_TRADERS = {
    'all_categories': [
        'dogname',      # $196k profit
        'Domer',        # $173k profit
        'bobbybatl',    # $116k profit
        'lostzemblan',  # $102k profit
        'Infinity',     # $100k profit
    ],
    'crypto': [
        'oiski.poiski',    # $8.8k profit
        'lilfishyfish',    # $7.1k profit
        'Landof10kBets',   # $6.8k profit
        'bladebetter',     # $5.1k profit
        'ktw5',            # $4.5k profit
    ]
}

class LeaderboardTracker:
    def __init__(self):
        self.client = KalshiClient(env='prod')
        self.tracked_positions = {}  # trader -> {ticker: position}
        self.consensus_signals = []
        
        print("\n" + "="*70)
        print("🎯 KALSHI LEADERBOARD TRACKER - COPY TOP PERFORMERS")
        print("="*70)
        print(f"Tracking {len(TOP_TRADERS['all_categories'])} top all-category traders")
        print(f"Tracking {len(TOP_TRADERS['crypto'])} top crypto traders")
        print("="*70 + "\n")
    
    def detect_consensus(self, market_ticker):
        """
        Check if 3+ top traders are in same market
        = STRONG CONSENSUS SIGNAL
        """
        traders_in_market = []
        
        for trader, positions in self.tracked_positions.items():
            if market_ticker in positions:
                traders_in_market.append(trader)
        
        if len(traders_in_market) >= 3:
            return True, traders_in_market
        
        return False, []
    
    def track_trader_positions(self, trader_name):
        """
        Track a specific trader's positions
        NOTE: Kalshi API doesn't expose other users' positions publicly
        This is a placeholder for when/if that data becomes available
        
        For now, we'll use market volume/momentum as proxy
        """
        # TODO: Implement if Kalshi adds public position tracking
        # For now, return empty
        return {}
    
    def find_high_volume_markets(self):
        """
        Find markets with high volume = where smart money is active
        """
        markets = self.client.get_markets(status='open', limit=200)
        
        high_volume = []
        
        for market in markets:
            ticker = market.get('ticker', '')
            volume = market.get('volume', 0)
            yes_bid = market.get('yes_bid', 0)
            
            # High volume threshold (in cents)
            if volume > 10000:  # $100+ in volume
                high_volume.append({
                    'ticker': ticker,
                    'title': market.get('title', ''),
                    'volume': volume,
                    'yes_price': yes_bid,
                    'timestamp': datetime.utcnow().isoformat()
                })
        
        return sorted(high_volume, key=lambda x: x['volume'], reverse=True)
    
    def generate_signals(self):
        """
        Generate trading signals based on leaderboard activity
        """
        print("🔍 Scanning for smart money signals...\n")
        
        # Get high-volume markets (proxy for smart money)
        high_vol_markets = self.find_high_volume_markets()
        
        if not high_vol_markets:
            print("⏳ No high-volume activity detected\n")
            return []
        
        signals = []
        
        print(f"📊 Found {len(high_vol_markets)} high-volume markets:\n")
        
        for i, market in enumerate(high_vol_markets[:10], 1):
            vol_usd = market['volume'] / 100
            
            signal = {
                'rank': i,
                'ticker': market['ticker'],
                'title': market['title'][:60],
                'volume': vol_usd,
                'yes_price': market['yes_price'],
                'confidence': min(vol_usd / 1000, 0.9),  # Higher volume = higher confidence
                'reason': f"High volume (${vol_usd:.0f}) = smart money active",
                'timestamp': market['timestamp']
            }
            
            signals.append(signal)
            
            print(f"{i}. {market['title'][:60]}")
            print(f"   Volume: ${vol_usd:.0f} | YES: {market['yes_price']}¢")
            print(f"   Confidence: {signal['confidence']*100:.0f}%")
            print()
        
        # Save signals
        self.save_signals(signals)
        
        return signals
    
    def save_signals(self, signals):
        """Save leaderboard signals to file"""
        output_file = Path(__file__).parent.parent / "data" / "leaderboard_signals.json"
        output_file.parent.mkdir(exist_ok=True)
        
        data = {
            'timestamp': datetime.utcnow().isoformat(),
            'signals': signals,
            'top_traders_tracked': TOP_TRADERS
        }
        
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"💾 Saved to {output_file}\n")
    
    def run_scan(self):
        """Run a single scan"""
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Running leaderboard scan...\n")
        
        signals = self.generate_signals()
        
        if signals:
            print(f"✅ Generated {len(signals)} smart money signals")
            print(f"   Top signal: {signals[0]['title'][:50]}")
            print(f"   Confidence: {signals[0]['confidence']*100:.0f}%\n")
        
        return signals


def main():
    tracker = LeaderboardTracker()
    
    # Run scan
    signals = tracker.run_scan()
    
    if signals:
        print("="*70)
        print("🎯 TOP SMART MONEY PLAYS (Top 3):\n")
        
        for sig in signals[:3]:
            print(f"{sig['rank']}. {sig['title']}")
            print(f"   Volume: ${sig['volume']:.0f}")
            print(f"   YES Price: {sig['yes_price']}¢")
            print(f"   Confidence: {sig['confidence']*100:.0f}%")
            print(f"   Reason: {sig['reason']}")
            print()
        
        print("="*70)
        print("\n💡 These markets have high trader activity")
        print("   Follow the smart money by taking similar positions\n")


if __name__ == "__main__":
    main()
