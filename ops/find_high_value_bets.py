"""
Find high-value betting opportunities
Analyzes markets for mispricing, arbitrage, and high-return potential
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.client import KalshiClient
from core.analyzer import MarketAnalyzer
import json
from datetime import datetime


def load_latest_markets():
    """Load most recent market data"""
    try:
        with open("data/markets_latest.json", "r") as f:
            data = json.load(f)
            return data.get("markets", [])
    except FileNotFoundError:
        print("❌ No market data found. Run: python3 ops/collect_markets.py")
        return []


def find_opportunities(target_return: float = 5.0):
    """
    Find betting opportunities
    
    Args:
        target_return: Desired return multiplier (e.g., 5.0 for 5x)
    """
    print(f"🔍 Searching for {target_return}x opportunities...")
    
    markets = load_latest_markets()
    if not markets:
        print("📊 Fetching fresh market data...")
        client = KalshiClient()
        markets = client.get_markets(status="open", limit=200)
    
    analyzer = MarketAnalyzer()
    
    # Find high-return bets (long shots with value)
    print(f"\n💰 High-Return Bets ({target_return}x+):")
    high_return = analyzer.find_high_return_bets(markets, target_return=target_return)
    
    if high_return:
        print(f"Found {len(high_return)} opportunities\n")
        
        for i, bet in enumerate(high_return[:10], 1):
            print(f"{i}. {bet['ticker']}")
            print(f"   {bet['title']}")
            print(f"   Price: {bet['price']*100:.1f}¢ → Potential: {bet['payout_multiplier']:.1f}x")
            print(f"   Category: {bet['category']}")
            print(f"   Volume: ${bet['volume']:,.0f}")
            print()
    else:
        print("No opportunities found matching criteria")
    
    # Find arbitrage opportunities
    print("\n🔄 Arbitrage Opportunities:")
    arbitrage = analyzer.find_arbitrage(markets)
    
    if arbitrage:
        for arb in arbitrage:
            print(f"Event: {arb['event']}")
            print(f"  Markets: {', '.join(arb['markets'])}")
            print(f"  Total prob: {arb['total_prob']*100:.1f}% (should be 100%)")
            print(f"  Guaranteed profit: {arb['guaranteed_profit']*100:.1f}%")
            print()
    else:
        print("No arbitrage found\n")
    
    # Analyze by category for patterns
    print("📊 Category Analysis:")
    by_category = {}
    for market in markets:
        cat = market.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = {"count": 0, "total_volume": 0, "avg_price": []}
        
        by_category[cat]["count"] += 1
        by_category[cat]["total_volume"] += market.get("volume", 0)
        if market.get("last_price"):
            by_category[cat]["avg_price"].append(market["last_price"])
    
    for cat, stats in sorted(by_category.items(), key=lambda x: x[1]["total_volume"], reverse=True)[:5]:
        avg_price = sum(stats["avg_price"]) / len(stats["avg_price"]) if stats["avg_price"] else 0
        print(f"  {cat}: {stats['count']} markets, ${stats['total_volume']:,.0f} volume, {avg_price*100:.1f}¢ avg")
    
    # Save opportunities
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    with open(f"data/opportunities_{timestamp}.json", "w") as f:
        json.dump({
            "timestamp": timestamp,
            "target_return": target_return,
            "high_return_bets": high_return[:20],
            "arbitrage": arbitrage,
        }, f, indent=2)
    
    print(f"\n💾 Saved to data/opportunities_{timestamp}.json")
    
    return high_return


def get_top_recommendation(target_return: float = 5.0):
    """
    Get the single best recommendation
    
    Criteria:
    - High return potential
    - Reasonable liquidity
    - Category with historical edge
    """
    markets = load_latest_markets()
    if not markets:
        client = KalshiClient()
        markets = client.get_markets(status="open", limit=200)
    
    analyzer = MarketAnalyzer()
    high_return = analyzer.find_high_return_bets(markets, target_return=target_return)
    
    if not high_return:
        return None
    
    # Filter for minimum liquidity
    liquid_bets = [b for b in high_return if b["volume"] >= 100]
    
    if not liquid_bets:
        return high_return[0]
    
    # Prefer certain categories (based on historical edge)
    priority_categories = ["economics", "politics", "finance", "weather"]
    
    for cat in priority_categories:
        for bet in liquid_bets:
            if bet["category"].lower() == cat:
                return bet
    
    # Default to highest return
    return liquid_bets[0]


if __name__ == "__main__":
    import sys
    
    target = 5.0
    if len(sys.argv) > 1:
        target = float(sys.argv[1])
    
    find_opportunities(target_return=target)
    
    print("\n" + "="*60)
    print("🎯 TOP RECOMMENDATION")
    print("="*60)
    
    top = get_top_recommendation(target_return=target)
    if top:
        print(f"\nTicker: {top['ticker']}")
        print(f"Market: {top['title']}")
        print(f"Price: {top['price']*100:.1f}¢ (${top['price']:.2f} per contract)")
        print(f"Potential Return: {top['payout_multiplier']:.1f}x")
        print(f"Category: {top['category']}")
        print(f"\n💡 Strategy: Invest $20 → Max payout ${20 * top['payout_multiplier']:.0f}")
        print(f"   Risk: High (long-shot bet)")
        print(f"   Reward: {(top['payout_multiplier'] - 1) * 100:.0f}% return")
    else:
        print("\nNo recommendations found. Market conditions may not favor high returns.")
