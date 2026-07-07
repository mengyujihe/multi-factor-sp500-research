# Methodology

## 1. Objective

The objective of this project is to build a disciplined multi-factor stock selection research pipeline for the S&P 500. The project focuses on research quality rather than production trading.

The central question is:

> Can a small set of accounting and quality factors generate robust stock-selection ability inside the historical S&P 500 universe?

## 2. Universe Construction

The investment universe is based on historical S&P 500 membership from 2000 to 2024. This matters because using only today's S&P 500 constituents would introduce survivorship bias: failed, merged, or removed companies would disappear from the historical test.

Each month, the model uses the stocks that were members of the S&P 500 at that time, then matches them to available CRSP-style price data and Compustat-style fundamental data.

## 3. Point-in-Time Data Principle

The database is designed to avoid look-ahead bias. Fundamental data is only used after it would have been publicly available. In this project, quarterly fundamentals are aligned using report dates when available, and stale fundamental observations are excluded.

This is important because a model should not use financial statement information before investors could realistically know it.

## 4. Factor Construction

The project contains valuation, profitability, quality, investment, liquidity, size, and technical factors. Examples include:

- `cfo_roa`: cash flow from operations scaled by assets.
- `accruals`: accounting accruals scaled by assets.
- `ebitda_to_ev`: EBITDA to enterprise value.
- `book_to_market`: book equity relative to market equity.
- `short_reversal`: recent one-month reversal.
- `illiquidity`: return impact relative to trading volume.
- `log_market_cap`: company size.

The final locked model uses two factors:

- `accruals`
- `cfo_roa`

Economically, these are quality/accounting factors. The rough idea is that companies with stronger cash-flow quality and lower accrual intensity may have more reliable earnings.

## 5. Single-Factor Testing

Each factor is tested cross-sectionally by month. The core metric is Rank IC, which measures whether stocks with higher factor scores tend to have higher next-month returns.

The detector evaluates:

- Mean Rank IC.
- IC information ratio.
- Newey-West adjusted t-statistics.
- Quantile monotonicity.
- Top-minus-bottom return spread.
- Turnover and transaction cost impact.
- Subperiod stability.
- Multiple-testing adjusted significance.

## 6. Winsorization

Before neutralization and testing, factors are winsorized cross-sectionally by month. This limits the influence of extreme observations.

This is especially important in accounting data because ratios can become unstable when denominators are very small.

## 7. Industry and Size Neutralization

Factors are neutralized by industry and market capitalization before stricter testing.

The reason is simple: if a factor works only because it accidentally buys one industry or one size segment, it may not be a true stock-selection signal.

The V2 detector uses monthly cross-sectional regressions:

```text
factor = industry dummies + log market cap + residual
```

The residual is treated as the neutralized factor exposure.

## 8. Multiple-Testing Control

Testing many factors increases the chance of finding a false positive. To reduce this risk, the project applies FDR-style multiple-testing correction.

This does not eliminate data mining, but it makes the research process more conservative.

## 9. Research / Validation / Test Split

The time periods are split as follows:

| Period | Years | Purpose |
|---|---:|---|
| Research | 2000–2014 | Select factors and estimate rules |
| Validation | 2015–2019 | Choose among pre-specified model variants |
| Locked test | 2020–2024 | Final historical evaluation |

After the final test is run, the strategy should not be retuned and still called out-of-sample.

## 10. Portfolio Construction

The locked portfolio rules are:

- Factor weights: 50% `accruals`, 50% `cfo_roa`.
- Required data: both factors must be available.
- Portfolio size: top 100 stocks.
- Weighting: equal weight.
- Maximum single-stock weight: 3%.
- Maximum industry weight: 25%, using SIC first digit.
- Rebalance frequency: monthly.
- Signal timing: month-end signal, next-month return.
- Transaction cost: 10 bps one-way.

## 11. Final Result Interpretation

The final locked strategy performed close to the benchmark but did not show strong alpha. This is an honest and useful conclusion. In large-cap U.S. equities, simple public factors are heavily studied, crowded, and often unstable.

The main achievement of this project is the construction of a rigorous research pipeline.

