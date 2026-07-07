# GitHub Upload Guide

This project contains useful code and reports, but it also contains local data files that should not be uploaded publicly. Use this checklist before publishing.

## Recommended Public Files

Upload:

- `README.md`
- `requirements.txt`
- `.gitignore`
- Main Python scripts
- `docs/`
- Small result summaries
- Small CSV / JSON reports

Do not upload:

- Raw WRDS exports
- Raw CRSP data
- Raw Compustat data
- Full Parquet factor databases
- Large holdings Parquet files
- Private school account information

## Recommended Clean Repository Workflow

Because the current folder appears to sit inside a broader local Git context, the safest upload workflow is:

1. Create a fresh folder outside the current experimental workspace.
2. Copy only the public-safe project files into that folder.
3. Run `git init` inside the fresh folder.
4. Check `git status` carefully.
5. Commit and push to GitHub.

Example:

```bash
mkdir ~/Documents/sp500-multifactor-research-public
cd ~/Documents/sp500-multifactor-research-public
git init
```

Then copy over only the safe files.

## Suggested Repository Name

Good options:

- `sp500-multifactor-research`
- `point-in-time-factor-research`
- `sp500-factor-model`
- `quant-factor-research-sp500`

My recommendation:

```text
sp500-multifactor-research
```

## Suggested GitHub Description

```text
Point-in-time S&P 500 multi-factor stock selection research with factor testing, neutralization, validation, and locked historical backtesting.
```

## Suggested Topics

```text
quantitative-finance
factor-investing
backtesting
python
pandas
sp500
portfolio-construction
financial-data
```

