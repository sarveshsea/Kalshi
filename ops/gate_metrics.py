"""
Shared gate and telemetry calculations for paper-trading promotion.
"""
from __future__ import annotations

from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.trading import compute_performance_metrics, to_probability


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return value


def _prob_or_none(raw: Any):
    if raw is None:
        return None
    return to_probability(raw)


def compute_execution_cost_summary(
    closed_positions: Sequence[Dict[str, Any]],
    *,
    fee_per_contract_prob: float,
    slippage_spread_factor: float,
) -> Dict[str, Any]:
    total_notional_cents = 0.0
    total_pnl_cents = 0.0
    estimated_cost_cents = 0.0
    cost_coverage = 0

    gross_edges: List[float] = []
    net_edges: List[float] = []
    cost_estimates: List[float] = []

    for trade in closed_positions:
        if not isinstance(trade, dict):
            continue
        notional = _safe_float(trade.get("notional_cents"), 0.0)
        pnl = _safe_float(trade.get("pnl_cents", trade.get("pnl", 0.0)), 0.0)
        total_notional_cents += max(0.0, notional)
        total_pnl_cents += pnl

        net_edge = _prob_or_none(trade.get("entry_edge"))
        gross_edge = _prob_or_none(trade.get("entry_gross_edge"))
        cost = _prob_or_none(trade.get("entry_cost_estimate"))

        if gross_edge is None and net_edge is not None:
            gross_edge = net_edge
        if cost is None and gross_edge is not None and net_edge is not None:
            cost = max(0.0, gross_edge - net_edge)

        if net_edge is not None:
            net_edges.append(net_edge)
        if gross_edge is not None:
            gross_edges.append(gross_edge)
        if cost is not None:
            cost_estimates.append(cost)

        has_cost_telemetry = (
            ("entry_edge" in trade)
            or ("entry_gross_edge" in trade)
            or ("entry_cost_estimate" in trade)
        )
        if has_cost_telemetry:
            cost_coverage += 1

        count = int(_safe_float(trade.get("count"), 0.0))
        if count > 0 and cost is not None:
            estimated_cost_cents += cost * 100.0 * count

    avg_gross_edge = mean(gross_edges) if gross_edges else 0.0
    avg_net_edge = mean(net_edges) if net_edges else 0.0
    avg_cost = mean(cost_estimates) if cost_estimates else max(0.0, avg_gross_edge - avg_net_edge)

    total_trades = len(closed_positions)
    coverage_ratio = (cost_coverage / total_trades) if total_trades > 0 else 0.0

    return {
        "closed_trades": total_trades,
        "cost_coverage_trades": cost_coverage,
        "cost_coverage_ratio": coverage_ratio,
        "fee_per_contract_prob": fee_per_contract_prob,
        "slippage_spread_factor": slippage_spread_factor,
        "avg_gross_edge": avg_gross_edge,
        "avg_net_edge": avg_net_edge,
        "avg_round_trip_cost": avg_cost,
        "estimated_total_cost_cents": estimated_cost_cents,
        "total_notional_cents": total_notional_cents,
        "realized_pnl_cents": total_pnl_cents,
        "realized_return_pct": (total_pnl_cents / total_notional_cents * 100.0) if total_notional_cents > 0 else 0.0,
        "estimated_cost_bps_on_notional": (
            estimated_cost_cents / total_notional_cents * 10000.0
            if total_notional_cents > 0
            else 0.0
        ),
    }


def compute_ticker_concentration(closed_positions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_ticker: Dict[str, float] = {}
    for trade in closed_positions:
        if not isinstance(trade, dict):
            continue
        ticker = str(trade.get("ticker", "")).strip()
        if not ticker:
            continue
        pnl = _safe_float(trade.get("pnl_cents", trade.get("pnl", 0.0)), 0.0)
        by_ticker[ticker] = by_ticker.get(ticker, 0.0) + pnl

    if not by_ticker:
        return {
            "ticker_count": 0,
            "max_ticker": None,
            "max_abs_pnl_cents": 0.0,
            "total_abs_pnl_cents": 0.0,
            "max_share_of_abs_pnl": 0.0,
            "ticker_pnl_cents": {},
        }

    total_abs = sum(abs(v) for v in by_ticker.values())
    max_ticker = max(by_ticker, key=lambda t: abs(by_ticker[t]))
    max_abs = abs(by_ticker[max_ticker])
    share = (max_abs / total_abs) if total_abs > 0 else 0.0
    return {
        "ticker_count": len(by_ticker),
        "max_ticker": max_ticker,
        "max_abs_pnl_cents": max_abs,
        "total_abs_pnl_cents": total_abs,
        "max_share_of_abs_pnl": share,
        "ticker_pnl_cents": by_ticker,
    }


def compute_trailing_expectancy(
    closed_positions: Sequence[Dict[str, Any]],
    windows: Iterable[int],
) -> Dict[int, Optional[float]]:
    result: Dict[int, Optional[float]] = {}
    for window in windows:
        window = int(window)
        if window <= 0:
            continue
        if len(closed_positions) < window:
            result[window] = None
            continue
        metrics = compute_performance_metrics(list(closed_positions[-window:]))
        result[window] = float(metrics["expectancy_pct"])
    return result


def evaluate_go_live_gates(
    closed_positions: Sequence[Dict[str, Any]],
    *,
    paper_bankroll: float,
    min_trades: int,
    min_expectancy: float,
    min_profit_factor: float,
    max_drawdown: float,
    min_cost_coverage: float,
    holdout_windows: Sequence[int],
    max_concentration_share: float,
    fee_per_contract_prob: float,
    slippage_spread_factor: float,
) -> Dict[str, Any]:
    metrics = compute_performance_metrics(list(closed_positions))
    trades = int(metrics["trades"])
    expectancy = float(metrics["expectancy_pct"])
    profit_factor = float(metrics["profit_factor"])
    max_drawdown_pct = (
        float(metrics["max_drawdown_cents"]) / max(paper_bankroll * 100.0, 1.0) * 100.0
    )

    cost_summary = compute_execution_cost_summary(
        closed_positions,
        fee_per_contract_prob=fee_per_contract_prob,
        slippage_spread_factor=slippage_spread_factor,
    )
    concentration = compute_ticker_concentration(closed_positions)
    holdout_expectancies = compute_trailing_expectancy(closed_positions, holdout_windows)

    checks: List[Dict[str, Any]] = [
        {
            "name": "trades",
            "pass": trades >= min_trades,
            "value": float(trades),
            "threshold": float(min_trades),
            "direction": ">=",
            "progress": min(1.0, trades / max(min_trades, 1)),
        },
        {
            "name": "expectancy_pct",
            "pass": expectancy > min_expectancy,
            "value": expectancy,
            "threshold": min_expectancy,
            "direction": ">",
            "progress": 1.0 if expectancy > min_expectancy else 0.0,
        },
        {
            "name": "profit_factor",
            "pass": profit_factor >= min_profit_factor,
            "value": profit_factor,
            "threshold": min_profit_factor,
            "direction": ">=",
            "progress": min(1.0, profit_factor / max(min_profit_factor, 1e-9)),
        },
        {
            "name": "max_drawdown_pct",
            "pass": max_drawdown_pct <= max_drawdown,
            "value": max_drawdown_pct,
            "threshold": max_drawdown,
            "direction": "<=",
            "progress": min(1.0, max_drawdown / max(max_drawdown_pct, 1e-9)),
        },
        {
            "name": "cost_coverage_ratio",
            "pass": float(cost_summary["cost_coverage_ratio"]) >= min_cost_coverage,
            "value": float(cost_summary["cost_coverage_ratio"]),
            "threshold": min_cost_coverage,
            "direction": ">=",
            "progress": min(
                1.0,
                float(cost_summary["cost_coverage_ratio"]) / max(min_cost_coverage, 1e-9),
            ),
        },
    ]

    for window in holdout_windows:
        val = holdout_expectancies.get(int(window))
        window_ready = val is not None
        checks.append(
            {
                "name": f"holdout_expectancy_{int(window)}",
                "pass": bool(window_ready and val > 0.0),
                "value": val if val is not None else "insufficient_trades",
                "threshold": 0.0,
                "direction": ">",
                "progress": 1.0 if bool(window_ready and val > 0.0) else 0.0,
            }
        )

    concentration_share = float(concentration["max_share_of_abs_pnl"])
    checks.append(
        {
            "name": "max_ticker_concentration",
            "pass": concentration_share <= max_concentration_share,
            "value": concentration_share,
            "threshold": max_concentration_share,
            "direction": "<=",
            "progress": min(1.0, max_concentration_share / max(concentration_share, 1e-9)),
        }
    )

    return {
        "metrics": metrics,
        "max_drawdown_pct": max_drawdown_pct,
        "checks": checks,
        "go_live": all(item["pass"] for item in checks),
        "cost_summary": cost_summary,
        "concentration": concentration,
        "holdout_expectancies": holdout_expectancies,
    }
