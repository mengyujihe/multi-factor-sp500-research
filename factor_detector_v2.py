"""V2 factor detector with neutralization and locked sample boundaries.

Workflow
--------
1. Orient every factor using predeclared economic logic.
2. Winsorize monthly at the 1st/99th percentiles.
3. Neutralize monthly with SIC 2-digit industry dummies and log market cap.
4. Standardize regression residuals.
5. Select factors using only 2000-2014.
6. Apply FDR control and remove highly correlated candidates.
7. Validate the frozen candidates on 2015-2019.
8. Write a locked manifest. This program does NOT evaluate 2020-2024.

The 2020-2024 period is intentionally inaccessible from the evaluation
functions in this file. A separate, explicit final-test program will be needed.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from run_single_factor_tests import (
    FACTOR_DIRECTIONS,
    ONE_WAY_COST,
    QUANTILES,
    annualized_geometric_return,
    assign_quantiles,
    calculate_turnover,
    monthly_ic_series,
    newey_west_mean_tstat,
)


DATABASE = Path(
    "factor_database/final/sp500_monthly_factor_panel_2000_2024.parquet"
)
OUTPUT_DIR = Path("factor_detector_v2")
NEUTRALIZED_FILE = OUTPUT_DIR / "neutralized_factor_panel.parquet"

RESEARCH_START = pd.Timestamp("2000-01-01")
RESEARCH_END = pd.Timestamp("2014-12-31")
VALIDATION_START = pd.Timestamp("2015-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_TEST_START = pd.Timestamp("2020-01-01")
LOCKED_TEST_END = pd.Timestamp("2024-12-31")

WINSOR_LOWER = 0.01
WINSOR_UPPER = 0.99
MIN_CROSS_SECTION = 50
MIN_INDUSTRY_COUNT = 5
CORRELATION_THRESHOLD = 0.70

RESEARCH_THRESHOLDS = {
    "minimum_coverage": 0.70,
    "minimum_months": 120,
    "minimum_mean_ic": 0.02,
    "minimum_ic_hac_tstat": 2.0,
    "minimum_net_spread_ann": 0.0,
    "minimum_spread_hac_tstat": 1.5,
    "minimum_quantile_monotonicity": 0.60,
    "minimum_positive_internal_periods": 2,
    "fdr_qvalue_for_select": 0.10,
    "fdr_qvalue_for_watch": 0.25,
    "minimum_watch_criteria": 5,
}

VALIDATION_THRESHOLDS = {
    "minimum_mean_ic": 0.0,
    "minimum_net_spread_ann": 0.0,
    "minimum_quantile_monotonicity": 0.40,
    "minimum_positive_month_ratio": 0.50,
    "minimum_conditions_passed": 3,
}

RESEARCH_INTERNAL_PERIODS = {
    "research_2000_2004": ("2000-01-01", "2004-12-31"),
    "research_2005_2009": ("2005-01-01", "2009-12-31"),
    "research_2010_2014": ("2010-01-01", "2014-12-31"),
}


def sic_two_digit(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    output = (numeric // 100).astype("Int64").astype("string")
    return output.fillna("UNKNOWN")


def winsorize(values: pd.Series) -> pd.Series:
    valid = values.dropna()
    if len(valid) < MIN_CROSS_SECTION:
        return pd.Series(np.nan, index=values.index)
    lower, upper = valid.quantile([WINSOR_LOWER, WINSOR_UPPER])
    return values.clip(lower, upper)


def neutralize_cross_section(
    group: pd.DataFrame,
    factor: str,
    include_size_control: bool,
) -> pd.Series:
    """Return standardized residual exposure for one month and one factor."""
    output = pd.Series(np.nan, index=group.index, dtype=float)
    oriented = group[factor] * FACTOR_DIRECTIONS[factor]
    oriented = winsorize(oriented)

    valid = oriented.notna() & group["industry2"].notna()
    if include_size_control:
        valid &= group["log_market_cap"].notna()
    if valid.sum() < MIN_CROSS_SECTION:
        return output

    sample = group.loc[valid, ["industry2", "log_market_cap"]].copy()
    y = oriented.loc[valid].astype(float)

    counts = sample["industry2"].value_counts()
    rare = counts[counts < MIN_INDUSTRY_COUNT].index
    sample.loc[sample["industry2"].isin(rare), "industry2"] = "OTHER"

    industry_dummies = pd.get_dummies(
        sample["industry2"], prefix="sic2", drop_first=True, dtype=float
    )
    design_parts = [
        pd.Series(1.0, index=sample.index, name="intercept"),
        industry_dummies,
    ]
    if include_size_control:
        size = sample["log_market_cap"].astype(float)
        size_std = size.std()
        if pd.notna(size_std) and size_std > 1e-12:
            size = (size - size.mean()) / size_std
            design_parts.insert(1, size.rename("log_market_cap"))

    design = pd.concat(design_parts, axis=1).astype(float)
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(
            design.to_numpy(), y.to_numpy(), rcond=None
        )
    except np.linalg.LinAlgError:
        return output
    if rank < 2:
        return output

    residual = y - design.to_numpy().dot(coefficients)
    residual = pd.Series(residual, index=y.index)
    residual_std = residual.std()
    if pd.isna(residual_std) or residual_std <= 1e-12:
        return output
    output.loc[valid] = (residual - residual.mean()) / residual_std
    return output


def build_neutralized_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Build exposures without using future returns or test-period outcomes."""
    identifiers = [
        "date",
        "permno",
        "ticker",
        "membership_code",
        "siccd",
        "log_market_cap",
        "forward_return_1m",
    ]
    output = panel[identifiers].copy()
    output["industry2"] = sic_two_digit(output["siccd"])

    for factor in FACTOR_DIRECTIONS:
        include_size = factor != "log_market_cap"
        neutral_column = f"{factor}_neutral"
        output[neutral_column] = panel.assign(
            industry2=output["industry2"]
        ).groupby("date", group_keys=False).apply(
            lambda group: neutralize_cross_section(
                group, factor=factor, include_size_control=include_size
            ),
            include_groups=False,
        )
    return output.sort_values(["date", "permno"]).reset_index(drop=True)


def evaluate_period(
    neutralized: pd.DataFrame,
    factor: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[dict, pd.Series, pd.DataFrame]:
    column = f"{factor}_neutral"
    data = neutralized.loc[
        neutralized["date"].between(start, end),
        ["date", "permno", column, "forward_return_1m"],
    ].rename(columns={column: "oriented_factor"})
    data["quantile"] = data.groupby("date", group_keys=False).apply(
        assign_quantiles, include_groups=False
    )

    coverage = float(
        (
            data["oriented_factor"].notna()
            & data["forward_return_1m"].notna()
        ).mean()
    )
    ic = monthly_ic_series(data)
    quantile_returns = (
        data.dropna(subset=["quantile", "forward_return_1m"])
        .groupby(["date", "quantile"])["forward_return_1m"]
        .mean()
        .unstack("quantile")
        .reindex(columns=range(1, QUANTILES + 1))
    )
    quantile_returns.columns = [
        f"q{number}" for number in range(1, QUANTILES + 1)
    ]
    quantile_returns["gross_spread"] = (
        quantile_returns[f"q{QUANTILES}"] - quantile_returns["q1"]
    )
    quantile_returns["top_turnover"] = calculate_turnover(data, QUANTILES)
    quantile_returns["bottom_turnover"] = calculate_turnover(data, 1)
    quantile_returns["net_spread"] = quantile_returns["gross_spread"] - ONE_WAY_COST * (
        quantile_returns["top_turnover"].fillna(0.0)
        + quantile_returns["bottom_turnover"].fillna(0.0)
    )

    average_q = quantile_returns[
        [f"q{number}" for number in range(1, QUANTILES + 1)]
    ].mean()
    monotonicity = pd.Series(range(1, QUANTILES + 1), dtype=float).corr(
        pd.Series(average_q.to_numpy(), dtype=float).rank(method="average")
    )
    metrics = {
        "factor": factor,
        "start": str(start.date()),
        "end": str(end.date()),
        "coverage": coverage,
        "months": int(ic.notna().sum()),
        "mean_ic": float(ic.mean()),
        "ic_std": float(ic.std()),
        "icir_annualized": float(
            ic.mean() / ic.std() * math.sqrt(12.0)
        )
        if ic.std() > 0
        else np.nan,
        "ic_hac_tstat": newey_west_mean_tstat(ic),
        "ic_positive_month_ratio": float(ic.gt(0).mean()),
        "quantile_monotonicity": float(monotonicity),
        "gross_spread_ann": annualized_geometric_return(
            quantile_returns["gross_spread"]
        ),
        "net_spread_ann": annualized_geometric_return(
            quantile_returns["net_spread"]
        ),
        "spread_hac_tstat": newey_west_mean_tstat(
            quantile_returns["net_spread"]
        ),
        "average_top_turnover": float(
            quantile_returns["top_turnover"].mean()
        ),
        "average_bottom_turnover": float(
            quantile_returns["bottom_turnover"].mean()
        ),
    }
    return metrics, ic, quantile_returns


def add_fdr(results: pd.DataFrame) -> pd.DataFrame:
    output = results.copy()
    output["ic_pvalue_approx"] = output["ic_hac_tstat"].apply(
        lambda value: math.erfc(abs(value) / math.sqrt(2.0))
        if pd.notna(value)
        else np.nan
    )
    valid = output["ic_pvalue_approx"].dropna().sort_values()
    qvalues = pd.Series(np.nan, index=output.index, dtype=float)
    count = len(valid)
    if count:
        raw = valid.to_numpy() * count / np.arange(1, count + 1)
        adjusted = np.minimum.accumulate(raw[::-1])[::-1]
        qvalues.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    output["ic_fdr_qvalue"] = qvalues
    return output


def research_screen(
    neutralized: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    internal_rows = []
    for factor in FACTOR_DIRECTIONS:
        metrics, _, _ = evaluate_period(
            neutralized, factor, RESEARCH_START, RESEARCH_END
        )
        positive_internal_periods = 0
        for period_name, (start, end) in RESEARCH_INTERNAL_PERIODS.items():
            internal, _, _ = evaluate_period(
                neutralized,
                factor,
                pd.Timestamp(start),
                pd.Timestamp(end),
            )
            internal["period"] = period_name
            internal_rows.append(internal)
            positive_internal_periods += internal["mean_ic"] > 0

        criteria = {
            "enough_data": metrics["coverage"]
            >= RESEARCH_THRESHOLDS["minimum_coverage"]
            and metrics["months"] >= RESEARCH_THRESHOLDS["minimum_months"],
            "meaningful_ic": metrics["mean_ic"]
            >= RESEARCH_THRESHOLDS["minimum_mean_ic"],
            "significant_ic": metrics["ic_hac_tstat"]
            >= RESEARCH_THRESHOLDS["minimum_ic_hac_tstat"],
            "positive_net_spread": metrics["net_spread_ann"]
            > RESEARCH_THRESHOLDS["minimum_net_spread_ann"],
            "significant_spread": metrics["spread_hac_tstat"]
            >= RESEARCH_THRESHOLDS["minimum_spread_hac_tstat"],
            "monotonic_quantiles": metrics["quantile_monotonicity"]
            >= RESEARCH_THRESHOLDS["minimum_quantile_monotonicity"],
            "internal_stability": positive_internal_periods
            >= RESEARCH_THRESHOLDS["minimum_positive_internal_periods"],
        }
        metrics["positive_internal_periods"] = positive_internal_periods
        metrics["criteria_passed"] = int(sum(criteria.values()))
        metrics.update({f"criterion_{key}": value for key, value in criteria.items()})
        rows.append(metrics)

    results = add_fdr(pd.DataFrame(rows))
    results["research_decision"] = np.select(
        [
            results["criteria_passed"].eq(7)
            & results["ic_fdr_qvalue"].le(
                RESEARCH_THRESHOLDS["fdr_qvalue_for_select"]
            ),
            results["criteria_passed"].ge(
                RESEARCH_THRESHOLDS["minimum_watch_criteria"]
            )
            & results["ic_fdr_qvalue"].le(
                RESEARCH_THRESHOLDS["fdr_qvalue_for_watch"]
            ),
        ],
        ["SELECT", "WATCH"],
        default="REJECT",
    )
    return results, pd.DataFrame(internal_rows)


def average_monthly_factor_correlation(
    neutralized: pd.DataFrame, factors: list[str]
) -> pd.DataFrame:
    columns = [f"{factor}_neutral" for factor in factors]
    research = neutralized.loc[
        neutralized["date"].between(RESEARCH_START, RESEARCH_END),
        ["date", *columns],
    ]
    matrices = []
    for _, group in research.groupby("date"):
        matrices.append(group[columns].corr(method="pearson").to_numpy())
    average = np.nanmean(np.stack(matrices), axis=0)
    return pd.DataFrame(average, index=factors, columns=factors)


def connected_components(
    correlation: pd.DataFrame, threshold: float
) -> list[list[str]]:
    remaining = set(correlation.index)
    components = []
    while remaining:
        start = remaining.pop()
        component = {start}
        frontier = [start]
        while frontier:
            current = frontier.pop()
            neighbors = set(
                correlation.columns[
                    correlation.loc[current].abs().ge(threshold)
                ]
            )
            neighbors.discard(current)
            new_neighbors = neighbors & remaining
            remaining -= new_neighbors
            component |= new_neighbors
            frontier.extend(new_neighbors)
        components.append(sorted(component))
    return sorted(components, key=lambda values: values[0])


def remove_redundancy(
    neutralized: pd.DataFrame, research: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = research.loc[
        research["research_decision"].isin(["SELECT", "WATCH"]), "factor"
    ].tolist()
    if not candidates:
        return pd.DataFrame(), pd.DataFrame()
    correlation = average_monthly_factor_correlation(neutralized, candidates)
    components = connected_components(correlation, CORRELATION_THRESHOLD)

    rows = []
    for cluster_id, factors in enumerate(components, start=1):
        ranking = research.loc[research["factor"].isin(factors)].sort_values(
            ["research_decision", "criteria_passed", "ic_hac_tstat", "coverage"],
            ascending=[True, False, False, False],
        )
        representative = ranking.iloc[0]["factor"]
        for factor in factors:
            rows.append(
                {
                    "cluster_id": cluster_id,
                    "factor": factor,
                    "representative": representative,
                    "kept": factor == representative,
                    "cluster_size": len(factors),
                }
            )
    return pd.DataFrame(rows), correlation


def validate_candidates(
    neutralized: pd.DataFrame,
    clusters: pd.DataFrame,
) -> pd.DataFrame:
    if clusters.empty:
        return pd.DataFrame()
    representatives = clusters.loc[clusters["kept"], "factor"].tolist()
    rows = []
    for factor in representatives:
        metrics, _, _ = evaluate_period(
            neutralized, factor, VALIDATION_START, VALIDATION_END
        )
        conditions = {
            "positive_ic": metrics["mean_ic"]
            > VALIDATION_THRESHOLDS["minimum_mean_ic"],
            "positive_net_spread": metrics["net_spread_ann"]
            > VALIDATION_THRESHOLDS["minimum_net_spread_ann"],
            "monotonic_quantiles": metrics["quantile_monotonicity"]
            >= VALIDATION_THRESHOLDS["minimum_quantile_monotonicity"],
            "positive_month_ratio": metrics["ic_positive_month_ratio"]
            >= VALIDATION_THRESHOLDS["minimum_positive_month_ratio"],
        }
        metrics["validation_conditions_passed"] = int(sum(conditions.values()))
        metrics["validation_decision"] = (
            "PASS"
            if metrics["validation_conditions_passed"]
            >= VALIDATION_THRESHOLDS["minimum_conditions_passed"]
            else "FAIL"
        )
        metrics.update(
            {f"condition_{key}": value for key, value in conditions.items()}
        )
        rows.append(metrics)
    return pd.DataFrame(rows)


def build_lock_manifest(
    research: pd.DataFrame,
    clusters: pd.DataFrame,
    validation: pd.DataFrame,
) -> dict:
    if validation.empty:
        final_candidates: list[str] = []
    else:
        final_candidates = validation.loc[
            validation["validation_decision"].eq("PASS"), "factor"
        ].tolist()
    manifest = {
        "version": "2.0",
        "status": "LOCKED_BEFORE_FINAL_TEST",
        "research_period": ["2000-01-01", "2014-12-31"],
        "validation_period": ["2015-01-01", "2019-12-31"],
        "locked_test_period": ["2020-01-01", "2024-12-31"],
        "test_period_previously_inspected_in_v1_diagnostics": True,
        "neutralization": {
            "winsorization": [WINSOR_LOWER, WINSOR_UPPER],
            "industry": "monthly SIC two-digit dummy regression",
            "size": "monthly log market cap regression",
            "minimum_cross_section": MIN_CROSS_SECTION,
            "minimum_industry_count": MIN_INDUSTRY_COUNT,
            "exception": "log_market_cap is industry-neutralized but not size-neutralized",
        },
        "research_thresholds": RESEARCH_THRESHOLDS,
        "validation_thresholds": VALIDATION_THRESHOLDS,
        "redundancy_correlation_threshold": CORRELATION_THRESHOLD,
        "research_selected_or_watch": research.loc[
            research["research_decision"].isin(["SELECT", "WATCH"]), "factor"
        ].tolist(),
        "representatives_after_redundancy": clusters.loc[
            clusters.get("kept", pd.Series(dtype=bool)).eq(True), "factor"
        ].tolist()
        if not clusters.empty
        else [],
        "final_locked_candidates": final_candidates,
        "final_test_has_been_run_by_v2": False,
    }
    canonical = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    manifest["configuration_sha256"] = hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return manifest


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(DATABASE)
    panel["date"] = pd.to_datetime(panel["date"])

    print("1/5 Building neutralized factor exposures...")
    neutralized = build_neutralized_panel(panel)
    neutralized.to_parquet(NEUTRALIZED_FILE, index=False)

    print("2/5 Screening factors on 2000-2014 only...")
    research, internal = research_screen(neutralized)
    research.to_csv(OUTPUT_DIR / "research_screen_2000_2014.csv", index=False)
    internal.to_csv(OUTPUT_DIR / "research_internal_stability.csv", index=False)

    print("3/5 Removing correlated candidates...")
    clusters, correlation = remove_redundancy(neutralized, research)
    clusters.to_csv(OUTPUT_DIR / "redundancy_clusters.csv", index=False)
    correlation.to_csv(OUTPUT_DIR / "candidate_factor_correlation.csv")

    print("4/5 Validating frozen representatives on 2015-2019...")
    validation = validate_candidates(neutralized, clusters)
    validation.to_csv(OUTPUT_DIR / "validation_2015_2019.csv", index=False)

    print("5/5 Locking configuration; 2020-2024 is NOT evaluated...")
    manifest = build_lock_manifest(research, clusters, validation)
    (OUTPUT_DIR / "locked_model_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\nResearch decisions:")
    print(
        research.sort_values(
            ["research_decision", "criteria_passed", "mean_ic"],
            ascending=[True, False, False],
        )[
            [
                "factor",
                "research_decision",
                "criteria_passed",
                "mean_ic",
                "ic_hac_tstat",
                "ic_fdr_qvalue",
                "net_spread_ann",
            ]
        ].to_string(index=False)
    )
    print("\nValidation:")
    print(
        validation[
            [
                "factor",
                "validation_decision",
                "validation_conditions_passed",
                "mean_ic",
                "net_spread_ann",
            ]
        ].to_string(index=False)
        if not validation.empty
        else "No candidates reached validation."
    )
    print("\nLocked candidates:", manifest["final_locked_candidates"])
    print("Final test executed by V2: False")
    print("Output:", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
