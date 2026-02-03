#!/usr/bin/env python3
"""
KALSHI SMART MONEY DAEMON - Zero Latency Autonomous Execution

Continuous monitoring of:
1. Market movements (volume spikes = smart money)
2. Pricing inefficiencies (mispricing = edge)
3. Consensus plays (3+ signals = high confidence)

Auto-executes on:
- High confidence (70%+)
- Clear edge (2x+ potential)
- Volume confirmation (smart money active)
"""
import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.client import KalshiClient

class SmartMoneyDaemon:
    def __init__(self, auto_execute=False, max_stake_per_bet=15, max_daily_trades=10):
        """
        Initialize autonomous trading daemon
        
        Args:
            auto_execute: If True, will auto-place trades (Level 5+)
            max_stake_per_bet: Max $ per position
            max_daily_trades: Safety limit
        """
        self.client = KalshiClient(env='prod')
        self.auto_execute = auto_execute
        self.max_stake = max_stake_per_bet
        self.max_daily = max_daily_trades
        
        self.daily_trades = 0
        self.positions_entered = []
        self.last_scan = None
        self.scan_interval = 30  # 30 seconds = zero latency
        
        # Track market state
        self.market_cache = {}
        self.last_volumes = {}
        
        print(f"\n{'='*70}")
        print("🔥 KALSHI SMART MONEY DAEMON - ZERO LATENCY MODE")
        print(f"{'='*70}")
        print(f"Auto-execute: {auto_execute}")
        print(f"Max stake/bet: ${self.max_stake}")
        print(f"Max daily trades: {self.max_daily}")
        print(f"Scan interval: {self.scan_interval}s")
        print(f"{'='*70}\n")
    
    def detect_volume_spike(self, ticker, current_volume):
        """Detect volume spikes = smart money entering"""
        if ticker not in self.last_volumes:
            self.last_volumes[ticker] = current_volume
            return False
        
        last_vol = self.last_volumes[ticker]
        if last_vol == 0:
            return False
        
        spike = (current_volume - last_vol) / last_vol
        self.last_volumes[ticker] = current_volume
        
        # 50%+ volume increase in 30s = smart money
        return spike > 0.5
    
    def calculate_edge(self, market):
        """
        Calculate trading edge from market data
        
        Returns: (action, confidence, reason)
        """
        ticker = market.get('ticker', '')
        yes_bid = market.get('yes_bid', 0)
        no_bid = market.get('no_bid', 0)
        volume = market.get('volume', 0)
        
        # Skip low-volume markets
        if volume < 500:
            return None, 0, "Low volume"
        
        # Skip extreme odds (lottery tickets or sure things)
        if yes_bid < 15 or yes_bid > 85:
            return None, 0, "Extreme odds"
        
        # Look for clear mispricing
        # Edge signals:
        # 1. Volume spike (smart money entering)
        # 2. Price < 40 or > 60 (clear directional bet)
        # 3. Bid-ask spread tight (liquid market)
        
        volume_spike = self.detect_volume_spike(ticker, volume)
        
        action = None
        confidence = 0
        reason = ""
        
        # LONG YES opportunities
        if yes_bid < 40:
            potential = 100 / yes_bid  # e.g., 30¢ → 3.3x
            confidence = (40 - yes_bid) / 40  # Bigger discount = higher confidence
            
            if volume_spike:
                confidence *= 1.5  # Boost confidence on volume spike
            
            if confidence > 0.6:  # 60%+ confidence
                action = "BUY_YES"
                reason = f"Underpriced @ {yes_bid}¢ (potential {potential:.1f}x)"
                if volume_spike:
                    reason += " + VOLUME SPIKE"
        
        # SHORT YES (buy NO) opportunities  
        elif yes_bid > 60:
            potential = 100 / no_bid
            confidence = (yes_bid - 60) / 40
            
            if volume_spike:
                confidence *= 1.5
            
            if confidence > 0.6:
                action = "BUY_NO"
                reason = f"Overpriced @ {yes_bid}¢ (NO @ {no_bid}¢, potential {potential:.1f}x)"
                if volume_spike:
                    reason += " + VOLUME SPIKE"
        
        return action, min(confidence, 0.95), reason
    
    def scan_markets(self):
        """Scan ECONOMICS & SPORTS markets for opportunities"""
        markets = self.client.get_markets(status='open', limit=200)
        
        # Filter for economics & sports by keywords in title/ticker
        econ_keywords = ['fed', 'inflation', 'cpi', 'gdp', 'unemployment', 'rate', 'jobs', 'economy', 'recession', 'treasury', 'bond']
        sports_keywords = ['nba', 'nhl', 'nfl', 'mlb', 'points', 'rebounds', 'assists', 'goals', 'touchdowns', 'wins', 'score']
        
        target_markets = []
        for m in markets:
            title = m.get('title', '').lower()
            ticker = m.get('ticker', '').lower()
            if any(kw in title or kw in ticker for kw in econ_keywords + sports_keywords):
                target_markets.append(m)
        
        opportunities = []
        
        for market in target_markets:
            action, confidence, reason = self.calculate_edge(market)
            
            if action and confidence >= 0.7:  # 70%+ confidence threshold
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                yes_bid = market.get('yes_bid', 0)
                no_bid = market.get('no_bid', 0)
                volume = market.get('volume', 0)
                
                opp = {
                    'ticker': ticker,
                    'title': title,
                    'action': action,
                    'confidence': confidence,
                    'reason': reason,
                    'yes_price': yes_bid,
                    'no_price': no_bid,
                    'volume': volume,
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                opportunities.append(opp)
        
        return sorted(opportunities, key=lambda x: x['confidence'], reverse=True)
    
    def execute_trade(self, opportunity):
        """Execute a trade (or log for manual execution)"""
        ticker = opportunity['ticker']
        action = opportunity['action']
        confidence = opportunity['confidence']
        
        # Check daily limit
        if self.daily_trades >= self.max_daily:
            print(f"⚠️  Daily trade limit reached ({self.max_daily})")
            return False
        
        # Check if already have position
        if ticker in self.positions_entered:
            print(f"⏭️  Already have position in {ticker}")
            return False
        
        if self.auto_execute:
            # TODO: Actual trade execution via API
            # For now, just log
            print(f"\n🚀 AUTO-EXECUTING TRADE:")
            print(f"   Ticker: {ticker}")
            print(f"   Action: {action}")
            print(f"   Confidence: {confidence*100:.0f}%")
            print(f"   Stake: ${self.max_stake}")
            print(f"   ⚠️  AUTO-EXECUTION NOT IMPLEMENTED YET")
            print(f"   Manual execution required\n")
        else:
            print(f"\n📢 HIGH-CONFIDENCE SIGNAL DETECTED:")
            print(f"   Ticker: {ticker}")
            print(f"   Title: {opportunity['title'][:60]}")
            print(f"   Action: {action}")
            print(f"   Price: {opportunity['yes_price']}¢")
            print(f"   Confidence: {confidence*100:.0f}%")
            print(f"   Reason: {opportunity['reason']}")
            print(f"   Recommended stake: ${self.max_stake}")
            print(f"   ⚠️  Manual execution required (auto-trade at Level 5)\n")
        
        # Track that we signaled this
        self.positions_entered.append(ticker)
        self.daily_trades += 1
        
        # Save to log
        self.log_trade(opportunity)
        
        return True
    
    def log_trade(self, opportunity):
        """Log trade signals to file"""
        log_file = Path(__file__).parent.parent / "data" / "smart_money_signals.jsonl"
        log_file.parent.mkdir(exist_ok=True)
        
        with open(log_file, 'a') as f:
            f.write(json.dumps(opportunity) + '\n')
    
    def run(self):
        """Main daemon loop - runs continuously"""
        cycle = 0
        
        print(f"🔄 Starting continuous monitoring...\n")
        
        try:
            while True:
                cycle += 1
                now = datetime.utcnow()
                
                print(f"[{now.strftime('%H:%M:%S')}] Cycle #{cycle} | Daily trades: {self.daily_trades}/{self.max_daily}")
                
                # Scan markets
                opportunities = self.scan_markets()
                
                if opportunities:
                    print(f"   ✅ Found {len(opportunities)} high-confidence plays")
                    
                    # Execute top opportunity
                    top = opportunities[0]
                    if top['confidence'] >= 0.7:
                        self.execute_trade(top)
                else:
                    print(f"   ⏳ No opportunities (scanning...)")
                
                # Reset daily counter at midnight UTC
                if now.hour == 0 and now.minute < 1:
                    print(f"\n🔄 NEW DAY - Resetting counters")
                    self.daily_trades = 0
                    self.positions_entered = []
                
                # Sleep until next scan
                time.sleep(self.scan_interval)
                
        except KeyboardInterrupt:
            print(f"\n\n⏹️  Daemon stopped by user")
            print(f"Total cycles: {cycle}")
            print(f"Trades today: {self.daily_trades}")
            print(f"Positions tracked: {len(self.positions_entered)}\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Kalshi Smart Money Daemon')
    parser.add_argument('--auto-execute', action='store_true', help='Enable auto-execution (Level 5+)')
    parser.add_argument('--stake', type=int, default=15, help='Max stake per bet ($)')
    parser.add_argument('--max-trades', type=int, default=10, help='Max daily trades')
    
    args = parser.parse_args()
    
    daemon = SmartMoneyDaemon(
        auto_execute=args.auto_execute,
        max_stake_per_bet=args.stake,
        max_daily_trades=args.max_trades
    )
    
    daemon.run()
