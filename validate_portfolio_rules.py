"""Choose the locked portfolio size using only the 2015-2019 validation period.

All other portfolio rules are fixed before this script runs. The locked
2020-2024 period is never read by the portfolio construction/evaluation code.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


INPUT_FILE = Path("factor_detector_v2/neutralized_factor_panel.parquet")
MANIFEST_FILE = Path("factor_detector_v2/locked_model_manifest.json")
OUTPUT_DIR = Path("portfolio_validation")

VALIDATION_START = pd.Timestamp("2015-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")

FACTOR_WEIGHTS = {
    "accruals_neutral": 0.50,
    "cfo_roa_neutral": 0.50,
}
PORTFOLIO_SIZES = [30, 50, 100]
MAX_STOCK_WEIGHT = 0.03
MAX_INDUSTRY_WEIGHT = 0.25
MINIMUM_ELIGIBLE_STOCKS = 100
ONE_WAY_TRANSACTION_COST = 0.001
SHARPE_TIE_BAND = 0.10


def sic_division(industry2: pd.Series) -> pd.Series:
    output = industry2.fillna("UNKNOWN").astype(str).str.strip()
    division = output.str[0]
    return division.where(division.str.match(r"\d"), "UNKNOWN")


def make_weights(
    cross_section: pd.DataFrame, target_count: int
) -> tuple[pd.DataFrame, dict]:
    # Eligibility is based only on information available at the signal date.
    # Future returns are deliberately not part of the selection filter.
    eligible = cross_section.dropna(subset=[*FACTOR_WEIGHTS]).copy()
    diagnostics = {
        "eligible_count": int(len(eligible)),
        "selected_count": 0,
        "missing_return_count": 0,
        "fully_invested": False,
    }
    if len(eligible) < MINIMUM_ELIGIBLE_STOCKS:
        return eligible.iloc[0:0].copy(), diagnostics

    eligible["composite_score"] = sum(
        weight * eligible[column] for column, weight in FACTOR_WEIGHTS.items()
    )
    eligible = eligible.sort_values(
        ["composite_score", "permno"], ascending=[False, True]
    )

    stock_weight = min(1.0 / target_count, MAX_STOCK_WEIGHT)
    max_per_industry = max(
        1, math.floor(MAX_INDUSTRY_WEIGHT / stock_weight + 1e-12)
    )
    selected_indices = []
    industry_counts: dict[str, int] = {}
    for index, row in eligible.iterrows():
        industry = row["industry_division"]
        if industry_counts.get(industry, 0) >= max_per_industry:
            continue
        selected_indices.append(index)
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        if len(selected_indices) == target_count:
            break

    selected = eligible.loc[selected_indices].copy()
    diagnostics["missing_return_count"] = int(
        selected["forward_return_1m"].isna().sum()
    )
    selected["target_weight"] = stock_weight
    invested_weight = float(selected["target_weight"].sum())
    selected["cash_weight"] = max(0.0, 1.0 - invested_weight)
    diagnostics.update(
        {
            "selected_count": int(len(selected)),
            "stock_weight": stock_weight,
            "invested_weight": invested_weight,
            "cash_weight": max(0.0, 1.0 - invested_weight),
            "fully_invested": abs(invested_weight - 1.0) < 1e-9,
            "maximum_industry_count": max(industry_counts.values(), default=0),
            "maximum_industry_weight": max(
                (count * stock_weight for count in industry_counts.values()),
                default=0.0,
            ),
        }
    )
    return selected, diagnostics


def calculate_weight_turnover(
    previous: dict[str, float], current: dict[str, float]
) -> float:
    assets = set(previous) | set(current)
    return 0.5 * sum(
        abs(current.get(asset, 0.0) - previous.get(asset, 0.0))
        for asset in assets
    )


def calculate_metrics(returns: pd.DataFrame) -> dict:
    net = returns["net_return"].dropna()
    if net.empty:
        return {}
    annual_return = (
        (1.0 + net).prod() ** (12.0 / len(net)) - 1.0
        if (1.0 + net).gt(0).all()
        else net.mean() * 12.0
    )
    annual_volatility = net.std() * math.sqrt(12.0)
    sharpe = (
        annual_return / annual_volatility
        if annual_volatility > 1e-12
        else np.nan
    )
    wealth = (1.0 + net).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    benchmark = returns.loc[net.index, "benchmark_cap_weighted_return"]
    excess = net - benchmark
    information_ratio = (
        excess.mean() / excess.std() * math.sqrt(12.0)
        if excess.std() > 1e-12
        else np.nan
    )
    return {
        "months": int(len(net)),
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "sharpe_zero_rf": float(sharpe),
        "maximum_drawdown": float(drawdown.min()),
        "positive_month_ratio": float(net.gt(0).mean()),
        "average_turnover": float(returns.loc[net.index, "turnover"].mean()),
        "annualized_transaction_cost": float(
            returns.loc[net.index, "transaction_cost"].mean() * 12.0
        ),
        "benchmark_annual_return": float(
            (1.0 + benchmark).prod() ** (12.0 / len(benchmark)) - 1.0
        ),
        "annualized_excess_return_arithmetic": float(excess.mean() * 12.0),
        "information_ratio": float(information_ratio),
        "months_with_selection_failure": int(
            returns.loc[net.index, "selection_failure"].sum()
        ),
    }


def run_variant(
    validation: pd.DataFrame, target_count: int
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    return_rows = []
    holding_frames = []
    previous_weights = {"CASH": 1.0}

    for date, cross_section in validation.groupby("date", sort=True):
        selected, diagnostics = make_weights(cross_section, target_count)
        selection_failure = len(selected) < target_count
        if selected.empty:
            current_weights = {"CASH": 1.0}
            gross_return = np.nan
        else:
            stock_weights = {
                str(int(row.permno)): float(row.target_weight)
                for row in selected.itertuples()
            }
            cash_weight = max(0.0, 1.0 - sum(stock_weights.values()))
            current_weights = {**stock_weights, "CASH": cash_weight}
            gross_return = (
                float(
                    (
                        selected["target_weight"]
                        * selected["forward_return_1m"]
                    ).sum()
                )
                if diagnostics["missing_return_count"] == 0
                else np.nan
            )

            selected["portfolio_size_rule"] = target_count
            selected["signal_date"] = date
            holding_frames.append(
                selected[
                    [
                        "signal_date",
                        "portfolio_size_rule",
                        "permno",
                        "ticker",
                        "industry_division",
                        "composite_score",
                        "target_weight",
                        "forward_return_1m",
                    ]
                ]
            )

        turnover = calculate_weight_turnover(previous_weights, current_weights)
        transaction_cost = turnover * ONE_WAY_TRANSACTION_COST
        net_return = (
            gross_return - transaction_cost
            if pd.notna(gross_return)
            else np.nan
        )

        benchmark_sample = cross_section.dropna(
            subset=["forward_return_1m", "log_market_cap"]
        ).copy()
        benchmark_market_cap = np.exp(benchmark_sample["log_market_cap"])
        benchmark_weights = benchmark_market_cap / benchmark_market_cap.sum()
        benchmark_return = float(
            (benchmark_weights * benchmark_sample["forward_return_1m"]).sum()
        )

        return_rows.append(
            {
                "date": date,
                "portfolio_size_rule": target_count,
                "eligible_count": diagnostics["eligible_count"],
                "selected_count": diagnostics["selected_count"],
                "invested_weight": diagnostics.get("invested_weight", 0.0),
                "cash_weight": diagnostics.get("cash_weight", 1.0),
                "maximum_industry_weight": diagnostics.get(
                    "maximum_industry_weight", np.nan
                ),
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "gross_return": gross_return,
                "net_return": net_return,
                "benchmark_cap_weighted_return": benchmark_return,
                "selection_failure": selection_failure,
                "missing_selected_returns": diagnostics["missing_return_count"],
            }
        )
        previous_weights = current_weights

    returns = pd.DataFrame(return_rows).sort_values("date").reset_index(drop=True)
    holdings = (
        pd.concat(holding_frames, ignore_index=True)
        if holding_frames
        else pd.DataFrame()
    )
    metrics = calculate_metrics(returns)
    metrics["portfolio_size_rule"] = target_count
    return returns, holdings, metrics


def choose_variant(summary: pd.DataFrame) -> int:
    eligible = summary.loc[summary["annual_return"].gt(0)].copy()
    if eligible.empty:
        raise RuntimeError("No validation variant has a positive net annual return.")
    maximum_sharpe = eligible["sharpe_zero_rf"].max()
    finalists = eligible.loc[
        eligible["sharpe_zero_rf"].ge(maximum_sharpe - SHARPE_TIE_BAND)
    ].copy()
    # Predeclared tie-break: prefer broader diversification, then lower turnover.
    finalists = finalists.sort_values(
        ["portfolio_size_rule", "average_turnover"],
        ascending=[False, True],
    )
    return int(finalists.iloc[0]["portfolio_size_rule"])


def lock_portfolio_manifest(
    selected_count: int, validation_summary: pd.DataFrame
) -> dict:
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    manifest.pop("configuration_sha256", None)
    manifest["status"] = "PORTFOLIO_RULES_LOCKED_BEFORE_FINAL_TEST"
    manifest["portfolio_rules"] = {
        "factor_weights": {
            "accruals": 0.50,
            "cfo_roa": 0.50,
        },
        "required_factor_data": "both factors must be non-missing",
        "portfolio_size": selected_count,
        "position_weighting": "equal weight",
        "maximum_stock_weight": MAX_STOCK_WEIGHT,
        "industry_definition": "SIC first digit",
        "maximum_industry_weight": MAX_INDUSTRY_WEIGHT,
        "minimum_eligible_stocks": MINIMUM_ELIGIBLE_STOCKS,
        "rebalance_frequency": "monthly",
        "signal_timing": "month-end signal, next-month return",
        "one_way_transaction_cost": ONE_WAY_TRANSACTION_COST,
        "missing_return_policy": "do not replace missing returns with zero",
        "delisting_policy": "CRSP total return includes DLRET when available",
        "cash_return_assumption": 0.0,
    }
    manifest["portfolio_size_validation_candidates"] = PORTFOLIO_SIZES
    manifest["portfolio_size_selection_rule"] = (
        "positive net return; highest Sharpe; if within 0.10 choose broader "
        "portfolio, then lower turnover"
    )
    manifest["selected_validation_summary"] = validation_summary.loc[
        validation_summary["portfolio_size_rule"].eq(selected_count)
    ].iloc[0].to_dict()
    manifest["final_test_has_been_run_by_v2"] = False

    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["configuration_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return manifest


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(INPUT_FILE)
    panel["date"] = pd.to_datetime(panel["date"])

    # This is the only period passed into every portfolio function below.
    validation = panel.loc[
        panel["date"].between(VALIDATION_START, VALIDATION_END)
    ].copy()
    validation["industry_division"] = sic_division(validation["industry2"])

    all_returns = []
    all_holdings = []
    summaries = []
    for target_count in PORTFOLIO_SIZES:
        returns, holdings, metrics = run_variant(validation, target_count)
        all_returns.append(returns)
        all_holdings.append(holdings)
        summaries.append(metrics)

    returns_frame = pd.concat(all_returns, ignore_index=True)
    holdings_frame = pd.concat(all_holdings, ignore_index=True)
    summary = pd.DataFrame(summaries).sort_values("portfolio_size_rule")
    selected_count = choose_variant(summary)

    returns_frame.to_csv(OUTPUT_DIR / "validation_portfolio_returns.csv", index=False)
    holdings_frame.to_parquet(
        OUTPUT_DIR / "validation_portfolio_holdings.parquet", index=False
    )
    summary.to_csv(OUTPUT_DIR / "validation_portfolio_summary.csv", index=False)

    manifest = lock_portfolio_manifest(selected_count, summary)
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (OUTPUT_DIR / "portfolio_lock_snapshot.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(summary.to_string(index=False))
    print("\nSelected portfolio size:", selected_count)
    print("Configuration hash:", manifest["configuration_sha256"])
    print("Final test executed by V2: False")


if __name__ == "__main__":
    main()
