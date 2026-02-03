#!/usr/bin/env python3
"""
Update Kalshi watchlist with current opportunities
"""
import os
import sys
from datetime import datetime
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.client import KalshiClient

def update_watchlist():
    """Scan markets and update watchlist with opportunities"""
    client = KalshiClient(env='prod')
    
    watchlist_file = Path(__file__).parent.parent / "WATCHLIST.md"
    
    # Scan for ECONOMICS & SPORTS opportunities
    markets = client.get_markets(status='open', limit=200)
    
    # Filter for economics & sports by keywords in title/ticker
    econ_keywords = ['fed', 'inflation', 'cpi', 'gdp', 'unemployment', 'rate', 'jobs', 'economy', 'recession', 'treasury', 'bond']
    sports_keywords = ['nba', 'nhl', 'nfl', 'mlb', 'points', 'rebounds', 'assists', 'goals', 'touchdowns', 'wins', 'score']
    
    target_markets = []
    for m in markets:
        title = m.get('title', '').lower()
        ticker = m.get('ticker', '').lower()
        if any(kw in title or kw in ticker for kw in econ_keywords + sports_keywords):
            target_markets.append(m)
    
    active_watch = []
    monitoring = []
    research = []
    
    for market in target_markets:
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        yes_bid = market.get('yes_bid', 0)
        no_bid = market.get('no_bid', 0)
        volume = market.get('volume', 0)
        
        # Skip low volume
        if volume < 500:
            continue
        
        # Calculate edge
        confidence = 0
        reason = ""
        category = "research"
        
        # Underpriced YES
        if yes_bid > 15 and yes_bid < 35:
            potential = 100 / yes_bid
            confidence = (35 - yes_bid) / 35
            reason = f"Underpriced @ {yes_bid}¢ → {potential:.1f}x potential"
            
            if confidence > 0.7:
                category = "active"
            elif confidence > 0.5:
                category = "monitoring"
        
        # Overpriced YES (cheap NO)
        elif yes_bid > 65 and yes_bid < 85:
            potential = 100 / no_bid
            confidence = (yes_bid - 65) / 35
            reason = f"NO underpriced @ {no_bid}¢ → {potential:.1f}x potential"
            
            if confidence > 0.7:
                category = "active"
            elif confidence > 0.5:
                category = "monitoring"
        
        # Volume spike indicator
        if volume > 10000:
            confidence *= 1.2
            reason += f" + HIGH VOLUME (${volume/100:.0f})"
        
        if category == "active" and confidence > 0:
            active_watch.append({
                'ticker': ticker,
                'title': title,
                'yes_price': yes_bid,
                'no_price': no_bid,
                'volume': volume,
                'confidence': min(confidence, 0.95),
                'reason': reason,
                'potential': 100 / (yes_bid if yes_bid < 50 else no_bid)
            })
        elif category == "monitoring" and confidence > 0:
            monitoring.append({
                'ticker': ticker,
                'title': title,
                'yes_price': yes_bid,
                'confidence': confidence,
                'reason': reason
            })
    
    # Sort by confidence
    active_watch.sort(key=lambda x: x['confidence'], reverse=True)
    monitoring.sort(key=lambda x: x['confidence'], reverse=True)
    
    # Build watchlist content
    content = f"""# 👀 KALSHI WATCHLIST - High-Confidence Opportunities

**Last Updated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
**Markets Scanned**: 200
**Opportunities Found**: {len(active_watch)} active, {len(monitoring)} monitoring

---

## 🎯 ACTIVE WATCH (Ready to Execute)

"""
    
    if active_watch:
        for i, opp in enumerate(active_watch[:5], 1):
            vol_usd = opp['volume'] / 100
            content += f"""
### {i}. {opp['title'][:60]}
- **Ticker**: `{opp['ticker']}`
- **Action**: BUY {"YES" if opp['yes_price'] < 50 else "NO"}
- **Price**: {"YES" if opp['yes_price'] < 50 else "NO"} @ {opp['yes_price'] if opp['yes_price'] < 50 else opp['no_price']}¢
- **Potential**: {opp['potential']:.1f}x return
- **Volume**: ${vol_usd:.0f}
- **Confidence**: {opp['confidence']*100:.0f}%
- **Why**: {opp['reason']}
- **Recommended Stake**: $15-20

"""
    else:
        content += "*No high-confidence plays found right now. Market conditions not favorable.*\n\n"
    
    content += """---

## 📊 MONITORING (Tracking for Entry)

"""
    
    if monitoring:
        for i, opp in enumerate(monitoring[:5], 1):
            content += f"""
{i}. **{opp['title'][:60]}**
   - Ticker: `{opp['ticker']}`
   - YES @ {opp['yes_price']}¢ | Confidence: {opp['confidence']*100:.0f}%
   - Why watching: {opp['reason']}

"""
    else:
        content += "*No markets currently being monitored.*\n\n"
    
    content += """---

## 🔍 RESEARCH (Under Analysis)

*Markets with interesting patterns but need more data before signaling.*

---

## ⚠️ HOW TO USE THIS WATCHLIST

1. **Active Watch** = High conviction (70%+), ready to execute
   - These are plays I'd take if I could auto-execute
   - Review and place manually if you agree

2. **Monitoring** = Good setups, waiting for better entry
   - Price needs to move slightly
   - Or volume needs to confirm

3. **Check this file frequently** - Updates every time daemon scans (30s)

4. **Cross-reference** with your own analysis before betting

---

**Next scan**: In 30 seconds (continuous monitoring active)
"""
    
    # Write to file
    watchlist_file.write_text(content)
    
    print(f"✅ Watchlist updated")
    print(f"   Active opportunities: {len(active_watch)}")
    print(f"   Monitoring: {len(monitoring)}")
    
    return active_watch, monitoring


if __name__ == "__main__":
    update_watchlist()
