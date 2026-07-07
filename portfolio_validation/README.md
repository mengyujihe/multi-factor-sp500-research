# Portfolio Rule Validation

## Fixed inputs

* Factors: 50% neutralized Accruals + 50% neutralized CFO/ROA.
* Validation period: 2015-2019 only.
* Portfolio sizes compared: 30, 50 and 100.
* Weighting: equal weight.
* Maximum SIC-division weight: 25%.
* Maximum single-stock weight: 3%.
* Rebalancing: monthly.
* One-way transaction cost: 10 basis points.
* Turnover compares new target weights with prior drifted weights.

## Result

| Stocks | Net CAGR | Sharpe | Max drawdown | Avg turnover |
|---:|---:|---:|---:|---:|
| 30 | 9.45% | 0.67 | -20.97% | 17.58% |
| 50 | 10.12% | 0.76 | -17.42% | 15.50% |
| 100 | 10.94% | 0.84 | -15.52% | 12.45% |

The approximate capitalization-weighted universe benchmark returned 12.36%
annualized during the same validation period. All three variants therefore
underperformed the benchmark.

The pre-registered selection rule chose 100 stocks because it had the highest
net Sharpe, lowest turnover, smallest drawdown and greatest diversification.
This is a risk-adjusted rule selection, not evidence that the strategy will
outperform SPY.

## Audit

* Missing holding-return anomalies: 0.
* Duplicate holdings: 0.
* Industry-cap breaches: 0.
* Portfolio weights sum to 100% in every validation month.
* V2 final test has not been executed.

## Locked rule file

`locked_portfolio_rules.json` contains the complete rule set and configuration
hash. The rules must not change after viewing the 2020-2024 final result.
