"""
Kalshi API Client
Handles authentication, market data fetching, and order execution
"""
import os
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
import json


class KalshiClient:
    """Wrapper for Kalshi API with error handling and caching"""
    
    def __init__(self, api_key_id: str = None, private_key_path: str = None, env: str = "demo"):
        """
        Initialize Kalshi client
        
        Args:
            api_key_id: API key ID from Kalshi dashboard
            private_key_path: Path to private key .pem file
            env: "demo" for sandbox, "prod" for live trading
        """
        self.api_key_id = api_key_id or os.getenv("KALSHI_API_KEY_ID")
        self.private_key_path = private_key_path or os.getenv("KALSHI_PRIVATE_KEY_PATH")
        self.env = env or os.getenv("KALSHI_ENV", "demo")
        self.base_url = (
            "https://demo-api.kalshi.co/trade-api/v2"
            if self.env == "demo"
            else "https://api.elections.kalshi.com/trade-api/v2"
        )
        
        if not self.api_key_id or not self.private_key_path:
            print("⚠️  No credentials found. Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
            print("   Running in READ-ONLY mode with public data")
            self.client = None
            self.authenticated = False
        else:
            self._init_client()
    
    def _init_client(self):
        """Initialize the Kalshi SDK client"""
        try:
            from kalshi_python_sync import Configuration, KalshiClient as SDK
            
            # Read private key
            with open(self.private_key_path, "r") as f:
                private_key = f.read()
            
            # Configure client (updated API endpoint as of 2026)
            config = Configuration(host=self.base_url)
            config.api_key_id = self.api_key_id
            config.private_key_pem = private_key
            
            self.client = SDK(config)
            self.authenticated = True
            print(f"✅ Kalshi client initialized ({self.env} mode)")
            
            # Test connection
            balance = self.get_balance()
            print(f"💰 Balance: ${balance / 100:.2f}")
            
        except ImportError:
            print("❌ kalshi_python_sync not installed. Run: pip install kalshi_python_sync")
            self.client = None
            self.authenticated = False
        except Exception as e:
            print(f"❌ Failed to initialize Kalshi client: {e}")
            self.client = None
            self.authenticated = False
    
    def get_balance(self) -> int:
        """Get account balance in cents"""
        if not self.authenticated:
            return 0
        try:
            balance_resp = self.client.get_balance()
            return balance_resp.balance
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0
    
    def get_portfolio(self) -> List[Dict]:
        """Get current portfolio/positions"""
        if not self.authenticated:
            return []
        try:
            portfolio_resp = self.client.get_portfolio()
            positions = []
            
            if hasattr(portfolio_resp, 'market_positions') and portfolio_resp.market_positions:
                for pos in portfolio_resp.market_positions:
                    positions.append({
                        'ticker': pos.ticker,
                        'position': pos.position,
                        'total_cost': pos.total_cost,
                        'resting_orders_count': getattr(pos, 'resting_orders_count', 0)
                    })
            
            return positions
        except Exception as e:
            print(f"Error fetching portfolio: {e}")
            return []
    
    def get_fills(self, limit: int = 50) -> List[Dict]:
        """Get recent order fills (trade history)"""
        if not self.authenticated:
            return []
        try:
            fills_resp = self.client.get_fills(limit=limit)
            fills = []
            
            if hasattr(fills_resp, 'fills') and fills_resp.fills:
                for fill in fills_resp.fills:
                    fills.append({
                        'ticker': fill.ticker,
                        'side': fill.side,
                        'count': fill.count,
                        'yes_price': fill.yes_price,
                        'created_time': fill.created_time,
                        'order_id': fill.order_id
                    })
            
            return fills
        except Exception as e:
            print(f"Error fetching fills: {e}")
            return []
    
    def get_markets(self, status: str = "open", limit: int = 100, event_ticker: str = None) -> List[Dict]:
        """
        Fetch markets from Kalshi
        
        Args:
            status: "open", "closed", or "all"
            limit: Max markets to return
            event_ticker: Filter by event (e.g., "FRSEP23")
        
        Returns:
            List of market dictionaries
        """
        # ALWAYS use public API to avoid Pydantic validation errors
        # The authenticated SDK has validation issues with None values
        return self._get_public_markets_v2(status, limit, event_ticker)

    def _public_get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Optional[Dict[str, Any]]:
        import requests

        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, params=params or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Error fetching {path}: {e}")
            return None
        
    def _get_public_markets_v2(self, status: str = "open", limit: int = 100, event_ticker: str = None) -> List[Dict]:
        """
        Fetch market data via direct API calls (bypasses SDK validation issues)
        """
        import requests
        try:
            url = f"{self.base_url}/markets"
            params = {"status": status, "limit": limit}
            if event_ticker:
                params["event_ticker"] = event_ticker
            
            # Use auth if available
            headers = {}
            if self.authenticated and hasattr(self.client, '_api_client'):
                # Get auth token from SDK client if possible
                pass  # For now, use public endpoint
            
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            markets = []
            for m in data.get("markets", []):
                # Convert cents to dollars and handle None values safely
                yes_bid = m.get("yes_bid")
                yes_ask = m.get("yes_ask")
                no_bid = m.get("no_bid")
                no_ask = m.get("no_ask")
                last_price = m.get("last_price")
                volume = m.get("volume", 0)
                
                markets.append({
                    "ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "event_ticker": m.get("event_ticker", ""),
                    "category": m.get("category", "Other"),  # Default to avoid None
                    "status": m.get("status", "open"),
                    "yes_bid": yes_bid if yes_bid is not None else 0,
                    "yes_ask": yes_ask if yes_ask is not None else 100,
                    "no_bid": no_bid if no_bid is not None else 0,
                    "no_ask": no_ask if no_ask is not None else 100,
                    "last_price": last_price if last_price is not None else 0,
                    "volume": volume,
                    "open_interest": m.get("open_interest", 0),
                    "close_date": m.get("close_time"),
                    "expiration": m.get("expiration_time"),
                })
            
            return markets
        except Exception as e:
            print(f"Error fetching markets via API: {e}")
            return []
    
    def _get_public_markets(self) -> List[Dict]:
        """Fetch public market data without authentication (limited data)"""
        import requests
        try:
            url = "https://api.elections.kalshi.com/trade-api/v2/markets"
            resp = requests.get(url, params={"status": "open", "limit": 100}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            markets = []
            for m in data.get("markets", []):
                markets.append({
                    "ticker": m.get("ticker"),
                    "title": m.get("title"),
                    "event_ticker": m.get("event_ticker"),
                    "category": m.get("category"),
                    "status": m.get("status"),
                    "yes_bid": m.get("yes_bid", 0) / 100,
                    "yes_ask": m.get("yes_ask", 0) / 100,
                    "last_price": m.get("last_price", 0) / 100,
                    "volume": m.get("volume", 0),
                    "open_interest": m.get("open_interest", 0),
                })
            return markets
        except Exception as e:
            print(f"Error fetching public markets: {e}")
            return []
    
    def get_events(self, limit: int = 50) -> List[Dict]:
        """Fetch events (groups of related markets)"""
        if not self.authenticated:
            return []
        
        try:
            events_resp = self.client.get_events(limit=limit)
            events = []
            for event in events_resp.events:
                events.append({
                    "ticker": event.event_ticker,
                    "title": event.title,
                    "category": event.category,
                    "series_ticker": event.series_ticker,
                    "markets_count": event.markets_count,
                })
            return events
        except Exception as e:
            print(f"Error fetching events: {e}")
            return []
    
    def get_orderbook(self, ticker: str) -> Optional[Dict]:
        """Get order book depth for a market"""
        if not self.authenticated:
            return self.get_public_orderbook(ticker)
        
        try:
            book_resp = self.client.get_orderbook(ticker=ticker)
            return {
                "yes_bids": [(b.price / 100, b.quantity) for b in book_resp.yes],
                "no_bids": [(b.price / 100, b.quantity) for b in book_resp.no],
            }
        except Exception as e:
            print(f"Error fetching orderbook for {ticker}: {e}")
            return self.get_public_orderbook(ticker)

    def get_public_orderbook(self, ticker: str) -> Optional[Dict[str, List[Dict[str, float]]]]:
        """
        Get market orderbook from public endpoint.
        """
        request_patterns = [
            (f"/markets/{ticker}/orderbook", None),
            ("/markets/orderbook", {"ticker": ticker}),
        ]
        for path, params in request_patterns:
            payload = self._public_get(path, params=params, timeout=10)
            if not payload:
                continue

            # Expected shape can vary; normalize both dict/list levels.
            book = payload.get("orderbook", payload)
            yes_raw = book.get("yes", book.get("yes_bids", [])) if isinstance(book, dict) else []
            no_raw = book.get("no", book.get("no_bids", [])) if isinstance(book, dict) else []

            yes_bids: List[Dict[str, float]] = []
            no_bids: List[Dict[str, float]] = []

            for level in yes_raw or []:
                if isinstance(level, dict):
                    price = level.get("price")
                    qty = level.get("quantity", level.get("count", 0))
                elif isinstance(level, (list, tuple)) and len(level) >= 2:
                    price, qty = level[0], level[1]
                else:
                    continue
                try:
                    price_val = float(price)
                    qty_val = float(qty)
                except (TypeError, ValueError):
                    continue
                yes_bids.append({"price": price_val, "quantity": qty_val})

            for level in no_raw or []:
                if isinstance(level, dict):
                    price = level.get("price")
                    qty = level.get("quantity", level.get("count", 0))
                elif isinstance(level, (list, tuple)) and len(level) >= 2:
                    price, qty = level[0], level[1]
                else:
                    continue
                try:
                    price_val = float(price)
                    qty_val = float(qty)
                except (TypeError, ValueError):
                    continue
                no_bids.append({"price": price_val, "quantity": qty_val})

            return {"yes_bids": yes_bids, "no_bids": no_bids}
        return None

    def get_market_trades(self, ticker: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Get recent public trades for a market.
        """
        payload = self._public_get("/markets/trades", params={"ticker": ticker, "limit": limit}, timeout=10)
        if not payload:
            return []
        trades = payload.get("trades", [])
        if not isinstance(trades, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            normalized.append(
                {
                    "ticker": trade.get("ticker", ticker),
                    "yes_price": trade.get("yes_price"),
                    "no_price": trade.get("no_price"),
                    "price": trade.get("price"),
                    "count": trade.get("count", trade.get("quantity", 0)),
                    "side": trade.get("side", trade.get("taker_side")),
                    "created_time": trade.get("created_time", trade.get("created_at")),
                }
            )
        return normalized
    
    def place_order(self, ticker: str, side: str, quantity: int, price: int, order_type: str = "limit") -> Optional[str]:
        """
        Place an order
        
        Args:
            ticker: Market ticker (e.g., "BTCUSD-25FEB03-90K")
            side: "yes" or "no"
            quantity: Number of contracts
            price: Price in cents (e.g., 45 for 45¢ / 45% probability)
            order_type: "limit" or "market"
        
        Returns:
            Order ID if successful
        """
        if not self.authenticated:
            print("⚠️  Cannot place order: not authenticated")
            return None
        
        try:
            if order_type == "limit":
                order_resp = self.client.create_order(
                    ticker=ticker,
                    side=side,
                    action="buy",
                    count=quantity,
                    type="limit",
                    yes_price=price if side == "yes" else None,
                    no_price=price if side == "no" else None,
                )
            else:
                order_resp = self.client.create_order(
                    ticker=ticker,
                    side=side,
                    action="buy",
                    count=quantity,
                    type="market",
                )
            
            print(f"✅ Order placed: {order_resp.order_id}")
            return order_resp.order_id
        except Exception as e:
            print(f"❌ Order failed: {e}")
            return None
