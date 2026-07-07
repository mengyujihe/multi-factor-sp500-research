# Data Dictionary

This file summarizes the main datasets and fields used in the project.

## Main Factor Panel

Primary generated file:

```text
factor_database/final/sp500_monthly_factor_panel_2000_2024.parquet
```

This file is not intended to be uploaded publicly because it is large and may contain licensed data.

Expected structure:

| Field type | Description |
|---|---|
| Date | Month-end observation date |
| Identifier | PERMNO, ticker, CUSIP, GVKEY when available |
| Membership | Whether the stock was in the historical S&P 500 universe |
| Price data | Monthly returns, market cap, volume, delisting-adjusted returns when available |
| Fundamentals | Quarterly accounting fields aligned point-in-time |
| Factors | Valuation, quality, profitability, investment, liquidity, size, and technical signals |
| Forward returns | Next-month returns used for testing |

## Important Raw Inputs

The project expects three broad input groups:

1. Historical S&P 500 membership.
2. CRSP-style monthly price and return data.
3. Compustat-style quarterly fundamentals.

Raw WRDS / CRSP / Compustat data should remain local and should not be uploaded to a public GitHub repository.

## Selected Factor Definitions

| Factor | Intuition |
|---|---|
| `cfo_roa` | Cash flow from operations relative to assets; a profitability/quality signal |
| `accruals` | Accounting accruals relative to assets; lower accruals are often interpreted as higher earnings quality |
| `ebitda_to_ev` | EBITDA relative to enterprise value; a valuation signal |
| `book_to_market` | Book equity relative to market value; a value signal |
| `earnings_yield` | Earnings relative to market value |
| `sales_yield` | Sales relative to market value |
| `short_reversal` | Recent return reversal signal |
| `momentum_12_1` | Prior 12-month return excluding the most recent month |
| `volatility` | Realized return volatility |
| `illiquidity` | Price impact / liquidity proxy |
| `log_market_cap` | Company size |

## Point-in-Time Rule

Accounting data should only be used after the market could reasonably know it. The project therefore aligns quarterly fundamentals to later monthly observations and excludes stale observations.

## Data Quality Checks

The project produces audit reports including:

- Monthly membership coverage.
- Missing factor coverage.
- Unmatched membership codes.
- Duplicate date / PERMNO checks.
- Point-in-time leakage checks.

Main quality report:

```text
factor_database/reports/quality_summary.json
```

