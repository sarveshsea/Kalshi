"""
Collect and cache Kalshi market data
Run this periodically to build a dataset for analysis
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.client import KalshiClient
import json
from datetime import datetime


def collect_markets():
    """Fetch all open markets and save to data/"""
    client = KalshiClient()
    
    print("📊 Fetching open markets...")
    markets = client.get_markets(status="open", limit=200)
    
    if not markets:
        print("❌ No markets found")
        return
    
    print(f"✅ Found {len(markets)} open markets")
    
    # Group by category
    by_category = {}
    for market in markets:
        cat = market.get("category", "unknown")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(market)
    
    print("\n📈 Markets by category:")
    for cat, mkts in sorted(by_category.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"  {cat}: {len(mkts)} markets")
    
    # Save to file
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filepath = f"data/markets_{timestamp}.json"
    
    with open(filepath, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "count": len(markets),
            "markets": markets,
        }, f, indent=2)
    
    print(f"\n💾 Saved to {filepath}")
    
    # Also save as "latest"
    with open("data/markets_latest.json", "w") as f:
        json.dump({
            "timestamp": timestamp,
            "count": len(markets),
            "markets": markets,
        }, f, indent=2)
    
    print("✅ Data collection complete")
    
    return markets


if __name__ == "__main__":
    collect_markets()
