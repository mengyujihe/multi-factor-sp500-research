# Project Report: S&P 500 Multi-Factor Stock Selection Research

## Abstract

This project builds a point-in-time S&P 500 multi-factor stock selection research pipeline covering 2000–2024. It combines historical index membership, CRSP-style monthly price data, and Compustat-style quarterly fundamentals to construct a monthly factor database. The project then performs single-factor testing, industry and size neutralization, multiple-testing correction, validation-period portfolio selection, and a locked final historical test from 2020 to 2024.

The final locked model uses two accounting quality factors, `accruals` and `cfo_roa`, and selects the top 100 stocks monthly. The final strategy performed close to the benchmark but did not generate meaningful alpha after costs.

## Motivation

Multi-factor investing attempts to rank stocks using several economically motivated signals. Common factor categories include value, quality, profitability, momentum, size, liquidity, and investment. However, many simple factors are unstable, crowded, or weakened by transaction costs.

This project focuses on building a disciplined research process rather than maximizing backtest performance.

## Data

The project uses:

- Historical S&P 500 membership.
- CRSP-style monthly stock return and market data.
- Compustat-style quarterly fundamental data.

The final generated factor panel contains:

- 147,093 monthly stock observations.
- 300 monthly dates.
- 1,051 unique PERMNOs.
- 2000-01-31 to 2024-12-31.
- Average monthly membership coverage of approximately 98.16%.
- No detected point-in-time leakage violations in the generated audit.

## Factor Testing

The first-stage detector tests many candidate factors using Rank IC, ICIR, Newey-West t-statistics, quantile returns, turnover, transaction costs, and subperiod stability.

The stricter V2 detector then applies:

- Monthly winsorization.
- Industry neutralization.
- Size neutralization.
- FDR multiple-testing correction.
- Research-only factor selection from 2000–2014.
- Validation from 2015–2019.

The final locked candidates were:

- `accruals`
- `cfo_roa`

## Portfolio Construction

The final portfolio uses:

- 50% weight on `accruals`.
- 50% weight on `cfo_roa`.
- Top 100 stocks by composite score.
- Equal weighting.
- Maximum stock weight of 3%.
- Maximum industry weight of 25%.
- Monthly rebalancing.
- 10 bps one-way transaction cost.

## Final Test Results

Final locked historical test, 2020–2024:

| Metric | Result |
|---|---:|
| Annual return | 14.89% |
| Benchmark annual return | 14.93% |
| Annualized excess return | 0.40% |
| Information ratio | 0.07 |
| Annual volatility | 20.77% |
| Sharpe ratio | 0.72 |
| Maximum drawdown | -21.52% |
| Average monthly turnover | 11.58% |

## Interpretation

The final model did not clearly outperform the benchmark. This is not a failed project. In fact, it is a realistic result for a simple public-factor model applied to large-cap U.S. equities.

The value of the project is that it demonstrates a complete research process:

- Avoiding static-universe bias.
- Avoiding obvious look-ahead bias.
- Testing factors before combining them.
- Neutralizing industry and size effects.
- Controlling multiple testing.
- Separating research, validation, and test periods.
- Reporting inconclusive results honestly.

## Future Improvements

Possible next steps include:

- Use official CRSP S&P 500 membership and CCM links.
- Compare directly against SPY total return.
- Expand beyond S&P 500 to a broader CRSP common-stock universe.
- Add analyst estimate revisions, earnings surprise, or alternative data.
- Build a market-neutral long-short version.
- Add a formal risk model and optimizer.
- Produce a polished notebook and presentation deck.

