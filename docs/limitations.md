# Limitations and Research Disclosures

This project is a research project, not an investment product.

## 1. Data Licensing

Some raw inputs may come from WRDS, CRSP, or Compustat-style datasets. These datasets are often licensed and should not be uploaded publicly.

The public repository should include code and summary results, not restricted raw data.

## 2. Historical Membership Source

The historical S&P 500 membership data used in this project is based on a public ticker-level membership file, not the official CRSP S&P 500 membership table.

This is useful for a student project, but it is not identical to an institutional-grade index membership source.

## 3. Identifier Matching

PERMNO / GVKEY matching is reconstructed from available ticker and CUSIP-style information. A professional version would use the official CRSP/Compustat Merged database link table.

## 4. Test-Set Disclosure

The final 2020–2024 period was inspected during earlier exploratory diagnostics before the stricter V2 detector was designed. Therefore, the final test should be described as a locked historical test, not a perfectly pristine never-seen holdout.

## 5. Benchmark Approximation

The benchmark used in the internal tests is an approximate cap-weighted S&P 500-style benchmark based on the available universe. It may differ from the exact SPY total return.

## 6. Model Simplicity

The final model uses only two factors and a simple long-only portfolio rule. Professional quant funds typically use more signals, broader universes, short books, advanced risk models, execution models, and proprietary data.

## 7. No Investment Advice

This project is for education and research. It should not be used as financial advice or as a live trading system.

