#!/usr/bin/env python3
"""
Kalshi auto-trader with statistically gated entries, strict risk controls,
and persistent performance tracking.

By default this runs in PAPER mode and only trades tickers that have alpha
signals in `data/alpha_signals.json`.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client import KalshiClient
from core.trading import (
    AlphaSignal,
    MarketQuote,
    compute_binary_kelly,
    compute_performance_metrics,
    load_alpha_signals,
    parse_timestamp,
    probability_to_cents,
    to_probability,
)


@dataclass(frozen=True)
class TraderConfig:
    env: str = "prod"
    enabled: bool = True
    paper_mode: bool = True
    paper_bankroll_usd: float = 250.0
    max_position_usd: float = 20.0
    min_position_usd: float = 5.0
    max_daily_trades: int = 12
    max_total_exposure_usd: float = 150.0
    min_signal_confidence: float = 0.65
    min_edge: float = 0.03
    min_net_edge: float = 0.015
    max_spread: float = 0.06
    min_volume: float = 500.0
    fee_per_contract_prob: float = 0.008
    slippage_spread_factor: float = 0.35
    kelly_fraction: float = 0.25
    take_profit_pct: float = 0.2
    stop_loss_pct: float = 0.12
    max_holding_minutes: int = 240
    scan_interval_seconds: int = 30
    markets_limit: int = 300
    state_file: str = "data/auto_trader_state.json"
    alpha_file: str = "data/alpha_signals.json"

    @property
    def max_position_cents(self) -> int:
        return int(round(self.max_position_usd * 100))

    @property
    def min_position_cents(self) -> int:
        return int(round(self.min_position_usd * 100))

    @property
    def max_total_exposure_cents(self) -> int:
        return int(round(self.max_total_exposure_usd * 100))

    @property
    def paper_bankroll_cents(self) -> int:
        return int(round(self.paper_bankroll_usd * 100))


class KalshiAutoTrader:
    def __init__(self, config: TraderConfig):
        self.config = config
        self.client = KalshiClient(env=config.env)
        self.state_path = Path(config.state_file)
        self.alpha_path = Path(config.alpha_file)

        self.current_day = self._utc_now().date().isoformat()
        self.daily_trades = 0
        self.positions: List[Dict[str, Any]] = []
        self.closed_positions: List[Dict[str, Any]] = []
        self.total_exposure_cents = 0
        self.total_pnl_cents = 0.0
        self.paper_cash_cents = config.paper_bankroll_cents
        self.loaded_schema_version = 0

        self.load_state()
        self._sync_totals()
        self.save_state()
        self._print_startup_banner()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _utc_now_iso() -> str:
        return KalshiAutoTrader._utc_now().isoformat()

    def _print_startup_banner(self) -> None:
        print("\n" + "=" * 78)
        print("KALSHI AUTO-TRADER | Risk-managed alpha execution")
        print("=" * 78)
        print(f"Mode: {'PAPER' if self.config.paper_mode else 'LIVE'}")
        print(f"Environment: {self.config.env}")
        print(f"Enabled: {self.config.enabled}")
        print(f"State file: {self.state_path}")
        print(f"Alpha file: {self.alpha_path}")
        print(
            f"Limits: max_position=${self.config.max_position_usd:.2f}, "
            f"max_daily={self.config.max_daily_trades}, "
            f"max_exposure=${self.config.max_total_exposure_usd:.2f}"
        )
        print(
            f"Edge gates: gross>={self.config.min_edge * 100:.2f}%, "
            f"net>={self.config.min_net_edge * 100:.2f}% "
            f"(fee={self.config.fee_per_contract_prob * 100:.2f}¢/side, "
            f"slippage={self.config.slippage_spread_factor:.2f}*spread)"
        )
        if self.config.paper_mode:
            print(f"Paper cash: ${self.paper_cash_cents / 100:.2f}")
        print("=" * 78 + "\n")

    def _normalize_position(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ticker = str(raw.get("ticker", "")).strip()
        side = str(raw.get("side", "")).lower().strip()
        if not ticker or side not in {"yes", "no"}:
            return None

        count = int(raw.get("count", 0) or 0)
        if count <= 0:
            return None

        entry_price_cents = raw.get("entry_price_cents")
        if entry_price_cents is None:
            legacy_price = raw.get("price")
            if legacy_price is not None:
                prob = to_probability(legacy_price)
                entry_price_cents = probability_to_cents(prob or 0.0)
        entry_price_cents = int(entry_price_cents or 0)
        if entry_price_cents <= 0:
            return None

        notional_cents = int(raw.get("notional_cents") or (entry_price_cents * count))
        opened_at = raw.get("opened_at") or raw.get("timestamp") or self._utc_now_iso()
        signal_confidence = float(raw.get("signal_confidence", raw.get("confidence", 0.5)))
        entry_edge = float(raw.get("entry_edge", 0.0))
        entry_gross_edge = float(raw.get("entry_gross_edge", entry_edge))
        entry_cost_estimate = float(raw.get("entry_cost_estimate", 0.0))
        entry_fair_yes_probability = float(raw.get("entry_fair_yes_probability", 0.5))
        entry_win_probability = float(raw.get("entry_win_probability", 0.5))
        entry_fair_yes_probability = max(0.0, min(1.0, entry_fair_yes_probability))
        entry_win_probability = max(0.0, min(1.0, entry_win_probability))

        return {
            "position_id": str(raw.get("position_id") or f"legacy-{uuid.uuid4().hex[:10]}"),
            "ticker": ticker,
            "side": side,
            "count": count,
            "entry_price_cents": entry_price_cents,
            "entry_edge": entry_edge,
            "entry_gross_edge": entry_gross_edge,
            "entry_cost_estimate": entry_cost_estimate,
            "entry_fair_yes_probability": entry_fair_yes_probability,
            "entry_win_probability": entry_win_probability,
            "signal_confidence": signal_confidence,
            "opened_at": opened_at,
            "notional_cents": notional_cents,
            "source": str(raw.get("source", "unknown")),
        }

    def _normalize_closed_trade(self, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ticker = str(raw.get("ticker", "")).strip()
        side = str(raw.get("side", "")).lower().strip()
        if not ticker or side not in {"yes", "no"}:
            return None

        entry = int(raw.get("entry_price_cents", raw.get("price", 0)) or 0)
        exit_price = int(raw.get("exit_price_cents", raw.get("exit_price", 0)) or 0)
        count = int(raw.get("count", 0) or 0)
        if entry <= 0 or exit_price < 0 or count <= 0:
            return None

        notional = int(raw.get("notional_cents") or (entry * count))
        pnl = float(raw.get("pnl_cents", raw.get("pnl", 0.0)) or 0.0)
        pnl_pct = float(raw.get("pnl_pct", 0.0) or 0.0)
        entry_edge = float(raw.get("entry_edge", 0.0) or 0.0)
        entry_gross_edge = float(raw.get("entry_gross_edge", entry_edge) or 0.0)
        entry_cost_estimate = float(raw.get("entry_cost_estimate", 0.0) or 0.0)
        entry_fair_yes_probability = float(raw.get("entry_fair_yes_probability", 0.5) or 0.5)
        entry_win_probability = float(raw.get("entry_win_probability", 0.5) or 0.5)
        entry_fair_yes_probability = max(0.0, min(1.0, entry_fair_yes_probability))
        entry_win_probability = max(0.0, min(1.0, entry_win_probability))
        opened_at = raw.get("opened_at") or raw.get("timestamp") or self._utc_now_iso()
        closed_at = raw.get("closed_at") or raw.get("exit_time") or self._utc_now_iso()
        signal_confidence = float(raw.get("signal_confidence", raw.get("confidence", 0.5)) or 0.5)
        signal_confidence = max(0.0, min(1.0, signal_confidence))
        entry_source = str(raw.get("entry_source", raw.get("source", "unknown")))

        return {
            "ticker": ticker,
            "side": side,
            "count": count,
            "entry_price_cents": entry,
            "exit_price_cents": exit_price,
            "notional_cents": notional,
            "pnl_cents": pnl,
            "pnl_pct": pnl_pct,
            "entry_edge": entry_edge,
            "entry_gross_edge": entry_gross_edge,
            "entry_cost_estimate": entry_cost_estimate,
            "entry_fair_yes_probability": entry_fair_yes_probability,
            "entry_win_probability": entry_win_probability,
            "signal_confidence": signal_confidence,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "exit_reason": str(raw.get("exit_reason", raw.get("reason", "unknown"))),
            "entry_source": entry_source,
            "entry_order_id": raw.get("entry_order_id"),
            "exit_order_id": raw.get("exit_order_id"),
        }

    def load_state(self) -> None:
        if not self.state_path.exists():
            return

        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"⚠️ Failed to read state file: {exc}")
            return

        self.loaded_schema_version = int(state.get("schema_version", 0) or 0)
        if self.loaded_schema_version < 3:
            print(
                "ℹ️ Loading legacy state schema. Missing telemetry fields will be backfilled "
                "with conservative defaults during normalization."
            )

        saved_day = str(state.get("current_day", self.current_day))
        if saved_day == self.current_day:
            self.daily_trades = int(state.get("daily_trades", 0) or 0)
        else:
            self.daily_trades = 0

        self.positions = []
        for raw_position in state.get("positions", []):
            normalized = self._normalize_position(raw_position)
            if normalized:
                self.positions.append(normalized)

        self.closed_positions = []
        for raw_trade in state.get("closed_positions", []):
            normalized = self._normalize_closed_trade(raw_trade)
            if normalized:
                self.closed_positions.append(normalized)

        self.total_pnl_cents = float(
            state.get("total_pnl_cents", state.get("total_pnl", 0.0)) or 0.0
        )
        loaded_cash = state.get("paper_cash_cents")
        if loaded_cash is not None:
            self.paper_cash_cents = int(loaded_cash)

    def _sync_totals(self) -> None:
        self.total_exposure_cents = sum(int(pos["notional_cents"]) for pos in self.positions)
        closed_pnl = sum(float(trade.get("pnl_cents", 0.0) or 0.0) for trade in self.closed_positions)
        if abs(closed_pnl) > 0:
            self.total_pnl_cents = closed_pnl

    def _config_snapshot(self) -> Dict[str, Any]:
        return {
            "env": self.config.env,
            "enabled": self.config.enabled,
            "paper_mode": self.config.paper_mode,
            "paper_bankroll_usd": self.config.paper_bankroll_usd,
            "max_position_usd": self.config.max_position_usd,
            "min_position_usd": self.config.min_position_usd,
            "max_daily_trades": self.config.max_daily_trades,
            "max_total_exposure_usd": self.config.max_total_exposure_usd,
            "min_signal_confidence": self.config.min_signal_confidence,
            "min_edge": self.config.min_edge,
            "min_net_edge": self.config.min_net_edge,
            "max_spread": self.config.max_spread,
            "min_volume": self.config.min_volume,
            "fee_per_contract_prob": self.config.fee_per_contract_prob,
            "slippage_spread_factor": self.config.slippage_spread_factor,
            "kelly_fraction": self.config.kelly_fraction,
            "take_profit_pct": self.config.take_profit_pct,
            "stop_loss_pct": self.config.stop_loss_pct,
            "max_holding_minutes": self.config.max_holding_minutes,
            "scan_interval_seconds": self.config.scan_interval_seconds,
            "markets_limit": self.config.markets_limit,
        }

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        metrics = compute_performance_metrics(self.closed_positions)
        state = {
            "schema_version": 3,
            "updated_at": self._utc_now_iso(),
            "current_day": self.current_day,
            "daily_trades": self.daily_trades,
            "positions": self.positions,
            "closed_positions": self.closed_positions[-2000:],
            "total_exposure_cents": self.total_exposure_cents,
            "total_pnl_cents": self.total_pnl_cents,
            "paper_cash_cents": self.paper_cash_cents,
            "config": self._config_snapshot(),
            "performance": metrics,
            "migration_notes": {
                "v3": (
                    "Closed-trade telemetry contract standardized. Older records may have "
                    "defaulted entry_edge/entry_gross_edge/entry_cost_estimate fields."
                )
            },
        }
        self.state_path.write_text(json.dumps(state, indent=2))

    def _reset_daily_counter_if_needed(self) -> None:
        today = self._utc_now().date().isoformat()
        if today != self.current_day:
            self.current_day = today
            self.daily_trades = 0
            print("🔄 New UTC day detected: reset daily trade counter.")

    def _fetch_quotes(self) -> List[MarketQuote]:
        raw_markets = self.client.get_markets(status="open", limit=self.config.markets_limit)
        quotes: List[MarketQuote] = []
        for raw in raw_markets:
            quote = MarketQuote.from_market(raw)
            if quote:
                quotes.append(quote)
        return quotes

    def _available_cash_cents(self) -> int:
        if self.config.paper_mode:
            return max(0, int(self.paper_cash_cents))
        balance = int(self.client.get_balance() or 0)
        return max(0, balance)

    def _has_open_position(self, ticker: str) -> bool:
        return any(pos["ticker"] == ticker for pos in self.positions)

    def _compute_edge(self, quote: MarketQuote, signal: AlphaSignal) -> Optional[Dict[str, Any]]:
        yes_entry = quote.entry_price("yes")
        no_entry = quote.entry_price("no")
        if yes_entry is None or no_entry is None:
            return None

        edge_yes = signal.fair_yes_probability - yes_entry
        edge_no = (1.0 - signal.fair_yes_probability) - no_entry

        if edge_yes >= edge_no:
            side = "yes"
            edge = edge_yes
            entry_probability = yes_entry
            win_probability = signal.fair_yes_probability
        else:
            side = "no"
            edge = edge_no
            entry_probability = no_entry
            win_probability = 1.0 - signal.fair_yes_probability

        spread = quote.spread(side)
        if spread is None:
            return None

        round_trip_cost = (2.0 * self.config.fee_per_contract_prob) + (
            spread * self.config.slippage_spread_factor
        )
        net_edge = edge - round_trip_cost

        if edge < self.config.min_edge:
            return None
        if net_edge < self.config.min_net_edge:
            return None
        if spread > self.config.max_spread:
            return None
        if quote.volume < self.config.min_volume:
            return None
        if signal.confidence < self.config.min_signal_confidence:
            return None

        spread_penalty = spread / self.config.max_spread if self.config.max_spread > 0 else 0.0
        score = net_edge * signal.confidence * max(0.1, 1.0 - spread_penalty)

        return {
            "ticker": quote.ticker,
            "title": quote.title,
            "side": side,
            "gross_edge": edge,
            "cost_estimate": round_trip_cost,
            "net_edge": net_edge,
            "entry_probability": entry_probability,
            "entry_price_cents": probability_to_cents(entry_probability),
            "spread": spread,
            "volume": quote.volume,
            "fair_yes_probability": signal.fair_yes_probability,
            "signal_confidence": signal.confidence,
            "source": signal.source,
            "score": score,
            "win_probability": win_probability,
        }

    def _position_size(self, candidate: Dict[str, Any]) -> Tuple[int, int]:
        entry_price_cents = int(candidate["entry_price_cents"])
        if entry_price_cents <= 0:
            return 0, 0

        available_cash = self._available_cash_cents()
        remaining_exposure = self.config.max_total_exposure_cents - self.total_exposure_cents
        if available_cash <= 0 or remaining_exposure <= 0:
            return 0, 0

        kelly = compute_binary_kelly(candidate["win_probability"], candidate["entry_probability"])
        gross_edge = max(float(candidate.get("gross_edge", 0.0)), 1e-9)
        edge_quality = max(0.0, min(1.0, float(candidate.get("net_edge", 0.0)) / gross_edge))
        adjusted_fraction = (
            kelly
            * self.config.kelly_fraction
            * candidate["signal_confidence"]
            * edge_quality
        )

        size_from_kelly = int(available_cash * adjusted_fraction)
        target_notional = max(self.config.min_position_cents, size_from_kelly)
        target_notional = min(
            target_notional,
            self.config.max_position_cents,
            remaining_exposure,
            available_cash,
        )

        contracts = target_notional // entry_price_cents
        if contracts < 1:
            return 0, 0

        notional = contracts * entry_price_cents
        if notional < self.config.min_position_cents:
            return 0, 0
        return contracts, notional

    def _scan_candidates(self, signals: Dict[str, AlphaSignal]) -> List[Dict[str, Any]]:
        quotes = self._fetch_quotes()
        candidates: List[Dict[str, Any]] = []

        for quote in quotes:
            if self._has_open_position(quote.ticker):
                continue
            signal = signals.get(quote.ticker)
            if not signal:
                continue
            candidate = self._compute_edge(quote, signal)
            if candidate:
                candidates.append(candidate)

        candidates.sort(key=lambda item: item["score"], reverse=True)
        return candidates

    def _submit_order(
        self, action: str, ticker: str, side: str, count: int
    ) -> Tuple[bool, str]:
        if count <= 0:
            return False, "invalid_count"

        if self.config.paper_mode:
            return True, f"paper-{action}-{uuid.uuid4().hex[:12]}"

        if not self.client.authenticated:
            return False, "client_not_authenticated"

        try:
            result = self.client.client.create_order(
                ticker=ticker,
                action=action,
                side=side,
                count=count,
                type="market",
            )
            return True, str(getattr(result, "order_id", "unknown_order_id"))
        except Exception as exc:
            return False, str(exc)

    def _open_position(self, candidate: Dict[str, Any]) -> bool:
        if not self.config.enabled:
            print("⏸️ Trader disabled; skipping entries.")
            return False
        if self.daily_trades >= self.config.max_daily_trades:
            print(f"⛔ Daily trade limit reached ({self.daily_trades}/{self.config.max_daily_trades}).")
            return False

        contracts, notional = self._position_size(candidate)
        if contracts == 0:
            return False

        success, order_id = self._submit_order(
            action="buy",
            ticker=candidate["ticker"],
            side=candidate["side"],
            count=contracts,
        )
        if not success:
            print(f"❌ Entry order failed for {candidate['ticker']}: {order_id}")
            return False

        position = {
            "position_id": f"pos-{uuid.uuid4().hex[:12]}",
            "ticker": candidate["ticker"],
            "side": candidate["side"],
            "count": contracts,
            "entry_price_cents": int(candidate["entry_price_cents"]),
            "entry_edge": float(candidate["net_edge"]),
            "entry_gross_edge": float(candidate["gross_edge"]),
            "entry_cost_estimate": float(candidate["cost_estimate"]),
            "entry_fair_yes_probability": float(candidate["fair_yes_probability"]),
            "entry_win_probability": float(candidate["win_probability"]),
            "signal_confidence": float(candidate["signal_confidence"]),
            "opened_at": self._utc_now_iso(),
            "notional_cents": notional,
            "source": candidate["source"],
            "order_id": order_id,
        }
        self.positions.append(position)
        self.daily_trades += 1
        self.total_exposure_cents += notional
        if self.config.paper_mode:
            self.paper_cash_cents -= notional

        print(
            f"✅ ENTRY {candidate['ticker']} {candidate['side'].upper()} "
            f"{contracts} @ {candidate['entry_price_cents']}¢ | "
            f"net_edge={candidate['net_edge'] * 100:.2f}% "
            f"(gross={candidate['gross_edge'] * 100:.2f}%, costs={candidate['cost_estimate'] * 100:.2f}%) "
            f"conf={candidate['signal_confidence'] * 100:.0f}%"
        )
        return True

    def _current_edge_for_position(
        self,
        position: Dict[str, Any],
        quote: MarketQuote,
        signals: Dict[str, AlphaSignal],
    ) -> Optional[float]:
        signal = signals.get(position["ticker"])
        if not signal:
            return None

        side = position["side"]
        if side == "yes":
            current_reference = quote.exit_price("yes")
            if current_reference is None:
                return None
            return signal.fair_yes_probability - current_reference

        current_reference = quote.exit_price("no")
        if current_reference is None:
            return None
        return (1.0 - signal.fair_yes_probability) - current_reference

    def _close_position(
        self,
        position: Dict[str, Any],
        exit_price_cents: int,
        reason: str,
    ) -> bool:
        success, order_id = self._submit_order(
            action="sell",
            ticker=position["ticker"],
            side=position["side"],
            count=int(position["count"]),
        )
        if not success:
            print(f"❌ Exit order failed for {position['ticker']}: {order_id}")
            return False

        entry_notional = int(position["entry_price_cents"]) * int(position["count"])
        exit_value = exit_price_cents * int(position["count"])
        pnl_cents = exit_value - entry_notional
        pnl_pct = (pnl_cents / entry_notional) if entry_notional > 0 else 0.0

        closed = {
            "ticker": position["ticker"],
            "side": position["side"],
            "count": int(position["count"]),
            "entry_price_cents": int(position["entry_price_cents"]),
            "exit_price_cents": int(exit_price_cents),
            "notional_cents": entry_notional,
            "pnl_cents": pnl_cents,
            "pnl_pct": pnl_pct,
            "entry_edge": float(position.get("entry_edge", 0.0)),
            "entry_gross_edge": float(position.get("entry_gross_edge", position.get("entry_edge", 0.0))),
            "entry_cost_estimate": float(position.get("entry_cost_estimate", 0.0)),
            "entry_fair_yes_probability": float(position.get("entry_fair_yes_probability", 0.5)),
            "entry_win_probability": float(position.get("entry_win_probability", 0.5)),
            "signal_confidence": float(position.get("signal_confidence", 0.5)),
            "opened_at": position["opened_at"],
            "closed_at": self._utc_now_iso(),
            "exit_reason": reason,
            "entry_source": position.get("source", "unknown"),
            "entry_order_id": position.get("order_id"),
            "exit_order_id": order_id,
        }
        self.closed_positions.append(closed)
        self.total_pnl_cents += pnl_cents
        self.total_exposure_cents = max(0, self.total_exposure_cents - entry_notional)

        if self.config.paper_mode:
            self.paper_cash_cents += exit_value

        print(
            f"📤 EXIT {position['ticker']} {position['side'].upper()} "
            f"@ {exit_price_cents}¢ | pnl=${pnl_cents / 100:+.2f} "
            f"({pnl_pct * 100:+.2f}%) | {reason}"
        )
        return True

    def check_exits(self, signals: Dict[str, AlphaSignal]) -> int:
        if not self.positions:
            return 0

        quotes = {quote.ticker: quote for quote in self._fetch_quotes()}
        remaining_positions: List[Dict[str, Any]] = []
        closed_count = 0

        for position in self.positions:
            quote = quotes.get(position["ticker"])
            if quote is None:
                remaining_positions.append(position)
                continue

            side = position["side"]
            exit_probability = quote.exit_price(side)
            if exit_probability is None:
                remaining_positions.append(position)
                continue

            exit_price_cents = probability_to_cents(exit_probability)
            entry_notional = int(position["entry_price_cents"]) * int(position["count"])
            mark_value = exit_price_cents * int(position["count"])
            pnl_pct = (mark_value - entry_notional) / entry_notional if entry_notional > 0 else 0.0

            opened_at = parse_timestamp(position.get("opened_at"))
            holding_minutes = 0.0
            if opened_at:
                holding_minutes = (self._utc_now() - opened_at).total_seconds() / 60.0

            reason = ""
            if pnl_pct >= self.config.take_profit_pct:
                reason = f"take_profit_{self.config.take_profit_pct:.2f}"
            elif pnl_pct <= -self.config.stop_loss_pct:
                reason = f"stop_loss_{self.config.stop_loss_pct:.2f}"
            elif holding_minutes >= self.config.max_holding_minutes:
                reason = f"time_stop_{self.config.max_holding_minutes}m"
            else:
                edge_now = self._current_edge_for_position(position, quote, signals)
                if edge_now is not None and edge_now < -(self.config.min_edge / 2):
                    reason = "edge_reversal"

            if not reason:
                remaining_positions.append(position)
                continue

            if self._close_position(position, exit_price_cents, reason):
                closed_count += 1
            else:
                remaining_positions.append(position)

        self.positions = remaining_positions
        return closed_count

    def run_cycle(self) -> None:
        self._reset_daily_counter_if_needed()
        cycle_time = self._utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n[{cycle_time}] Cycle start")

        signals = load_alpha_signals(self.alpha_path)
        if not signals:
            print(f"⚠️ No alpha signals loaded from {self.alpha_path}; entry scan skipped.")
            self.save_state()
            return

        closed = self.check_exits(signals)
        if closed:
            print(f"Closed positions this cycle: {closed}")

        candidates = self._scan_candidates(signals)
        if not candidates:
            print("No entry candidates passed filters.")
            self.save_state()
            return

        top = candidates[0]
        self._open_position(top)
        self.save_state()

    def print_performance_summary(self) -> None:
        metrics = compute_performance_metrics(self.closed_positions)
        print("\n" + "-" * 78)
        print(
            f"Open positions: {len(self.positions)} | "
            f"Daily trades: {self.daily_trades}/{self.config.max_daily_trades} | "
            f"Exposure: ${self.total_exposure_cents / 100:.2f}"
        )
        print(
            f"Closed trades: {int(metrics['trades'])} | "
            f"Win rate: {metrics['win_rate'] * 100:.1f}% | "
            f"Expectancy: {metrics['expectancy_pct']:.2f}% | "
            f"Profit factor: {metrics['profit_factor']:.2f}"
        )
        print(
            f"Total PnL: ${metrics['total_pnl_cents'] / 100:+.2f} | "
            f"Max drawdown: ${metrics['max_drawdown_cents'] / 100:.2f}"
        )
        if self.config.paper_mode:
            print(f"Paper cash: ${self.paper_cash_cents / 100:.2f}")
        print("-" * 78)

    def run(self) -> None:
        cycle = 0
        try:
            while True:
                cycle += 1
                self.run_cycle()
                self.print_performance_summary()
                time.sleep(self.config.scan_interval_seconds)
        except KeyboardInterrupt:
            print(f"\n⏹️ Stopped after {cycle} cycles.")
            self.save_state()
            self.print_performance_summary()


def build_config(args: argparse.Namespace) -> TraderConfig:
    return TraderConfig(
        env=args.env,
        enabled=not args.disabled,
        paper_mode=not args.live,
        paper_bankroll_usd=args.paper_bankroll,
        max_position_usd=args.max_position,
        min_position_usd=args.min_position,
        max_daily_trades=args.max_trades,
        max_total_exposure_usd=args.max_exposure,
        min_signal_confidence=args.min_confidence,
        min_edge=args.min_edge,
        min_net_edge=args.min_net_edge,
        max_spread=args.max_spread,
        min_volume=args.min_volume,
        fee_per_contract_prob=args.fee_per_contract,
        slippage_spread_factor=args.slippage_factor,
        kelly_fraction=args.kelly_fraction,
        take_profit_pct=args.take_profit,
        stop_loss_pct=args.stop_loss,
        max_holding_minutes=args.max_holding_minutes,
        scan_interval_seconds=args.interval,
        markets_limit=args.markets_limit,
        state_file=args.state_file,
        alpha_file=args.alpha_file,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kalshi auto-trader")
    parser.add_argument("--env", default="prod", choices=["demo", "prod"])
    parser.add_argument("--live", action="store_true", help="Enable live order placement")
    parser.add_argument("--disabled", action="store_true", help="Disable new entries")
    parser.add_argument("--run-once", action="store_true", help="Run one cycle and exit")

    parser.add_argument("--paper-bankroll", type=float, default=250.0, help="Paper mode bankroll in USD")
    parser.add_argument("--max-position", type=float, default=20.0, help="Max position size in USD")
    parser.add_argument("--min-position", type=float, default=5.0, help="Min position size in USD")
    parser.add_argument("--max-trades", type=int, default=12, help="Max trades per UTC day")
    parser.add_argument("--max-exposure", type=float, default=150.0, help="Max total exposure in USD")

    # Backward-compatible argument name.
    parser.add_argument("--min-confidence", type=float, default=0.65, help="Minimum alpha confidence [0,1]")
    parser.add_argument("--min-edge", type=float, default=0.03, help="Minimum expected edge [0,1]")
    parser.add_argument(
        "--min-net-edge",
        type=float,
        default=0.015,
        help="Minimum expected edge after fee/slippage costs [0,1]",
    )
    parser.add_argument("--max-spread", type=float, default=0.06, help="Maximum bid-ask spread [0,1]")
    parser.add_argument("--min-volume", type=float, default=500.0, help="Minimum market volume filter")
    parser.add_argument(
        "--fee-per-contract",
        type=float,
        default=0.008,
        help="Estimated one-way fee in probability units (0.008 = 0.8 cents)",
    )
    parser.add_argument(
        "--slippage-factor",
        type=float,
        default=0.35,
        help="Expected slippage as fraction of spread included in cost model",
    )
    parser.add_argument("--kelly-fraction", type=float, default=0.25, help="Fraction of Kelly position sizing")
    parser.add_argument("--take-profit", type=float, default=0.20, help="Take-profit threshold [0,1]")
    parser.add_argument("--stop-loss", type=float, default=0.12, help="Stop-loss threshold [0,1]")
    parser.add_argument("--max-holding-minutes", type=int, default=240, help="Time-based stop in minutes")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between cycles")
    parser.add_argument("--markets-limit", type=int, default=300, help="Number of markets to request per cycle")
    parser.add_argument("--state-file", default="data/auto_trader_state.json")
    parser.add_argument("--alpha-file", default="data/alpha_signals.json")

    # Deprecated flag retained for old deployment scripts.
    parser.add_argument("--enabled", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    config = build_config(cli_args)
    trader = KalshiAutoTrader(config)

    if cli_args.run_once:
        trader.run_cycle()
        trader.print_performance_summary()
    else:
        trader.run()
