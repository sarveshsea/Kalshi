#!/usr/bin/env python3
"""
KALSHI AUTO-TRADER - Autonomous Execution System

CRITICAL: This will auto-execute trades based on signals
Safety limits in place to prevent runaway trading
"""
import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.client import KalshiClient

class KalshiAutoTrader:
    def __init__(
        self,
        max_position_size_usd=30,  # RUTHLESS - Even bigger
        max_daily_trades=50,  # RUTHLESS - Way more opportunities
        min_confidence=0.50,  # RUTHLESS - 50% is enough
        max_total_exposure_usd=250,  # RUTHLESS - Deploy more capital
        take_profit_pct=0.25,  # FASTER exits - 25% gain
        stop_loss_pct=0.20,  # WIDER stops - 20% loss (let winners run)
        enabled=True
    ):
        """
        Initialize auto-trader with safety limits
        
        Args:
            max_position_size_usd: Max $ per trade
            max_daily_trades: Daily trade limit
            min_confidence: Minimum confidence to auto-execute (0.70 = 70%)
            max_total_exposure_usd: Total capital at risk limit
            enabled: Master kill switch
        """
        self.client = KalshiClient(env='prod')
        self.max_position = max_position_size_usd * 100  # Convert to cents
        self.max_daily = max_daily_trades
        self.min_confidence = min_confidence
        self.max_exposure = max_total_exposure_usd * 100
        self.take_profit = take_profit_pct
        self.stop_loss = stop_loss_pct
        self.enabled = enabled
        
        # State tracking
        self.daily_trades = 0
        self.positions = []  # Open positions we're tracking
        self.closed_positions = []  # Closed positions (history)
        self.total_exposure = 0
        self.total_pnl = 0
        
        # Load existing positions
        self.load_state()
        
        print("\n" + "="*70)
        print("🤖 KALSHI AUTO-TRADER - AUTONOMOUS EXECUTION")
        print("="*70)
        print(f"Status: {'ENABLED ✅' if enabled else 'DISABLED ⚠️'}")
        print(f"Max position size: ${max_position_size_usd}")
        print(f"Max daily trades: {max_daily_trades}")
        print(f"Min confidence: {min_confidence*100:.0f}%")
        print(f"Max total exposure: ${max_total_exposure_usd}")
        print(f"Current trades today: {self.daily_trades}")
        print(f"Current exposure: ${self.total_exposure/100:.2f}")
        print("="*70 + "\n")
    
    def load_state(self):
        """Load trading state from file"""
        state_file = Path(__file__).parent.parent / "data" / "auto_trader_state.json"
        
        if state_file.exists():
            state = json.loads(state_file.read_text())
            
            # Reset daily counter if new day
            last_trade_date = state.get('last_trade_date', '')
            today = datetime.utcnow().date().isoformat()
            
            if last_trade_date != today:
                self.daily_trades = 0
            else:
                self.daily_trades = state.get('daily_trades', 0)
            
            self.positions = state.get('positions', [])
            self.total_exposure = state.get('total_exposure', 0)
    
    def save_state(self):
        """Save trading state to file"""
        state_file = Path(__file__).parent.parent / "data" / "auto_trader_state.json"
        state_file.parent.mkdir(exist_ok=True)
        
        state = {
            'last_trade_date': datetime.utcnow().date().isoformat(),
            'daily_trades': self.daily_trades,
            'positions': self.positions,
            'total_exposure': self.total_exposure,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        state_file.write_text(json.dumps(state, indent=2))
    
    def check_safety_limits(self, trade_size_cents):
        """Check if trade passes safety limits"""
        # Master kill switch
        if not self.enabled:
            return False, "Auto-trader disabled"
        
        # Daily trade limit
        if self.daily_trades >= self.max_daily:
            return False, f"Daily limit reached ({self.max_daily} trades)"
        
        # Position size limit
        if trade_size_cents > self.max_position:
            return False, f"Position too large (${trade_size_cents/100:.2f} > ${self.max_position/100})"
        
        # Total exposure limit
        if self.total_exposure + trade_size_cents > self.max_exposure:
            return False, f"Would exceed max exposure (${(self.total_exposure + trade_size_cents)/100:.2f} > ${self.max_exposure/100})"
        
        # Balance check
        balance = self.client.get_balance()
        if balance < trade_size_cents:
            return False, f"Insufficient balance (${balance/100:.2f} < ${trade_size_cents/100:.2f})"
        
        return True, "All safety checks passed"
    
    def execute_trade(self, ticker, side, count, yes_price):
        """
        Execute a trade on Kalshi
        
        Args:
            ticker: Market ticker
            side: 'yes' or 'no'
            count: Number of contracts
            yes_price: Price per contract in cents
        
        Returns:
            success, order_id or error
        """
        if not self.client.authenticated:
            return False, "Not authenticated"
        
        try:
            # Calculate trade size
            trade_size = count * yes_price
            
            # Check safety limits
            safe, reason = self.check_safety_limits(trade_size)
            if not safe:
                return False, reason
            
            # Place order via SDK
            # NOTE: Using market order for immediate execution
            order_result = self.client.client.create_order(
                ticker=ticker,
                action='buy',
                side=side,
                count=count,
                type='market',
                yes_price=yes_price
            )
            
            # Track position
            self.positions.append({
                'ticker': ticker,
                'side': side,
                'count': count,
                'price': yes_price,
                'size': trade_size,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            self.daily_trades += 1
            self.total_exposure += trade_size
            self.save_state()
            
            return True, order_result.order_id
            
        except Exception as e:
            return False, str(e)
    
    def check_exits(self):
        """
        CRITICAL: Check open positions and exit based on take-profit/stop-loss
        This is where we lock in gains and cut losses - DEGENERATE QUANT STYLE
        """
        if not self.positions:
            return
        
        print(f"💼 Checking {len(self.positions)} open position(s) for exits...\n")
        
        # Get current market prices (all markets for exits)
        markets = self.client.get_markets(status='open', limit=200)
        
        market_prices = {}
        
        for market in markets:
            ticker = market.get('ticker', '')
            market_prices[ticker] = {
                'yes_bid': market.get('yes_bid', 0),
                'no_bid': market.get('no_bid', 0),
                'yes_ask': market.get('yes_ask', 100),
                'no_ask': market.get('no_ask', 100)
            }
        
        positions_to_close = []
        
        for i, pos in enumerate(self.positions):
            ticker = pos['ticker']
            side = pos['side']
            entry_price = pos['price']
            count = pos['count']
            
            if ticker not in market_prices:
                continue
            
            # Current market price (what we'd get if we sold)
            current_price = market_prices[ticker]['yes_bid'] if side == 'yes' else market_prices[ticker]['no_bid']
            
            # Calculate P&L
            entry_value = entry_price * count
            current_value = current_price * count
            pnl = current_value - entry_value
            pnl_pct = pnl / entry_value if entry_value > 0 else 0
            
            # DEGENERATE QUANT LOGIC:
            # Take profit at 30% OR stop loss at 15%
            should_exit = False
            reason = ""
            
            if pnl_pct >= self.take_profit:
                should_exit = True
                reason = f"🎯 TAKE PROFIT ({pnl_pct*100:.1f}% gain)"
            elif pnl_pct <= -self.stop_loss:
                should_exit = True
                reason = f"🛑 STOP LOSS ({pnl_pct*100:.1f}% loss)"
            
            if should_exit:
                print(f"   [{i+1}] {ticker}")
                print(f"       Entry: {entry_price}¢ → Current: {current_price}¢")
                print(f"       P&L: ${pnl/100:+.2f} ({pnl_pct*100:+.1f}%)")
                print(f"       Action: {reason}")
                
                positions_to_close.append({
                    'index': i,
                    'position': pos,
                    'exit_price': current_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'reason': reason
                })
        
        # Execute exits
        for exit_data in positions_to_close:
            pos = exit_data['position']
            
            print(f"\n🔄 CLOSING POSITION: {pos['ticker']}")
            
            try:
                # Place sell order (opposite side)
                sell_result = self.client.client.create_order(
                    ticker=pos['ticker'],
                    action='sell',
                    side=pos['side'],
                    count=pos['count'],
                    type='market'
                )
                
                print(f"   ✅ POSITION CLOSED")
                print(f"      P&L: ${exit_data['pnl']/100:+.2f}")
                print(f"      Reason: {exit_data['reason']}")
                
                # Update tracking
                self.closed_positions.append({
                    **pos,
                    'exit_price': exit_data['exit_price'],
                    'exit_time': datetime.utcnow().isoformat(),
                    'pnl': exit_data['pnl'],
                    'pnl_pct': exit_data['pnl_pct'],
                    'reason': exit_data['reason']
                })
                
                self.total_pnl += exit_data['pnl']
                self.total_exposure -= pos['size']
                
                # Remove from open positions
                self.positions.pop(exit_data['index'])
                
            except Exception as e:
                print(f"   ❌ FAILED TO CLOSE: {e}")
        
        if positions_to_close:
            self.save_state()
            print(f"\n💰 Total P&L: ${self.total_pnl/100:+.2f}")
        else:
            print("   ✅ All positions within range (no exits)")
        
        print()
    
    def scan_and_execute(self):
        """
        DEGENERATE QUANT TRADING LOOP:
        1. Check exits first (lock gains, cut losses)
        2. Scan for new entries (aggressive but data-driven)
        3. Execute on 60%+ confidence
        """
        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] === DEGENERATE QUANT CYCLE ===\n")
        
        # STEP 1: CHECK EXITS (Take profits & stop losses)
        self.check_exits()
        
        # STEP 2: SCAN FOR NEW ENTRIES
        print(f"🔍 Scanning ECONOMICS & SPORTS markets for entry opportunities...\n")
        
        # Get markets
        markets = self.client.get_markets(status='open', limit=200)
        
        # Filter for ECONOMICS & SPORTS by keywords in title/ticker
        econ_keywords = ['fed', 'inflation', 'cpi', 'gdp', 'unemployment', 'rate', 'jobs', 'economy', 'recession', 'treasury', 'bond']
        sports_keywords = ['nba', 'nhl', 'nfl', 'mlb', 'points', 'rebounds', 'assists', 'goals', 'touchdowns', 'wins', 'score']
        
        target_markets = []
        for m in markets:
            title = m.get('title', '').lower()
            ticker = m.get('ticker', '').lower()
            # Match either economics OR sports
            if any(kw in title or kw in ticker for kw in econ_keywords + sports_keywords):
                target_markets.append(m)
        
        print(f"   Found {len(target_markets)} economics/sports markets\n")
        
        # Use filtered markets
        markets = target_markets
        
        opportunities = []
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            yes_bid = market.get('yes_bid', 0)
            no_bid = market.get('no_bid', 0)
            volume = market.get('volume', 0)
            
            # RUTHLESS MODE: Accept ANY volume
            # Target: $50 → $200 in 2-3 hours = need $150 profit
            # Strategy: High frequency, any edge, execute fast
            
            # Calculate confidence - AGGRESSIVE BUT DATA-DRIVEN
            confidence = 0
            action = None
            price = 0
            
            # RUTHLESS MODE: MUCH wider ranges, lower bars
            # LONG YES opportunities (ANY discount)
            if yes_bid > 5 and yes_bid < 50:  # VERY wide
                # Aggressive confidence calculation
                if yes_bid < 20:
                    confidence = 0.75  # High confidence on deep value
                elif yes_bid < 35:
                    confidence = 0.65  # Medium confidence
                else:
                    confidence = 0.55  # Still tradeable
                
                # ANY volume = boost
                if volume > 0:
                    confidence += 0.05
                if volume > 1000:
                    confidence += 0.10
                
                confidence = min(confidence, 0.95)
                
                if confidence >= self.min_confidence:
                    action = 'yes'
                    price = yes_bid
            
            # SHORT YES (buy NO) - ANY overpricing
            elif yes_bid > 50 and yes_bid < 95:  # VERY wide
                if yes_bid > 80:
                    confidence = 0.75  # High confidence
                elif yes_bid > 65:
                    confidence = 0.65
                else:
                    confidence = 0.55
                
                if volume > 0:
                    confidence += 0.05
                if volume > 1000:
                    confidence += 0.10
                
                confidence = min(confidence, 0.95)
                
                if confidence >= self.min_confidence:
                    action = 'no'
                    price = no_bid
            
            # RUTHLESS: Also trade 40-60¢ range (near-fair value but with volume)
            elif yes_bid >= 40 and yes_bid <= 60 and volume > 5000:
                # Volume spike in fair-value range = momentum play
                confidence = 0.60  # Base confidence from volume
                if volume > 10000:
                    confidence = 0.70
                
                # Direction: Favor slight undervalue
                if yes_bid < 50:
                    action = 'yes'
                    price = yes_bid
                else:
                    action = 'no'
                    price = no_bid
            
            if action and confidence >= self.min_confidence:
                # Calculate position size
                contracts = int(self.max_position / price)
                
                opportunities.append({
                    'ticker': ticker,
                    'title': title,
                    'action': action,
                    'price': price,
                    'contracts': contracts,
                    'confidence': confidence,
                    'volume': volume
                })
        
        # Execute top opportunity
        if opportunities:
            opportunities.sort(key=lambda x: x['confidence'], reverse=True)
            top = opportunities[0]
            
            print(f"🎯 HIGH-CONFIDENCE SIGNAL DETECTED:")
            print(f"   {top['title'][:60]}")
            print(f"   Action: BUY {top['action'].upper()}")
            print(f"   Price: {top['price']}¢")
            print(f"   Contracts: {top['contracts']}")
            print(f"   Confidence: {top['confidence']*100:.0f}%")
            print(f"   Volume: ${top['volume']/100:.0f}")
            print()
            
            # AUTO-EXECUTE
            print(f"🤖 AUTO-EXECUTING...")
            success, result = self.execute_trade(
                top['ticker'],
                top['action'],
                top['contracts'],
                top['price']
            )
            
            if success:
                print(f"✅ TRADE EXECUTED!")
                print(f"   Order ID: {result}")
                print(f"   Size: ${top['contracts'] * top['price'] / 100:.2f}")
                print(f"   Daily trades: {self.daily_trades}/{self.max_daily}")
                print(f"   Total exposure: ${self.total_exposure/100:.2f}/${self.max_exposure/100}")
            else:
                print(f"❌ TRADE FAILED: {result}")
            
            print()
        else:
            print("⏳ No opportunities meeting criteria")
        
        return len(opportunities)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Kalshi Auto-Trader')
    parser.add_argument('--max-position', type=int, default=15, help='Max $ per trade')
    parser.add_argument('--max-trades', type=int, default=10, help='Max daily trades')
    parser.add_argument('--min-confidence', type=float, default=0.70, help='Min confidence (0-1)')
    parser.add_argument('--max-exposure', type=int, default=150, help='Max total exposure $')
    parser.add_argument('--enabled', action='store_true', default=True, help='Enable auto-trading')
    parser.add_argument('--run-once', action='store_true', help='Run once and exit')
    
    args = parser.parse_args()
    
    trader = KalshiAutoTrader(
        max_position_size_usd=args.max_position,
        max_daily_trades=args.max_trades,
        min_confidence=args.min_confidence,
        max_total_exposure_usd=args.max_exposure,
        enabled=args.enabled
    )
    
    if args.run_once:
        trader.scan_and_execute()
    else:
        # Continuous mode
        print("🔄 Starting continuous auto-trading...\n")
        cycle = 0
        
        try:
            while True:
                cycle += 1
                print(f"--- Cycle #{cycle} ---")
                trader.scan_and_execute()
                print(f"Next scan in 15 seconds... (RUTHLESS MODE)\n")
                time.sleep(15)  # RUTHLESS: 4x faster scanning
                
        except KeyboardInterrupt:
            print(f"\n\n⏹️  Auto-trader stopped")
            print(f"Total cycles: {cycle}")
            print(f"Trades executed: {trader.daily_trades}")
