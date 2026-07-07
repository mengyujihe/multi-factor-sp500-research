"""Reproducible single-factor validation for the S&P 500 factor panel.

The program uses only factor values observable at month-end and the already
prepared next-month return target. Three factors are sampled with a fixed seed
unless explicit factor names are supplied on the command line.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/codex-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DATABASE = Path(
    "factor_database/final/sp500_monthly_factor_panel_2000_2024.parquet"
)
OUTPUT_DIR = Path("factor_tests")
RANDOM_SEED = 20260706
QUANTILES = 5
ONE_WAY_COST = 0.001

# Direction is chosen from economic logic before examining factor performance.
# After orientation, a larger value always represents the expected "better"
# exposure and should have a positive IC/spread.
FACTOR_DIRECTIONS = {
    "book_to_market": 1,
    "earnings_yield": 1,
    "sales_yield": 1,
    "ebitda_to_ev": 1,
    "dividend_yield_12m": 1,
    "roa": 1,
    "roe": 1,
    "gross_profitability": 1,
    "operating_margin": 1,
    "cfo_roa": 1,
    "accruals": -1,
    "leverage": -1,
    "cash_to_assets": 1,
    "current_ratio": 1,
    "sales_growth_yoy": 1,
    "earnings_growth_yoy": 1,
    "asset_growth_yoy": -1,
    "capex_to_assets": -1,
    "net_buyback_to_assets": 1,
    "momentum_12_1": 1,
    "momentum_6_1": 1,
    "short_reversal": 1,
    "volatility_12m": -1,
    "turnover": 1,
    "illiquidity": -1,
    "log_market_cap": -1,
}

SUBPERIODS = {
    "research_2000_2014": ("2000-01-01", "2014-12-31"),
    "validation_2015_2019": ("2015-01-01", "2019-12-31"),
    "test_2020_2024": ("2020-01-01", "2024-12-31"),
}


def newey_west_mean_tstat(values: pd.Series, max_lag: int = 3) -> float:
    """HAC t-statistic for whether a monthly series has mean zero."""
    x = values.dropna().astype(float).to_numpy()
    n = len(x)
    if n < max(24, max_lag + 2):
        return np.nan
    centered = x - x.mean()
    gamma_0 = float(np.dot(centered, centered) / n)
    long_run_variance = gamma_0
    for lag in range(1, max_lag + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        long_run_variance += 2.0 * weight * covariance
    variance_of_mean = long_run_variance / n
    if variance_of_mean <= 0 or not np.isfinite(variance_of_mean):
        return np.nan
    return float(x.mean() / math.sqrt(variance_of_mean))


def annualized_geometric_return(returns: pd.Series) -> float:
    valid = returns.dropna().astype(float)
    if valid.empty or (1.0 + valid).le(0).any():
        return float(valid.mean() * 12.0) if not valid.empty else np.nan
    return float((1.0 + valid).prod() ** (12.0 / len(valid)) - 1.0)


def assign_quantiles(group: pd.DataFrame) -> pd.Series:
    """Rank first so tied raw values still produce stable equal-sized groups."""
    output = pd.Series(pd.NA, index=group.index, dtype="Int64")
    valid = group["oriented_factor"].notna() & group["forward_return_1m"].notna()
    if valid.sum() < 50:
        return output
    ranks = group.loc[valid, "oriented_factor"].rank(method="first")
    output.loc[valid] = pd.qcut(
        ranks, q=QUANTILES, labels=range(1, QUANTILES + 1)
    ).astype("int64")
    return output


def calculate_turnover(holdings: pd.DataFrame, quantile: int) -> pd.Series:
    selected = holdings.loc[holdings["quantile"].eq(quantile)]
    sets = selected.groupby("date")["permno"].agg(set).sort_index()
    dates = []
    turnovers = []
    previous: set[int] | None = None
    for date, current in sets.items():
        if previous is None or not current:
            turnover = np.nan
        else:
            turnover = 1.0 - len(current & previous) / len(current)
        dates.append(date)
        turnovers.append(turnover)
        previous = current
    return pd.Series(turnovers, index=pd.DatetimeIndex(dates), name="turnover")


def monthly_ic_series(data: pd.DataFrame) -> pd.Series:
    def correlation(group: pd.DataFrame) -> float:
        valid = group[["oriented_factor", "forward_return_1m"]].dropna()
        if len(valid) < 30:
            return np.nan
        factor_rank = valid["oriented_factor"].rank(method="average")
        return_rank = valid["forward_return_1m"].rank(method="average")
        return factor_rank.corr(return_rank)

    return data.groupby("date").apply(correlation, include_groups=False).rename("ic")


def evaluate_factor(
    panel: pd.DataFrame, factor: str
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    direction = FACTOR_DIRECTIONS[factor]
    data = panel[
        ["date", "permno", factor, "forward_return_1m"]
    ].copy()
    data["oriented_factor"] = data[factor] * direction
    data["quantile"] = data.groupby("date", group_keys=False).apply(
        assign_quantiles, include_groups=False
    )

    total_rows = len(data)
    usable_rows = int(
        data["oriented_factor"].notna().mul(data["forward_return_1m"].notna()).sum()
    )
    coverage = usable_rows / total_rows if total_rows else np.nan

    ic = monthly_ic_series(data)
    quantile_returns = (
        data.dropna(subset=["quantile", "forward_return_1m"])
        .groupby(["date", "quantile"])["forward_return_1m"]
        .mean()
        .unstack("quantile")
        .reindex(columns=range(1, QUANTILES + 1))
    )
    quantile_returns.columns = [f"q{column}" for column in quantile_returns.columns]
    quantile_returns["gross_spread"] = (
        quantile_returns[f"q{QUANTILES}"] - quantile_returns["q1"]
    )

    top_turnover = calculate_turnover(data, QUANTILES)
    bottom_turnover = calculate_turnover(data, 1)
    quantile_returns["top_turnover"] = top_turnover
    quantile_returns["bottom_turnover"] = bottom_turnover
    quantile_returns["net_spread"] = quantile_returns["gross_spread"] - ONE_WAY_COST * (
        quantile_returns["top_turnover"].fillna(0.0)
        + quantile_returns["bottom_turnover"].fillna(0.0)
    )

    average_quantile_returns = quantile_returns[
        [f"q{number}" for number in range(1, QUANTILES + 1)]
    ].mean()
    quantile_numbers = pd.Series(range(1, QUANTILES + 1), dtype=float)
    quantile_return_ranks = pd.Series(
        average_quantile_returns.to_numpy(), dtype=float
    ).rank(method="average")
    monotonicity = quantile_numbers.corr(quantile_return_ranks)

    subperiod_rows = []
    for name, (start, end) in SUBPERIODS.items():
        period_ic = ic.loc[start:end]
        period_spread = quantile_returns.loc[start:end, "net_spread"]
        subperiod_rows.append(
            {
                "factor": factor,
                "period": name,
                "months": int(period_ic.notna().sum()),
                "mean_ic": float(period_ic.mean()),
                "ic_hac_tstat": newey_west_mean_tstat(period_ic),
                "net_spread_ann": annualized_geometric_return(period_spread),
                "spread_hac_tstat": newey_west_mean_tstat(period_spread),
            }
        )
    subperiod = pd.DataFrame(subperiod_rows)
    positive_subperiods = int(subperiod["mean_ic"].gt(0).sum())

    mean_ic = float(ic.mean())
    ic_std = float(ic.std())
    icir = mean_ic / ic_std * math.sqrt(12.0) if ic_std > 0 else np.nan
    ic_tstat = newey_west_mean_tstat(ic)
    gross_spread_ann = annualized_geometric_return(quantile_returns["gross_spread"])
    net_spread_ann = annualized_geometric_return(quantile_returns["net_spread"])
    spread_tstat = newey_west_mean_tstat(quantile_returns["net_spread"])

    criteria = {
        "enough_data": coverage >= 0.70 and ic.notna().sum() >= 120,
        "meaningful_ic": mean_ic >= 0.02,
        "significant_ic": pd.notna(ic_tstat) and ic_tstat >= 2.0,
        "positive_net_spread": pd.notna(net_spread_ann) and net_spread_ann > 0,
        "significant_spread": pd.notna(spread_tstat) and spread_tstat >= 1.5,
        "monotonic_quantiles": pd.notna(monotonicity) and monotonicity >= 0.60,
        "subperiod_stability": positive_subperiods >= 2,
    }
    criteria_passed = int(sum(criteria.values()))
    if all(criteria.values()):
        verdict = "PASS"
    elif criteria["enough_data"] and criteria_passed >= 4:
        verdict = "MIXED"
    else:
        verdict = "FAIL"

    summary = {
        "factor": factor,
        "expected_direction": "higher_is_better"
        if direction == 1
        else "lower_is_better",
        "verdict": verdict,
        "criteria_passed": criteria_passed,
        "criteria_total": len(criteria),
        "coverage": coverage,
        "months": int(ic.notna().sum()),
        "mean_ic": mean_ic,
        "ic_std": ic_std,
        "icir_annualized": icir,
        "ic_hac_tstat": ic_tstat,
        "ic_positive_month_ratio": float(ic.gt(0).mean()),
        "quantile_monotonicity": float(monotonicity),
        "gross_spread_ann": gross_spread_ann,
        "net_spread_ann_after_10bp": net_spread_ann,
        "spread_hac_tstat": spread_tstat,
        "average_top_turnover": float(quantile_returns["top_turnover"].mean()),
        "average_bottom_turnover": float(
            quantile_returns["bottom_turnover"].mean()
        ),
        "positive_ic_subperiods": positive_subperiods,
        **{f"criterion_{key}": value for key, value in criteria.items()},
    }

    monthly_ic = ic.reset_index()
    monthly_ic.insert(0, "factor", factor)
    quantile_output = quantile_returns.reset_index()
    quantile_output.insert(0, "factor", factor)
    return summary, monthly_ic, quantile_output, subperiod


def save_plot(
    factor: str, monthly_ic: pd.DataFrame, quantile_returns: pd.DataFrame
) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)
    ic = monthly_ic.set_index("date")["ic"]
    axes[0].plot(ic.index, ic.rolling(12, min_periods=6).mean(), color="#1769aa")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title(f"{factor}: rolling 12-month Rank IC")
    axes[0].set_ylabel("Rank IC")
    axes[0].grid(alpha=0.25)

    returns = quantile_returns.set_index("date")
    for quantile in range(1, QUANTILES + 1):
        wealth = (1.0 + returns[f"q{quantile}"].fillna(0.0)).cumprod()
        axes[1].plot(wealth.index, wealth, label=f"Q{quantile}")
    axes[1].set_yscale("log")
    axes[1].set_title("Equal-weighted quantile portfolios (log scale)")
    axes[1].set_ylabel("Growth of 1")
    axes[1].grid(alpha=0.25)
    axes[1].legend(ncol=5)
    figure.savefig(OUTPUT_DIR / f"{factor}_diagnostics.png", dpi=160)
    plt.close(figure)


def write_markdown_report(
    summary: pd.DataFrame, selected: list[str], all_mode: bool = False
) -> None:
    lines = [
        "# Single-Factor Validation Report",
        "",
        f"* Mode: `{'all factors' if all_mode else 'seeded selection'}`",
        f"* Random seed: `{RANDOM_SEED}`",
        f"* Factors: `{', '.join(selected)}`",
        f"* Transaction-cost assumption: `{ONE_WAY_COST:.2%}` one way",
        "* Returns use the next-month target already stored in the point-in-time panel.",
        "",
        "## Verdicts",
        "",
    ]
    for row in summary.itertuples(index=False):
        lines.extend(
            [
                f"### {row.factor}: {row.verdict}",
                "",
                f"* Coverage: {row.coverage:.1%}",
                f"* Mean Rank IC: {row.mean_ic:.4f}",
                f"* Newey-West IC t-stat: {row.ic_hac_tstat:.2f}",
                f"* Annualized ICIR: {row.icir_annualized:.2f}",
                f"* Quantile monotonicity: {row.quantile_monotonicity:.2f}",
                f"* Net Q5-Q1 annual return: {row.net_spread_ann_after_10bp:.2%}",
                f"* Newey-West spread t-stat: {row.spread_hac_tstat:.2f}",
                f"* Criteria passed: {row.criteria_passed}/{row.criteria_total}",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "`PASS` requires every predeclared data, IC, spread, monotonicity and "
            "stability criterion. `MIXED` means the factor has some useful evidence "
            "but should not enter the final model without further robustness checks. "
            "`FAIL` means the expected direction is not sufficiently supported.",
            "",
            "The tests diagnose association, not causality. Multiple-testing control, "
            "sector neutralization and a fully locked out-of-sample portfolio test "
            "remain necessary before a production conclusion.",
        ]
    )
    (OUTPUT_DIR / "single_factor_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def detector_self_check(panel: pd.DataFrame) -> pd.DataFrame:
    """Verify that the detector rejects noise and accepts an obvious signal.

    The positive control deliberately contains future information and is used
    only as a software test fixture. It is never a candidate investment factor.
    """
    test_panel = panel.copy()
    generator = np.random.default_rng(RANDOM_SEED)
    test_panel["_negative_control_random_noise"] = generator.normal(
        size=len(test_panel)
    )
    test_panel["_positive_control_future_return"] = test_panel[
        "forward_return_1m"
    ]
    controls = {
        "_negative_control_random_noise": "FAIL",
        "_positive_control_future_return": "PASS",
    }
    rows = []
    for factor, expected_verdict in controls.items():
        FACTOR_DIRECTIONS[factor] = 1
        summary, _, _, _ = evaluate_factor(test_panel, factor)
        rows.append(
            {
                "control": factor,
                "expected_verdict": expected_verdict,
                "actual_verdict": summary["verdict"],
                "self_check_passed": summary["verdict"] == expected_verdict,
                "mean_ic": summary["mean_ic"],
                "ic_hac_tstat": summary["ic_hac_tstat"],
                "net_spread_ann": summary["net_spread_ann_after_10bp"],
            }
        )
        FACTOR_DIRECTIONS.pop(factor, None)
    return pd.DataFrame(rows)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--factors",
        nargs="*",
        choices=sorted(FACTOR_DIRECTIONS),
        help="Optional explicit factors; default is three seeded random factors.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Test every available raw factor instead of sampling three.",
    )
    parser.add_argument(
        "--skip-plots",
        action="store_true",
        help="Skip diagnostic PNG generation for faster batch runs.",
    )
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    return parser.parse_args()


def add_multiple_testing_results(summary: pd.DataFrame) -> pd.DataFrame:
    """Add two-sided normal p-values and Benjamini-Hochberg q-values."""
    result = summary.copy()
    result["ic_pvalue_approx"] = result["ic_hac_tstat"].apply(
        lambda value: math.erfc(abs(value) / math.sqrt(2.0))
        if pd.notna(value)
        else np.nan
    )
    valid = result["ic_pvalue_approx"].dropna().sort_values()
    count = len(valid)
    adjusted = pd.Series(np.nan, index=result.index, dtype=float)
    if count:
        raw_adjusted = valid.to_numpy() * count / np.arange(1, count + 1)
        monotone = np.minimum.accumulate(raw_adjusted[::-1])[::-1]
        adjusted.loc[valid.index] = np.clip(monotone, 0.0, 1.0)
    result["ic_fdr_qvalue"] = adjusted
    result["fdr_significant_5pct"] = result["ic_fdr_qvalue"].lt(0.05)
    result["final_screen"] = np.select(
        [
            result["verdict"].eq("PASS") & result["fdr_significant_5pct"],
            result["verdict"].isin(["PASS", "MIXED"]),
        ],
        ["SELECT", "WATCH"],
        default="REJECT",
    )
    return result


def main() -> None:
    global OUTPUT_DIR
    arguments = parse_arguments()
    if arguments.all:
        OUTPUT_DIR = Path("factor_tests_all")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(DATABASE)
    panel["date"] = pd.to_datetime(panel["date"])

    available = [
        factor for factor in FACTOR_DIRECTIONS if factor in panel.columns
    ]
    if arguments.all:
        selected = available
    elif arguments.factors:
        selected = arguments.factors
    else:
        selected = random.Random(arguments.seed).sample(available, 3)

    summaries = []
    monthly_ic_frames = []
    quantile_frames = []
    subperiod_frames = []
    for factor in selected:
        summary, monthly_ic, quantile_returns, subperiod = evaluate_factor(
            panel, factor
        )
        summaries.append(summary)
        monthly_ic_frames.append(monthly_ic)
        quantile_frames.append(quantile_returns)
        subperiod_frames.append(subperiod)
        if not arguments.skip_plots:
            save_plot(factor, monthly_ic, quantile_returns)

    summary_frame = add_multiple_testing_results(pd.DataFrame(summaries))
    monthly_ic_frame = pd.concat(monthly_ic_frames, ignore_index=True)
    quantile_frame = pd.concat(quantile_frames, ignore_index=True)
    subperiod_frame = pd.concat(subperiod_frames, ignore_index=True)

    summary_frame.to_csv(OUTPUT_DIR / "factor_ic_summary.csv", index=False)
    monthly_ic_frame.to_csv(OUTPUT_DIR / "factor_monthly_ic.csv", index=False)
    quantile_frame.to_csv(
        OUTPUT_DIR / "factor_quantile_returns.csv", index=False
    )
    subperiod_frame.to_csv(
        OUTPUT_DIR / "factor_subperiod_results.csv", index=False
    )
    correlation = panel[selected].rank(method="average").corr()
    correlation.to_csv(OUTPUT_DIR / "selected_factor_correlation.csv")
    self_check = detector_self_check(panel)
    self_check.to_csv(OUTPUT_DIR / "detector_self_check.csv", index=False)
    write_markdown_report(summary_frame, selected, all_mode=arguments.all)

    metadata = {
        "database": str(DATABASE),
        "seed": arguments.seed,
        "selected_factors": selected,
        "quantiles": QUANTILES,
        "one_way_cost": ONE_WAY_COST,
    }
    (OUTPUT_DIR / "test_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    print(summary_frame.to_string(index=False))
    print("\nDetector self-check:")
    print(self_check.to_string(index=False))
    print(f"\nSaved to: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
