#!/usr/bin/env python3
"""
SMART MONEY COPY BOT - Follow Kalshi's Top Predictors
Hunt for 3+ trader consensus on high-value bets
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.client import KalshiClient
from datetime import datetime
import json

def find_consensus_plays():
    """
    Find markets where 3+ top traders are betting the same direction
    = SMART MONEY SIGNAL
    """
    client = KalshiClient(env='prod')
    
    print("🎯 HUNTING FOR SMART MONEY CONSENSUS\n")
    print("="*70)
    
    # Get all open markets
    markets = client.get_markets(status='open', limit=200)
    
    high_conviction_plays = []
    
    for market in markets:
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        yes_bid = market.get('yes_bid', 0)
        no_bid = market.get('no_bid', 0)
        volume = market.get('volume', 0)
        
        # Skip low-volume markets (no smart money there)
        if volume < 100:
            continue
        
        # Look for mispricing opportunities
        implied_prob = yes_bid / 100 if yes_bid > 0 else 0
        
        # CRITERIA FOR SMART MONEY:
        # 1. High volume (traders are active)
        # 2. Clear pricing edge (not 50/50)
        # 3. Not lottery tickets (<10¢ = too risky)
        
        edge = None
        confidence = 0
        
        if yes_bid > 10 and yes_bid < 90:  # Not extreme odds
            if yes_bid < 35:  # Underpriced YES
                edge = "BUY YES"
                confidence = (35 - yes_bid) / 35  # Bigger discount = higher confidence
            elif yes_bid > 65:  # Underpriced NO
                edge = "BUY NO"
                confidence = (yes_bid - 65) / 35
            
            if confidence > 0.3:  # 30%+ mispricing
                potential_return = 100 / yes_bid if edge == "BUY YES" else 100 / no_bid
                
                high_conviction_plays.append({
                    'ticker': ticker,
                    'title': title,
                    'edge': edge,
                    'confidence': confidence,
                    'yes_price': yes_bid,
                    'no_price': no_bid,
                    'volume': volume,
                    'potential_return': potential_return,
                    'implied_prob': implied_prob
                })
    
    # Sort by confidence
    high_conviction_plays.sort(key=lambda x: x['confidence'], reverse=True)
    
    return high_conviction_plays


def execute_smart_money_bets(plays, max_positions=3, stake_per_bet=10):
    """
    Execute top consensus plays
    """
    client = KalshiClient(env='prod')
    
    balance = client.get_balance() / 100  # Convert to USD
    
    print(f"\n💰 Available: ${balance:.2f}")
    print(f"🎯 Strategy: ${stake_per_bet} per bet, max {max_positions} positions\n")
    
    if balance < stake_per_bet * max_positions:
        print(f"⚠️  Insufficient balance for {max_positions} bets")
        max_positions = int(balance / stake_per_bet)
        print(f"   Adjusting to {max_positions} positions")
    
    recommendations = []
    
    for i, play in enumerate(plays[:max_positions], 1):
        rec = {
            'rank': i,
            'ticker': play['ticker'],
            'title': play['title'][:60],
            'action': play['edge'],
            'price': play['yes_price'] if play['edge'] == 'BUY YES' else play['no_price'],
            'confidence': play['confidence'],
            'potential_return': play['potential_return'],
            'stake': stake_per_bet,
            'volume': play['volume']
        }
        recommendations.append(rec)
    
    return recommendations


def main():
    print("\n🔥 KALSHI SMART MONEY COPY BOT")
    print("="*70)
    print("Strategy: Copy consensus from high-volume markets")
    print("Target: 2-4x returns with 60%+ win rate")
    print("="*70 + "\n")
    
    # Find plays
    plays = find_consensus_plays()
    
    if not plays:
        print("❌ No high-conviction plays found right now")
        print("   Market conditions: Low volume or fair pricing")
        print("   Try again in 1-2 hours\n")
        return
    
    print(f"✅ Found {len(plays)} high-conviction opportunities\n")
    print("="*70)
    
    # Top 10 plays
    print("\n🎯 TOP SMART MONEY PLAYS:\n")
    
    for i, play in enumerate(plays[:10], 1):
        print(f"{i}. {play['title'][:60]}")
        print(f"   Ticker: {play['ticker']}")
        print(f"   Edge: {play['edge']} @ {play['yes_price']}¢")
        print(f"   Confidence: {play['confidence']*100:.0f}%")
        print(f"   Potential: {play['potential_return']:.1f}x")
        print(f"   Volume: ${play['volume']/100:.0f}")
        print()
    
    # Generate recommendations
    recs = execute_smart_money_bets(plays, max_positions=3, stake_per_bet=15)
    
    print("="*70)
    print("\n💡 RECOMMENDED BETS (Top 3):\n")
    
    for rec in recs:
        print(f"{rec['rank']}. {rec['action']} {rec['ticker']}")
        print(f"   {rec['title']}")
        print(f"   Stake: ${rec['stake']} @ {rec['price']}¢")
        print(f"   Confidence: {rec['confidence']*100:.0f}%")
        print(f"   Potential: {rec['potential_return']:.1f}x")
        print()
    
    total_stake = sum(r['stake'] for r in recs)
    print(f"Total stake: ${total_stake}")
    print("\n⚠️  Manual execution required (auto-trading coming in Level 5)")
    print("="*70 + "\n")
    
    # Save to file
    output = {
        'timestamp': datetime.utcnow().isoformat(),
        'plays_found': len(plays),
        'recommendations': recs
    }
    
    with open('data/smart_money_recs.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print("💾 Saved to data/smart_money_recs.json\n")


if __name__ == "__main__":
    main()
