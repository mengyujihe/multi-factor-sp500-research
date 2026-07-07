# Data Sample

This folder can contain a tiny anonymized or synthetic sample of the factor panel for demonstration.

Do not place raw WRDS, CRSP, Compustat, or full generated Parquet datasets here.

Recommended sample format:

```text
date,permno,ticker,sector,market_cap,cfo_roa,accruals,forward_return
```

If you want the repository to be fully reproducible without licensed data, create a synthetic sample and clearly label it as synthetic.

