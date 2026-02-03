# Kalshi Deployment Guide

## Quick Start (Demo Mode - No Credentials)

You can start exploring Kalshi markets immediately without credentials using public data:

```bash
cd Kalshi

# Install dependencies
pip install kalshi_python_sync pandas numpy requests

# Collect market data (public API, no auth required)
python3 ops/collect_markets.py

# Find high-value opportunities
python3 ops/find_high_value_bets.py

# Get top 5x recommendation for $20 → $100
python3 ops/find_high_value_bets.py 5.0
```

## Full Setup (Authenticated Trading)

### 1. Create Kalshi Account

1. Go to https://kalshi.com
2. Sign up (start with demo account)
3. Complete identity verification (for live trading)

### 2. Generate API Credentials

1. Log in to Kalshi
2. Go to Settings → API
3. Click "Create API Key"
4. Download the `.pem` private key file
5. Save API Key ID

### 3. Configure Environment

Create `.env` file:

```bash
KALSHI_API_KEY_ID=your-key-id-here
KALSHI_PRIVATE_KEY_PATH=/path/to/your/private_key.pem
KALSHI_ENV=demo  # or "prod" for live trading
```

### 4. Test Connection

```bash
python3 -c "from core.client import KalshiClient; c = KalshiClient(); print(f'Balance: \${c.get_balance()/100:.2f}')"
```

### 5. Run Analysis

```bash
# Collect fresh market data
python3 ops/collect_markets.py

# Find opportunities
python3 ops/find_high_value_bets.py 5.0

# Start live monitor
python3 ops/live_monitor.py 60
```

## Trading Strategy

### For $20 → $100 (5x Return)

**Strategy**: Find long-shot markets (≤20% price) with real probability ≥50%

**Categories to watch**:
1. **Economics**: CPI, unemployment, Fed decisions (data-driven)
2. **Politics**: Elections, legislative outcomes (polling edge)
3. **Finance**: Stock prices, earnings (technical analysis)
4. **Weather**: Temperature, precipitation (meteorological models)

**Risk Management**:
- Max $20 per bet (10% of $200 bankroll)
- Need 1 win in 5 bets to break even
- Target categories with 30-50% historical accuracy on long-shots

**Example Bet**:
```
Market: "Bitcoin below $90k on Feb 7"
Price: 18¢ (18% implied probability)
True Probability Estimate: 45% (based on volatility model)
Expected Value: (0.45 / 0.18) - 1 = 150% return
Bet: $20 → Max payout: $111
```

### Signals to Build

1. **Economics Data**: Track Fed calendars, use consensus forecasts
2. **Polling Aggregation**: 538, RealClearPolitics, PredictIt for politics
3. **Options Implied Vol**: Use crypto/stock options to estimate probability
4. **Weather Models**: NOAA, Weather.gov for precipitation/temp markets
5. **News Sentiment**: Monitor breaking news for rapid market moves

## Advanced Features

### Arbitrage Detection

```bash
# Find guaranteed profit opportunities
python3 ops/find_high_value_bets.py
# Check "Arbitrage Opportunities" section
```

### Live Monitoring

```bash
# Monitor markets every 30 seconds
python3 ops/live_monitor.py 30
```

### Custom Analysis

```python
from core.client import KalshiClient
from core.analyzer import MarketAnalyzer

client = KalshiClient()
analyzer = MarketAnalyzer()

# Get markets in specific category
markets = client.get_markets(status="open", limit=100)
economics = [m for m in markets if m["category"] == "economics"]

# Find high-return bets
opportunities = analyzer.find_high_return_bets(economics, target_return=5.0)

for opp in opportunities[:5]:
    print(f"{opp['ticker']}: {opp['payout_multiplier']}x potential")
```

## Paper Trading Workflow

1. **Research**: Use `find_high_value_bets.py` to identify opportunities
2. **Analyze**: Manual review of market conditions, news, data
3. **Track**: Log predictions in `data/paper_trades.json`
4. **Review**: Compare predictions to outcomes, calculate win rate
5. **Iterate**: Refine probability estimation models

## Safety

- **Start demo**: Test strategies with fake money
- **Small stakes**: Begin with $20-50 per bet
- **Track everything**: Log all bets for performance analysis
- **Review weekly**: Adjust strategy based on results
- **Know limits**: Prediction markets favor informed traders, not lucky guessers

## Next Steps

1. Build probability estimation models (data-driven)
2. Integrate news sentiment analysis
3. Automate opportunity detection
4. Create notification system for high-value bets
5. Backtest strategies on historical market data
