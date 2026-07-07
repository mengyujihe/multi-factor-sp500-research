# Resume and Interview Pitch

## One-Line Resume Bullet

Built a point-in-time S&P 500 multi-factor stock selection research system using CRSP-style monthly returns and Compustat-style fundamentals, including factor testing, industry/size neutralization, validation-period model selection, transaction costs, and locked 2020–2024 historical evaluation.

## Short Interview Explanation

I built a research pipeline for testing multi-factor stock selection strategies on the historical S&P 500 universe. The project starts by constructing a monthly point-in-time factor database from price, membership, and fundamental data. Then I test individual factors using Rank IC, quantile returns, Newey-West adjusted statistics, and transaction-cost-aware spreads. To make the factor tests stricter, I added industry and size neutralization and multiple-testing correction. Finally, I separated the project into a research period, validation period, and locked historical test period.

The final model used two accounting quality factors, accruals and cash-flow return on assets. It performed close to the benchmark from 2020 to 2024 but did not generate strong alpha. The main value of the project is that it follows a realistic quant research process and reports the result honestly.

## Longer Project Pitch

The project was designed to answer a practical research question: if I use only public-style price and accounting data, can I build a disciplined S&P 500 factor model that survives basic institutional research checks?

I learned that the hard part is not writing a backtest. The hard part is avoiding biased data, testing too many factors, accidentally using future information, and overfitting the final test period. So I focused on building the pipeline carefully:

- dynamic historical universe,
- point-in-time accounting data alignment,
- factor construction,
- single-factor testing,
- winsorization,
- industry and size neutralization,
- FDR multiple-testing correction,
- validation-based portfolio rule selection,
- transaction-cost-aware final backtest.

The final model did not meaningfully outperform the benchmark, which is actually an important finding. It showed me why simple public factors in large-cap U.S. equities are difficult to monetize, and why professional quant funds rely on broader universes, many small signals, risk models, execution systems, and proprietary data.

## Honest Limitation Statement

This was a student research project, not a production trading system. The historical S&P 500 membership source was public and ticker-based, not the official CRSP index membership table. Identifier matching was reconstructed rather than using a full institutional CCM link pipeline. Also, because the test period had been inspected in earlier exploratory diagnostics, the final test should be described as a locked historical test rather than a perfectly pristine unseen holdout.

