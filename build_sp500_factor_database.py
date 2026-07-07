"""Build a point-in-time monthly S&P 500 factor database.

Inputs
------
* CRSP monthly stock data downloaded from WRDS.
* Compustat Fundamentals Quarterly downloaded from WRDS.
* Point-in-time S&P 500 ticker snapshots from fja05680/sp500.

Outputs
-------
* Clean CRSP and Compustat parquet files.
* A monthly point-in-time membership table.
* A model-ready monthly factor panel and quality reports.

Important limitation
--------------------
The historical constituent source uses tickers, while CRSP uses PERMNO and
Compustat uses GVKEY. Without the official CRSP constituent table and CCM link
history, identifier matching is necessarily approximate. All match methods and
unmatched codes are retained for audit.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


PRICE_CSV = Path("/Users/ericyang/Downloads/sp500_price.csv")
FUNDAMENTALS_CSV = Path("/Users/ericyang/Downloads/sp500_fundamentals.csv")
MEMBERSHIP_CSV = Path(
    "/Users/ericyang/Downloads/"
    "S&P 500 Historical Components & Changes (Updated).csv"
)

START_DATE = pd.Timestamp("2000-01-01")
END_DATE = pd.Timestamp("2024-12-31")
OUTPUT_DIR = Path("factor_database")
CLEAN_DIR = OUTPUT_DIR / "clean"
FINAL_DIR = OUTPUT_DIR / "final"
REPORT_DIR = OUTPUT_DIR / "reports"


def safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.where(denominator.abs() > 1e-12)
    result = numerator / denominator
    return result.replace([np.inf, -np.inf], np.nan)


def normalize_ticker(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().str.upper()


def normalize_cusip8(values: pd.Series) -> pd.Series:
    return (
        values.fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
        .str[:8]
    )


def compound_return(values: pd.Series) -> float:
    valid = values.dropna()
    if valid.empty:
        return np.nan
    return float(np.prod(1.0 + valid) - 1.0)


def clean_price_data() -> pd.DataFrame:
    price = pd.read_csv(PRICE_CSV, low_memory=False)
    price.columns = price.columns.str.lower()
    price["date"] = pd.to_datetime(price["date"], errors="coerce")

    numeric_columns = [
        "permno",
        "shrcd",
        "exchcd",
        "dlstcd",
        "dlret",
        "prc",
        "vol",
        "ret",
        "shrout",
        "cfacpr",
        "cfacshr",
        "retx",
    ]
    for column in numeric_columns:
        price[column] = pd.to_numeric(price[column], errors="coerce")

    price["ticker"] = normalize_ticker(price["ticker"])
    price["ncusip8"] = normalize_cusip8(price["ncusip"])
    price["header_cusip8"] = normalize_cusip8(price["cusip"])
    price["cusip8"] = price["ncusip8"].where(
        price["ncusip8"].ne(""), price["header_cusip8"]
    )

    price = price.dropna(subset=["permno", "date"]).copy()
    price["permno"] = price["permno"].astype("int64")
    price = price.sort_values(["permno", "date"])
    price = price.drop_duplicates(["permno", "date"], keep="last")

    price["price"] = price["prc"].abs()
    price["market_cap_m"] = price["price"] * price["shrout"] / 1000.0
    price["dollar_volume_m"] = price["price"] * price["vol"] / 1_000_000.0

    # CRSP delisting return is combined with the regular return where present.
    price["total_ret"] = price["ret"]
    both = price["ret"].notna() & price["dlret"].notna()
    price.loc[both, "total_ret"] = (
        (1.0 + price.loc[both, "ret"]) * (1.0 + price.loc[both, "dlret"]) - 1.0
    )
    only_delist = price["ret"].isna() & price["dlret"].notna()
    price.loc[only_delist, "total_ret"] = price.loc[only_delist, "dlret"]

    grouped = price.groupby("permno", group_keys=False)
    price["momentum_12_1"] = grouped["total_ret"].transform(
        lambda x: (1.0 + x.shift(1)).rolling(11, min_periods=9).apply(np.prod, raw=True)
        - 1.0
    )
    price["momentum_6_1"] = grouped["total_ret"].transform(
        lambda x: (1.0 + x.shift(1)).rolling(5, min_periods=4).apply(np.prod, raw=True)
        - 1.0
    )
    price["short_reversal"] = -price["total_ret"]
    price["volatility_12m"] = grouped["total_ret"].transform(
        lambda x: x.shift(1).rolling(12, min_periods=9).std() * np.sqrt(12.0)
    )
    price["turnover"] = safe_div(price["vol"], price["shrout"])
    price["illiquidity"] = safe_div(
        price["total_ret"].abs(), price["dollar_volume_m"].abs()
    )
    price["log_market_cap"] = np.log(
        price["market_cap_m"].where(price["market_cap_m"] > 0)
    )

    distribution_ret = safe_div(1.0 + price["ret"], 1.0 + price["retx"]) - 1.0
    price["dividend_yield_12m"] = distribution_ret.groupby(price["permno"]).transform(
        lambda x: (1.0 + x).rolling(12, min_periods=9).apply(np.prod, raw=True) - 1.0
    )

    next_date = grouped["date"].shift(-1)
    next_ret = grouped["total_ret"].shift(-1)
    consecutive = (
        next_date.dt.to_period("M").astype("int64")
        - price["date"].dt.to_period("M").astype("int64")
    ) == 1
    price["forward_return_1m"] = next_ret.where(consecutive)
    return price.reset_index(drop=True)


def quarterize_ytd(
    fundamentals: pd.DataFrame, column: str, output_column: str
) -> None:
    previous = fundamentals.groupby(["gvkey", "fyearq"])[column].shift(1)
    fundamentals[output_column] = np.where(
        fundamentals["fqtr"].eq(1),
        fundamentals[column],
        fundamentals[column] - previous,
    )
    fundamentals.loc[fundamentals[column].isna(), output_column] = np.nan


def clean_fundamentals() -> pd.DataFrame:
    fund = pd.read_csv(FUNDAMENTALS_CSV, low_memory=False)
    fund.columns = fund.columns.str.lower()
    fund["datadate"] = pd.to_datetime(fund["datadate"], errors="coerce")
    fund["rdq"] = pd.to_datetime(fund["rdq"], errors="coerce")
    fund["ticker_compustat"] = normalize_ticker(fund["tic"])
    fund["cusip8"] = normalize_cusip8(fund["cusip"])

    fund = fund.loc[
        fund["datafmt"].eq("STD")
        & fund["indfmt"].eq("INDL")
        & fund["consol"].eq("C")
        & fund["curcdq"].eq("USD")
    ].copy()

    fund = fund.dropna(subset=["gvkey", "datadate"]).copy()
    fund["gvkey"] = fund["gvkey"].astype("int64")

    # Keep the most complete record if a rare duplicate remains.
    value_columns = [
        column
        for column in fund.columns
        if column
        not in {
            "gvkey",
            "datadate",
            "rdq",
            "tic",
            "ticker_compustat",
            "cusip",
            "cusip8",
            "conm",
            "conml",
        }
    ]
    fund["_completeness"] = fund[value_columns].notna().sum(axis=1)
    fund = (
        fund.sort_values(
            ["gvkey", "datadate", "_completeness"], ascending=[True, True, False]
        )
        .drop_duplicates(["gvkey", "datadate"], keep="first")
        .drop(columns="_completeness")
    )

    valid_rdq = (
        fund["rdq"].notna()
        & fund["rdq"].ge(fund["datadate"])
        & fund["rdq"].le(fund["datadate"] + pd.Timedelta(days=180))
    )
    fund["available_date"] = fund["rdq"].where(
        valid_rdq, fund["datadate"] + pd.Timedelta(days=90)
    )
    fund["availability_source"] = np.where(valid_rdq, "rdq", "datadate_plus_90d")

    fund = fund.sort_values(["gvkey", "fyearq", "fqtr", "datadate"])
    for source, target in [
        ("oancfy", "oancf_single_q"),
        ("capxy", "capx_single_q"),
        ("prstkcy", "repurchase_single_q"),
        ("sstky", "issuance_single_q"),
    ]:
        quarterize_ytd(fund, source, target)

    grouped = fund.groupby("gvkey", group_keys=False)
    flow_columns = [
        "saleq",
        "revtq",
        "cogsq",
        "xsgaq",
        "xintq",
        "dpq",
        "ibq",
        "niq",
        "oiadpq",
        "oibdpq",
        "oancf_single_q",
        "capx_single_q",
        "repurchase_single_q",
        "issuance_single_q",
        "dvpspq",
    ]
    for column in flow_columns:
        fund[f"{column}_ttm"] = grouped[column].transform(
            lambda x: x.rolling(4, min_periods=4).sum()
        )

    lag_at = grouped["atq"].shift(4)
    lag_seq = grouped["seqq"].shift(4)
    avg_assets = (fund["atq"] + lag_at) / 2.0
    avg_equity = (fund["seqq"] + lag_seq) / 2.0
    preferred = fund["pstkq"].fillna(0.0)
    fund["book_equity"] = fund["ceqq"].where(
        fund["ceqq"].notna(), fund["seqq"] - preferred
    )

    fund["roa"] = safe_div(fund["niq_ttm"], avg_assets)
    fund["roe"] = safe_div(fund["niq_ttm"], avg_equity)
    fund["gross_profitability"] = safe_div(
        fund["revtq_ttm"] - fund["cogsq_ttm"], avg_assets
    )
    fund["operating_margin"] = safe_div(fund["oiadpq_ttm"], fund["saleq_ttm"])
    fund["net_margin"] = safe_div(fund["niq_ttm"], fund["saleq_ttm"])
    fund["cfo_roa"] = safe_div(fund["oancf_single_q_ttm"], avg_assets)
    fund["accruals"] = safe_div(
        fund["niq_ttm"] - fund["oancf_single_q_ttm"], avg_assets
    )
    fund["leverage"] = safe_div(
        fund["dlcq"].fillna(0.0) + fund["dlttq"].fillna(0.0), fund["atq"]
    )
    fund["cash_to_assets"] = safe_div(fund["cheq"], fund["atq"])
    fund["current_ratio"] = safe_div(fund["actq"], fund["lctq"])
    fund["interest_coverage"] = safe_div(fund["oiadpq_ttm"], fund["xintq_ttm"])
    fund["sales_growth_yoy"] = grouped["saleq_ttm"].pct_change(
        4, fill_method=None
    )
    fund["earnings_growth_yoy"] = safe_div(
        fund["niq_ttm"] - grouped["niq_ttm"].shift(4),
        grouped["niq_ttm"].shift(4).abs(),
    )
    fund["asset_growth_yoy"] = grouped["atq"].pct_change(4, fill_method=None)
    fund["capex_to_assets"] = safe_div(fund["capx_single_q_ttm"], avg_assets)
    fund["net_buyback_to_assets"] = safe_div(
        fund["repurchase_single_q_ttm"] - fund["issuance_single_q_ttm"],
        avg_assets,
    )

    fund = fund.replace([np.inf, -np.inf], np.nan)
    return fund.sort_values(["gvkey", "available_date", "datadate"]).reset_index(
        drop=True
    )


def build_identifier_maps(
    price: pd.DataFrame, fund: pd.DataFrame
) -> tuple[dict[str, set[int]], dict[str, set[int]], dict[str, set[int]]]:
    ticker_to_permnos: dict[str, set[int]] = defaultdict(set)
    for ticker, group in price.loc[price["ticker"].ne("")].groupby("ticker"):
        ticker_to_permnos[ticker].update(group["permno"].unique())

    cusip_to_permnos = (
        price.loc[price["cusip8"].ne("")]
        .groupby("cusip8")["permno"]
        .agg(lambda x: set(int(value) for value in x))
        .to_dict()
    )
    ticker_to_gvkeys = (
        fund.loc[fund["ticker_compustat"].ne("")]
        .groupby("ticker_compustat")["gvkey"]
        .agg(lambda x: set(int(value) for value in x))
        .to_dict()
    )
    cusip_to_gvkeys = (
        fund.loc[fund["cusip8"].ne("")]
        .groupby("cusip8")["gvkey"]
        .agg(lambda x: set(int(value) for value in x))
        .to_dict()
    )

    # Compustat ticker and CUSIP aliases help connect vendor-style constituent
    # tickers to the CRSP PERMNO that carries the relevant security history.
    for row in fund[
        ["ticker_compustat", "cusip8"]
    ].drop_duplicates().itertuples(index=False):
        if row.ticker_compustat and row.cusip8:
            ticker_to_permnos[row.ticker_compustat].update(
                cusip_to_permnos.get(row.cusip8, set())
            )
    return ticker_to_permnos, ticker_to_gvkeys, cusip_to_gvkeys


def build_monthly_membership(
    price: pd.DataFrame,
    fund: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    snapshots = pd.read_csv(MEMBERSHIP_CSV)
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["date"], errors="coerce")
    snapshots = snapshots.dropna(subset=["snapshot_date"]).sort_values(
        "snapshot_date"
    )

    eligible_price = price.loc[price["date"].between(START_DATE, END_DATE)].copy()
    month_dates = pd.DataFrame({"date": sorted(eligible_price["date"].unique())})
    monthly_snapshots = pd.merge_asof(
        month_dates,
        snapshots[["snapshot_date", "tickers"]],
        left_on="date",
        right_on="snapshot_date",
        direction="backward",
    )

    ticker_to_permnos, ticker_to_gvkeys, cusip_to_gvkeys = build_identifier_maps(
        price, fund
    )
    rows: list[dict] = []
    unmatched_rows: list[dict] = []

    for snapshot in monthly_snapshots.itertuples(index=False):
        cross_section = eligible_price.loc[eligible_price["date"].eq(snapshot.date)]
        by_permno = {
            int(row.permno): row for row in cross_section.itertuples(index=False)
        }
        codes = [
            code.strip().upper()
            for code in str(snapshot.tickers).split(",")
            if code.strip()
        ]
        exact_codes = set(cross_section["ticker"])
        codes.sort(key=lambda code: (code not in exact_codes, code))
        used_permnos: set[int] = set()

        for code in codes:
            candidates = []
            for permno in ticker_to_permnos.get(code, set()):
                if permno not in by_permno or permno in used_permnos:
                    continue
                record = by_permno[permno]
                exact = record.ticker == code
                common_share = record.shrcd in (10.0, 11.0)
                market_cap = (
                    float(record.market_cap_m)
                    if pd.notna(record.market_cap_m)
                    else -1.0
                )
                score = (
                    (1_000_000_000.0 if exact else 0.0)
                    + (100_000_000.0 if common_share else 0.0)
                    + market_cap
                )
                candidates.append((score, int(permno), exact))

            if not candidates:
                unmatched_rows.append(
                    {
                        "date": snapshot.date,
                        "snapshot_date": snapshot.snapshot_date,
                        "membership_code": code,
                    }
                )
                continue

            _, permno, exact = max(candidates)
            used_permnos.add(permno)
            record = by_permno[permno]

            gvkey_candidates = cusip_to_gvkeys.get(record.cusip8, set())
            gvkey_method = "cusip8"
            if len(gvkey_candidates) != 1:
                ticker_candidates = ticker_to_gvkeys.get(code, set())
                if len(ticker_candidates) == 1:
                    gvkey_candidates = ticker_candidates
                    gvkey_method = "membership_ticker"
                else:
                    ticker_candidates = ticker_to_gvkeys.get(record.ticker, set())
                    if len(ticker_candidates) == 1:
                        gvkey_candidates = ticker_candidates
                        gvkey_method = "crsp_ticker"
            gvkey = (
                int(next(iter(gvkey_candidates)))
                if len(gvkey_candidates) == 1
                else pd.NA
            )

            rows.append(
                {
                    "date": snapshot.date,
                    "snapshot_date": snapshot.snapshot_date,
                    "membership_code": code,
                    "permno": permno,
                    "gvkey": gvkey,
                    "membership_match_method": "exact_ticker" if exact else "alias",
                    "gvkey_match_method": gvkey_method
                    if pd.notna(gvkey)
                    else "unmatched",
                }
            )

    membership = pd.DataFrame(rows)
    membership["gvkey"] = membership["gvkey"].astype("Int64")
    membership = membership.sort_values(["date", "membership_code"])
    unmatched = pd.DataFrame(unmatched_rows)
    return membership.reset_index(drop=True), unmatched


def merge_fundamentals_asof(
    panel: pd.DataFrame, fund: pd.DataFrame
) -> pd.DataFrame:
    fundamental_columns = [
        "gvkey",
        "available_date",
        "availability_source",
        "datadate",
        "rdq",
        "fyearq",
        "fqtr",
        "ticker_compustat",
        "book_equity",
        "saleq_ttm",
        "niq_ttm",
        "oibdpq_ttm",
        "roa",
        "roe",
        "gross_profitability",
        "operating_margin",
        "net_margin",
        "cfo_roa",
        "accruals",
        "leverage",
        "cash_to_assets",
        "current_ratio",
        "interest_coverage",
        "sales_growth_yoy",
        "earnings_growth_yoy",
        "asset_growth_yoy",
        "capex_to_assets",
        "net_buyback_to_assets",
        "cheq",
        "dlcq",
        "dlttq",
    ]
    right = fund[fundamental_columns].dropna(subset=["available_date"]).copy()
    left_matched = panel.loc[panel["gvkey"].notna()].copy()
    left_unmatched = panel.loc[panel["gvkey"].isna()].copy()

    left_matched["gvkey"] = left_matched["gvkey"].astype("int64")
    right["gvkey"] = right["gvkey"].astype("int64")
    left_matched = left_matched.sort_values(["date", "gvkey"])
    right = right.sort_values(["available_date", "gvkey"])

    merged = pd.merge_asof(
        left_matched,
        right,
        by="gvkey",
        left_on="date",
        right_on="available_date",
        direction="backward",
        allow_exact_matches=True,
    )
    for column in fundamental_columns:
        if column != "gvkey" and column not in left_unmatched.columns:
            left_unmatched[column] = pd.NA
    combined = pd.concat([merged, left_unmatched], ignore_index=True, sort=False)
    combined["gvkey"] = combined["gvkey"].astype("Int64")
    combined["fundamental_age_days"] = (
        combined["date"] - combined["available_date"]
    ).dt.days
    combined["fundamentals_stale"] = combined["fundamental_age_days"].gt(180)
    stale_value_columns = [
        column
        for column in fundamental_columns
        if column
        not in {
            "gvkey",
            "available_date",
            "availability_source",
            "datadate",
            "rdq",
            "fyearq",
            "fqtr",
            "ticker_compustat",
        }
    ]
    combined.loc[combined["fundamentals_stale"], stale_value_columns] = np.nan
    return combined.sort_values(["date", "permno"]).reset_index(drop=True)


def winsorized_zscore(group: pd.Series) -> pd.Series:
    valid = group.dropna()
    if len(valid) < 20:
        return pd.Series(np.nan, index=group.index)
    lower, upper = valid.quantile([0.01, 0.99])
    clipped = group.clip(lower, upper)
    standard_deviation = clipped.std()
    if not np.isfinite(standard_deviation) or standard_deviation <= 1e-12:
        return pd.Series(np.nan, index=group.index)
    return (clipped - clipped.mean()) / standard_deviation


def build_factor_panel(
    price: pd.DataFrame, fund: pd.DataFrame, membership: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    price_columns = [
        "date",
        "permno",
        "ticker",
        "comnam",
        "cusip8",
        "shrcd",
        "exchcd",
        "siccd",
        "price",
        "vol",
        "shrout",
        "market_cap_m",
        "total_ret",
        "forward_return_1m",
        "momentum_12_1",
        "momentum_6_1",
        "short_reversal",
        "volatility_12m",
        "turnover",
        "illiquidity",
        "log_market_cap",
        "dividend_yield_12m",
    ]
    panel = membership.merge(
        price[price_columns], on=["date", "permno"], how="left", validate="one_to_one"
    )
    panel = merge_fundamentals_asof(panel, fund)

    panel["book_to_market"] = safe_div(
        panel["book_equity"], panel["market_cap_m"]
    )
    panel["earnings_yield"] = safe_div(panel["niq_ttm"], panel["market_cap_m"])
    panel["sales_yield"] = safe_div(panel["saleq_ttm"], panel["market_cap_m"])
    enterprise_value = (
        panel["market_cap_m"]
        + panel["dlcq"].fillna(0.0)
        + panel["dlttq"].fillna(0.0)
        - panel["cheq"].fillna(0.0)
    )
    panel["ebitda_to_ev"] = safe_div(panel["oibdpq_ttm"], enterprise_value)

    raw_factors = [
        "book_to_market",
        "earnings_yield",
        "sales_yield",
        "ebitda_to_ev",
        "dividend_yield_12m",
        "roa",
        "roe",
        "gross_profitability",
        "operating_margin",
        "cfo_roa",
        "accruals",
        "leverage",
        "cash_to_assets",
        "current_ratio",
        "sales_growth_yoy",
        "earnings_growth_yoy",
        "asset_growth_yoy",
        "capex_to_assets",
        "net_buyback_to_assets",
        "momentum_12_1",
        "momentum_6_1",
        "short_reversal",
        "volatility_12m",
        "turnover",
        "illiquidity",
        "log_market_cap",
    ]
    for factor in raw_factors:
        panel[f"{factor}_z"] = panel.groupby("date")[factor].transform(
            winsorized_zscore
        )

    def category_mean(items: list[str | pd.Series]) -> pd.Series:
        columns = [
            panel[item] if isinstance(item, str) else item
            for item in items
        ]
        return pd.concat(columns, axis=1).mean(axis=1, skipna=True)

    panel["value_score"] = category_mean(
        [
            "book_to_market_z",
            "earnings_yield_z",
            "sales_yield_z",
            "ebitda_to_ev_z",
            "dividend_yield_12m_z",
        ]
    )
    panel["quality_score"] = category_mean(
        [
            "roa_z",
            "roe_z",
            "gross_profitability_z",
            "operating_margin_z",
            "cfo_roa_z",
            -panel["accruals_z"],
            -panel["leverage_z"],
        ]
    )
    panel["growth_score"] = category_mean(
        ["sales_growth_yoy_z", "earnings_growth_yoy_z"]
    )
    panel["investment_score"] = category_mean(
        [
            -panel["asset_growth_yoy_z"],
            -panel["capex_to_assets_z"],
            panel["net_buyback_to_assets_z"],
        ]
    )
    panel["market_score"] = category_mean(
        [
            panel["momentum_12_1_z"],
            panel["momentum_6_1_z"],
            panel["short_reversal_z"],
            -panel["volatility_12m_z"],
            -panel["illiquidity_z"],
        ]
    )
    panel["size_score"] = -panel["log_market_cap_z"]
    panel["composite_score"] = panel[
        [
            "value_score",
            "quality_score",
            "growth_score",
            "investment_score",
            "market_score",
            "size_score",
        ]
    ].mean(axis=1, skipna=True)
    panel["composite_rank_pct"] = panel.groupby("date")["composite_score"].rank(
        pct=True, method="average"
    )

    panel = panel.replace([np.inf, -np.inf], np.nan)
    return panel.sort_values(["date", "permno"]).reset_index(drop=True), raw_factors


def write_reports(
    price: pd.DataFrame,
    fund: pd.DataFrame,
    membership: pd.DataFrame,
    unmatched: pd.DataFrame,
    panel: pd.DataFrame,
    raw_factors: list[str],
) -> None:
    monthly_counts = membership.groupby("date").agg(
        matched_members=("permno", "nunique"),
        exact_ticker_matches=(
            "membership_match_method",
            lambda x: int(x.eq("exact_ticker").sum()),
        ),
        gvkey_matches=("gvkey", lambda x: int(x.notna().sum())),
    )
    if not unmatched.empty:
        unmatched_counts = unmatched.groupby("date").size().rename("unmatched_codes")
        monthly_counts = monthly_counts.join(unmatched_counts, how="left")
    monthly_counts["unmatched_codes"] = (
        monthly_counts.get("unmatched_codes", 0).fillna(0).astype(int)
    )
    monthly_counts["expected_members"] = (
        monthly_counts["matched_members"] + monthly_counts["unmatched_codes"]
    )
    monthly_counts["membership_coverage"] = safe_div(
        monthly_counts["matched_members"], monthly_counts["expected_members"]
    )
    monthly_counts["fundamental_coverage"] = safe_div(
        monthly_counts["gvkey_matches"], monthly_counts["matched_members"]
    )
    monthly_counts.reset_index().to_csv(
        REPORT_DIR / "monthly_coverage.csv", index=False
    )
    unmatched.to_csv(REPORT_DIR / "unmatched_membership_codes.csv", index=False)

    missing = (
        panel[raw_factors]
        .isna()
        .mean()
        .rename("missing_fraction")
        .sort_values()
        .rename_axis("factor")
        .reset_index()
    )
    missing.to_csv(REPORT_DIR / "factor_missingness.csv", index=False)

    leakage_violations = int(
        (
            panel["available_date"].notna()
            & panel["available_date"].gt(panel["date"])
        ).sum()
    )
    summary = {
        "input_price_rows": int(len(price)),
        "input_fundamental_rows_after_filters": int(len(fund)),
        "panel_rows": int(len(panel)),
        "panel_start": str(panel["date"].min().date()),
        "panel_end": str(panel["date"].max().date()),
        "unique_permnos": int(panel["permno"].nunique()),
        "unique_gvkeys_matched": int(panel["gvkey"].nunique(dropna=True)),
        "average_members_per_month": float(monthly_counts["matched_members"].mean()),
        "minimum_members_per_month": int(monthly_counts["matched_members"].min()),
        "maximum_members_per_month": int(monthly_counts["matched_members"].max()),
        "average_membership_coverage": float(
            monthly_counts["membership_coverage"].mean()
        ),
        "average_gvkey_coverage": float(
            monthly_counts["fundamental_coverage"].mean()
        ),
        "point_in_time_leakage_violations": leakage_violations,
        "duplicate_date_permno_rows": int(panel.duplicated(["date", "permno"]).sum()),
        "source_limitations": [
            "Historical membership is a public ticker-based dataset, not CRSP msp500list.",
            "PERMNO and GVKEY links are reconstructed from ticker/CUSIP aliases because CCM link history was not supplied.",
            "Unmatched membership codes are excluded and listed in the audit report.",
        ],
    }
    (REPORT_DIR / "quality_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    readme = f"""# S&P 500 Point-in-Time Factor Database

## Main output

`final/sp500_monthly_factor_panel_2000_2024.parquet`

Each row represents one matched historical S&P 500 constituent at one CRSP
month-end. Financial statements are joined only when `available_date <= date`.

## Dimensions

* Rows: {len(panel):,}
* Months: {panel['date'].nunique():,}
* PERMNOs: {panel['permno'].nunique():,}
* Date range: {panel['date'].min().date()} to {panel['date'].max().date()}

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
"""
    (OUTPUT_DIR / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    for directory in [CLEAN_DIR, FINAL_DIR, REPORT_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    print("1/5 Cleaning CRSP monthly data...")
    price = clean_price_data()
    price.to_parquet(CLEAN_DIR / "crsp_monthly_clean.parquet", index=False)

    print("2/5 Cleaning Compustat quarterly data...")
    fund = clean_fundamentals()
    fund.to_parquet(CLEAN_DIR / "compustat_quarterly_clean.parquet", index=False)

    print("3/5 Reconstructing monthly S&P 500 membership...")
    membership, unmatched = build_monthly_membership(price, fund)
    membership.to_parquet(
        CLEAN_DIR / "sp500_monthly_membership.parquet", index=False
    )

    print("4/5 Building point-in-time factor panel...")
    panel, raw_factors = build_factor_panel(price, fund, membership)
    panel.to_parquet(
        FINAL_DIR / "sp500_monthly_factor_panel_2000_2024.parquet", index=False
    )

    print("5/5 Writing audit reports...")
    write_reports(price, fund, membership, unmatched, panel, raw_factors)

    print("Done.")
    print((FINAL_DIR / "sp500_monthly_factor_panel_2000_2024.parquet").resolve())


if __name__ == "__main__":
    main()
