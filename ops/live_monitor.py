"""
Live market monitor for real-time opportunity detection
Watches for price movements, news-driven spikes, and arbitrage windows
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.client import KalshiClient
from core.analyzer import MarketAnalyzer
import time
from datetime import datetime
import json


def monitor_markets(interval: int = 60, alert_threshold: float = 0.20):
    """
    Monitor markets for sudden opportunities
    
    Args:
        interval: Seconds between checks
        alert_threshold: Alert when price moves >20%
    """
    print("🔴 Live Market Monitor")
    print(f"⏱️  Refresh: every {interval}s")
    print(f"🚨 Alert threshold: {alert_threshold*100:.0f}% price change")
    print("\nPress Ctrl+C to stop\n")
    
    client = KalshiClient()
    analyzer = MarketAnalyzer()
    
    last_prices = {}
    cycle = 0
    
    try:
        while True:
            cycle += 1
            timestamp = datetime.utcnow().strftime("%H:%M:%S")
            print(f"[{timestamp}] Cycle #{cycle}")
            
            markets = client.get_markets(status="open", limit=100)
            
            if not markets:
                print("  ⚠️  No markets fetched")
                time.sleep(interval)
                continue
            
            # Check for price movements
            alerts = []
            
            for market in markets:
                ticker = market.get("ticker")
                price = market.get("last_price")
                
                if not price:
                    continue
                
                if ticker in last_prices:
                    prev_price = last_prices[ticker]
                    change = (price - prev_price) / prev_price if prev_price > 0 else 0
                    
                    if abs(change) >= alert_threshold:
                        alerts.append({
                            "ticker": ticker,
                            "title": market.get("title"),
                            "prev_price": prev_price,
                            "current_price": price,
                            "change": change,
                        })
                
                last_prices[ticker] = price
            
            # Display alerts
            if alerts:
                print(f"\n🚨 {len(alerts)} PRICE ALERTS:")
                for alert in alerts:
                    direction = "⬆️" if alert["change"] > 0 else "⬇️"
                    print(f"  {direction} {alert['ticker']}")
                    print(f"     {alert['title']}")
                    print(f"     {alert['prev_price']*100:.1f}¢ → {alert['current_price']*100:.1f}¢ ({alert['change']*100:+.1f}%)")
                print()
            
            # Find high-value opportunities
            high_value = analyzer.find_high_return_bets(markets, target_return=5.0)
            if high_value:
                print(f"  💰 {len(high_value)} high-return opportunities (5x+)")
            
            # Check for arbitrage
            arbitrage = analyzer.find_arbitrage(markets)
            if arbitrage:
                print(f"  🔄 {len(arbitrage)} arbitrage opportunities")
                for arb in arbitrage:
                    print(f"     {arb['event']}: {arb['guaranteed_profit']*100:.1f}% profit")
            
            print(f"  ✓ {len(markets)} markets checked\n")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped")
        
        # Save final state
        with open("data/monitor_state.json", "w") as f:
            json.dump({
                "last_prices": last_prices,
                "timestamp": datetime.utcnow().isoformat(),
            }, f, indent=2)
        
        print("💾 State saved to data/monitor_state.json")


if __name__ == "__main__":
    import sys
    
    interval = 60
    if len(sys.argv) > 1:
        interval = int(sys.argv[1])
    
    monitor_markets(interval=interval)
