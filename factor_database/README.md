# S&P 500 Point-in-Time Factor Database

## Main output

`final/sp500_monthly_factor_panel_2000_2024.parquet`

Each row represents one matched historical S&P 500 constituent at one CRSP
month-end. Financial statements are joined only when `available_date <= date`.

## Dimensions

* Rows: 147,093
* Months: 300
* PERMNOs: 1,051
* Date range: 2000-01-31 to 2024-12-31

## Supporting outputs

* `clean/crsp_monthly_clean.parquet`
* `clean/compustat_quarterly_clean.parquet`
* `clean/sp500_monthly_membership.parquet`
* `reports/monthly_coverage.csv`
* `reports/unmatched_membership_codes.csv`
* `reports/factor_missingness.csv`
* `reports/quality_summary.json`

## Point-in-time rules

* Valid Compustat `RDQ` is used as the availability date.
* Missing or anomalous `RDQ` falls back to `DATADATE + 90 days`.
* Fundamental values older than 180 days are marked stale and excluded from
  factor calculations.
* Quarterly cumulative cash-flow variables are converted to single-quarter
  flows before trailing-four-quarter calculations.
* Factor z-scores are winsorized at the monthly 1st/99th percentiles and
  standardized only within the matched contemporaneous S&P 500 universe.
* `forward_return_1m` is a target variable, never an input factor.

## Research limitation

The constituent file is ticker-based. The official CRSP membership table and
CCM link history were not supplied, so identifier reconstruction is approximate.
Use the coverage and unmatched-code reports when interpreting results.
