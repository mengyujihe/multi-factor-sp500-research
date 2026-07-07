# Factor Detector V2

## Purpose

This detector separates factor research, validation and final testing:

* Research: 2000-2014
* Validation: 2015-2019
* Locked historical test: 2020-2024

The V2 detector has not evaluated the locked test period. Earlier V1 diagnostic
work did inspect 2020-2024, and that limitation is disclosed in the manifest.

## Processing modules

1. Orient every factor using predeclared economic logic.
2. Winsorize each monthly cross-section at the 1st and 99th percentiles.
3. Regress each factor on SIC two-digit industry dummies and log market cap.
4. Use standardized residuals as neutralized factor exposures.
5. Screen all factors using only the research period.
6. Apply Benjamini-Hochberg FDR correction.
7. Cluster candidates whose average absolute correlation is at least 0.70.
8. Keep one research-period representative from each correlated cluster.
9. Validate the frozen representatives on 2015-2019.
10. Write a hashed lock manifest before any V2 final test.

The size factor itself is industry-neutralized but is not neutralized against
its own log-market-cap exposure.

## Research-period results

Research SELECT:

* `ebitda_to_ev`
* `illiquidity`
* `log_market_cap`

Research WATCH:

* `accruals`
* `capex_to_assets`
* `cfo_roa`
* `roe`

No pair among these seven candidates exceeded the 0.70 redundancy threshold.

## Validation results

Passed 2015-2019 validation:

* `accruals`
* `cfo_roa`

Failed validation:

* `capex_to_assets`
* `ebitda_to_ev`
* `illiquidity`
* `log_market_cap`
* `roe`

The final locked candidate list is therefore `accruals` and `cfo_roa`.

## Files

* `neutralized_factor_panel.parquet`: monthly neutralized exposures.
* `research_screen_2000_2014.csv`: research-only factor results.
* `research_internal_stability.csv`: three research subperiod checks.
* `candidate_factor_correlation.csv`: average monthly candidate correlations.
* `redundancy_clusters.csv`: cluster membership and representatives.
* `validation_2015_2019.csv`: validation results.
* `locked_model_manifest.json`: frozen rules, candidates and configuration hash.

## Next step

Before running 2020-2024, define and lock the portfolio rule for the two
surviving factors: factor weights, minimum data requirement, number of stocks,
rebalancing frequency, position weights and transaction-cost assumptions.
