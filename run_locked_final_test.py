"""Run the locked 2020-2024 portfolio test exactly as specified in the manifest.

This script verifies the pre-test configuration hash before evaluating returns.
It does not optimize, compare variants, or modify any portfolio rule.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from validate_portfolio_rules import (
    INPUT_FILE,
    MANIFEST_FILE,
    run_variant,
    sic_division,
)


TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2024-12-31")
OUTPUT_DIR = Path("locked_final_test")


def verify_manifest_hash(manifest: dict) -> str:
    stored_hash = manifest.get("configuration_sha256")
    if not stored_hash:
        raise RuntimeError("The locked manifest has no configuration hash.")
    unhashed = dict(manifest)
    unhashed.pop("configuration_sha256", None)
    canonical = json.dumps(unhashed, sort_keys=True, ensure_ascii=False)
    calculated = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if calculated != stored_hash:
        raise RuntimeError(
            "Locked manifest hash mismatch. Refusing to run the final test."
        )
    return stored_hash


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    configuration_hash = verify_manifest_hash(manifest)

    if manifest["status"] != "PORTFOLIO_RULES_LOCKED_BEFORE_FINAL_TEST":
        raise RuntimeError("Portfolio rules are not in the expected locked state.")
    if manifest.get("final_test_has_been_run_by_v2"):
        raise RuntimeError("Manifest indicates that the V2 final test already ran.")

    target_count = int(manifest["portfolio_rules"]["portfolio_size"])
    if target_count not in (30, 50, 100):
        raise RuntimeError("Unexpected locked portfolio size.")

    panel = pd.read_parquet(INPUT_FILE)
    panel["date"] = pd.to_datetime(panel["date"])
    test = panel.loc[panel["date"].between(TEST_START, TEST_END)].copy()
    test["industry_division"] = sic_division(test["industry2"])

    returns, holdings, metrics = run_variant(test, target_count)
    returns.to_csv(OUTPUT_DIR / "final_test_monthly_returns.csv", index=False)
    holdings.to_parquet(OUTPUT_DIR / "final_test_holdings.parquet", index=False)

    results = {
        "status": "FINAL_TEST_COMPLETED_NO_RETUNING_ALLOWED",
        "configuration_sha256": configuration_hash,
        "test_period": ["2020-01-01", "2024-12-31"],
        "portfolio_size": target_count,
        "metrics": metrics,
        "important_disclosure": (
            "The 2020-2024 period was inspected in earlier V1 single-factor "
            "diagnostics before V2 was designed, so this is a locked historical "
            "test rather than a pristine never-seen holdout."
        ),
    }
    (OUTPUT_DIR / "final_test_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = f"""# Locked Final Historical Test

* Configuration hash: `{configuration_hash}`
* Signal period: 2020-01-01 to 2024-12-31
* Locked portfolio size: {target_count}
* Factors: 50% accruals, 50% CFO/ROA
* Rules were not changed after validation.

## Results

* Evaluated months: {metrics['months']}
* Net annual return: {metrics['annual_return']:.2%}
* Annual volatility: {metrics['annual_volatility']:.2%}
* Sharpe ratio (zero risk-free rate): {metrics['sharpe_zero_rf']:.2f}
* Maximum drawdown: {metrics['maximum_drawdown']:.2%}
* Positive-month ratio: {metrics['positive_month_ratio']:.2%}
* Average monthly turnover: {metrics['average_turnover']:.2%}
* Approximate cap-weighted benchmark annual return: {metrics['benchmark_annual_return']:.2%}
* Arithmetic annualized excess return: {metrics['annualized_excess_return_arithmetic']:.2%}
* Information ratio: {metrics['information_ratio']:.2f}

## Disclosure

The 2020-2024 period was inspected in earlier V1 single-factor diagnostics
before V2 was designed. This result is therefore a locked historical test, not
a pristine never-seen holdout. No rule may be retuned and re-labelled as an
out-of-sample result after viewing this report.
"""
    (OUTPUT_DIR / "final_test_report.md").write_text(report, encoding="utf-8")

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
