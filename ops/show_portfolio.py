#!/usr/bin/env python3
"""
Display current Kalshi portfolio and positions
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client import KalshiClient

def show_portfolio():
    client = KalshiClient(env='prod')
    
    print("\n" + "="*70)
    print("💼 YOUR KALSHI PORTFOLIO")
    print("="*70 + "\n")
    
    # Balance
    balance = client.get_balance()
    print(f"💰 Available Balance: ${balance / 100:.2f}\n")
    
    # Get positions
    positions = client.get_portfolio()
    
    if positions:
        print(f"📈 ACTIVE POSITIONS ({len(positions)}):\n")
        print("-"*70)
        
        total_invested = 0
        for i, pos in enumerate(positions, 1):
            ticker = pos['ticker']
            position_count = pos['position']
            cost = pos['total_cost']
            total_invested += cost
            
            print(f"\n{i}. {ticker}")
            print(f"   Position: {position_count} YES contracts")
            print(f"   Total Cost: ${cost / 100:.2f}")
            
            # Try to get current market price
            try:
                markets = client.get_markets(limit=200)
                for market in markets:
                    if market.get('ticker') == ticker:
                        yes_price = market.get('yes_bid', 0)
                        current_value = position_count * yes_price
                        pnl = current_value - cost
                        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
                        
                        print(f"   Current Price: {yes_price}¢")
                        print(f"   Current Value: ${current_value / 100:.2f}")
                        print(f"   P&L: ${pnl / 100:+.2f} ({pnl_pct:+.1f}%)")
                        break
            except:
                pass
        
        print("\n" + "-"*70)
        print(f"\nTotal Invested: ${total_invested / 100:.2f}")
        print(f"Available Cash: ${balance / 100:.2f}")
        print(f"Total Portfolio: ${(balance + total_invested) / 100:.2f}")
    
    else:
        print("📊 No active positions")
    
    # Recent activity
    print("\n" + "="*70)
    print("📋 RECENT TRADES (last 10):\n")
    
    fills = client.get_fills(limit=10)
    
    if fills:
        for i, fill in enumerate(fills, 1):
            side_emoji = "📗" if fill['side'] == 'yes' else "📕"
            ticker = fill['ticker']
            side = fill['side'].upper()
            count = fill['count']
            price = fill['yes_price']
            time = fill['created_time'][:19] if fill.get('created_time') else 'N/A'
            
            print(f"{i}. {side_emoji} {ticker}")
            print(f"   {side} | {count} contracts @ {price}¢ | {time}")
            print()
    else:
        print("  No recent trades\n")
    
    print("="*70 + "\n")


if __name__ == "__main__":
    show_portfolio()
