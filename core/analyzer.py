"""
Market Analysis & Opportunity Detection
Finds mispriced odds, arbitrage opportunities, and high-value bets
"""
from typing import Dict, List, Tuple
import math


class MarketAnalyzer:
    """Analyze Kalshi markets for betting opportunities"""
    
    def __init__(self):
        self.min_edge = 0.15  # Minimum 15% edge required
        self.min_liquidity = 1000  # Minimum $1000 open interest
        self.max_spread = 0.10  # Max 10% bid-ask spread
    
    def calculate_implied_probability(self, price: float) -> float:
        """
        Convert market price to implied probability
        Kalshi prices are already in percentage (e.g., 0.45 = 45%)
        """
        return price
    
    def calculate_edge(self, market_prob: float, true_prob: float) -> float:
        """
        Calculate betting edge
        Edge = (true_prob - market_prob) / market_prob
        
        Example:
            Market: 20% | True: 40% → Edge = 100% (double your expected value)
        """
        if market_prob <= 0:
            return 0
        return (true_prob - market_prob) / market_prob
    
    def calculate_kelly_bet_size(self, edge: float, prob: float, bankroll: float) -> float:
        """
        Kelly Criterion for optimal bet sizing
        f* = (p * (b + 1) - 1) / b
        
        Where:
            p = probability of winning
            b = odds received (payout / stake)
        """
        if prob <= 0 or edge <= 0:
            return 0
        
        # For prediction markets: b = (1/price - 1)
        # Simplified: f* = edge
        kelly_fraction = edge
        
        # Use fractional Kelly (25%) for risk management
        return min(kelly_fraction * 0.25 * bankroll, bankroll * 0.10)
    
    def find_mispriced_markets(self, markets: List[Dict], true_probs: Dict[str, float] = None) -> List[Dict]:
        """
        Find markets where price != true probability
        
        Args:
            markets: List of market data
            true_probs: Dict mapping ticker → estimated true probability
        
        Returns:
            List of opportunities sorted by edge
        """
        opportunities = []
        
        for market in markets:
            ticker = market.get("ticker")
            last_price = market.get("last_price")
            yes_ask = market.get("yes_ask")
            volume = market.get("volume", 0)
            open_interest = market.get("open_interest", 0)
            
            # Skip if no price data
            if not last_price and not yes_ask:
                continue
            
            # Use ask price (what you pay) for analysis
            price = yes_ask if yes_ask else last_price
            
            # Skip if liquidity too low
            if open_interest < self.min_liquidity:
                continue
            
            # Calculate spread
            yes_bid = market.get("yes_bid", price)
            spread = (yes_ask - yes_bid) if yes_ask and yes_bid else 0
            if spread > self.max_spread:
                continue
            
            # If we have a true probability estimate, calculate edge
            if true_probs and ticker in true_probs:
                true_prob = true_probs[ticker]
                market_prob = price
                edge = self.calculate_edge(market_prob, true_prob)
                
                if edge >= self.min_edge:
                    expected_return = (true_prob / market_prob) - 1
                    opportunities.append({
                        "ticker": ticker,
                        "title": market.get("title"),
                        "market_price": market_prob,
                        "true_prob": true_prob,
                        "edge": edge,
                        "expected_return": expected_return,
                        "volume": volume,
                        "open_interest": open_interest,
                        "spread": spread,
                    })
        
        # Sort by edge (highest first)
        opportunities.sort(key=lambda x: x["edge"], reverse=True)
        return opportunities
    
    def find_arbitrage(self, markets: List[Dict]) -> List[Dict]:
        """
        Find arbitrage opportunities across related markets
        
        Example:
            Market A: "Candidate X wins" = 60%
            Market B: "Candidate X loses" = 50%
            → Arbitrage: Yes on A (60%) + Yes on B (50%) = 110% > 100%
        """
        # Group markets by event
        events = {}
        for market in markets:
            event_ticker = market.get("event_ticker")
            if event_ticker not in events:
                events[event_ticker] = []
            events[event_ticker].append(market)
        
        arbitrage_opps = []
        
        # Check for complementary markets (should sum to 100%)
        for event_ticker, event_markets in events.items():
            if len(event_markets) < 2:
                continue
            
            # Calculate total implied probability
            total_prob = sum(m.get("last_price", 0) for m in event_markets if m.get("last_price"))
            
            if total_prob > 0:
                # If sum < 100%, there's a guaranteed profit opportunity
                if total_prob < 0.95:
                    arbitrage_opps.append({
                        "event": event_ticker,
                        "markets": [m.get("ticker") for m in event_markets],
                        "total_prob": total_prob,
                        "guaranteed_profit": 1 - total_prob,
                    })
        
        return arbitrage_opps
    
    def find_high_return_bets(self, markets: List[Dict], target_return: float = 4.0) -> List[Dict]:
        """
        Find bets with potential for high returns (e.g., 5x)
        
        For $20 → $100, need 5x return
        This means finding markets priced at 20% or less that have >50% true probability
        """
        high_return_bets = []
        
        for market in markets:
            last_price = market.get("last_price")
            yes_ask = market.get("yes_ask")
            
            if not last_price and not yes_ask:
                continue
            
            price = yes_ask if yes_ask else last_price
            
            # Max price for desired return: 1 / target_return
            max_price = 1.0 / target_return
            
            if price <= max_price:
                potential_return = (1.0 / price) - 1
                high_return_bets.append({
                    "ticker": market.get("ticker"),
                    "title": market.get("title"),
                    "price": price,
                    "potential_return": potential_return,
                    "payout_multiplier": 1.0 / price,
                    "category": market.get("category"),
                    "volume": market.get("volume", 0),
                })
        
        # Sort by potential return
        high_return_bets.sort(key=lambda x: x["potential_return"], reverse=True)
        return high_return_bets
    
    def estimate_true_probability(self, market: Dict, signals: Dict = None) -> float:
        """
        Estimate true probability using various signals
        
        Signals can include:
        - Historical data
        - Polling data
        - Expert forecasts
        - Statistical models
        - Market sentiment
        
        This is a placeholder - you'll want to build sophisticated models
        """
        # For now, return None (manual analysis required)
        # In production, integrate:
        # - News sentiment analysis
        # - Historical event data
        # - Statistical models (e.g., FiveThirtyEight for elections)
        # - Expert consensus (Metaculus, Good Judgment)
        
        return None
