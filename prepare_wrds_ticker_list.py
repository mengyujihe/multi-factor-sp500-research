from pathlib import Path

import pandas as pd


INPUT = Path(
    "/Users/ericyang/Downloads/"
    "S&P 500 Historical Components & Changes (Updated).csv"
)
OUTPUT_DIR = Path("wrds_code_lists")
START_DATE = pd.Timestamp("2000-01-01")
END_DATE = pd.Timestamp("2024-12-31")
CHUNK_SIZE = 500


def main():
    snapshots = pd.read_csv(INPUT)
    snapshots["date"] = pd.to_datetime(snapshots["date"], errors="raise")
    snapshots = snapshots.sort_values("date").reset_index(drop=True)

    # Include the last snapshot on or before the start date, followed by every
    # change through the end date. This captures all constituents active at any
    # point during 2000-2024.
    before_start = snapshots.loc[snapshots["date"] <= START_DATE].tail(1)
    during_period = snapshots.loc[
        snapshots["date"].between(START_DATE, END_DATE, inclusive="right")
    ]
    relevant = pd.concat([before_start, during_period], ignore_index=True)

    tickers = sorted(
        {
            ticker.strip().upper()
            for value in relevant["tickers"]
            for ticker in str(value).split(",")
            if ticker.strip()
        }
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    complete_path = OUTPUT_DIR / "sp500_tickers_ever_member_2000_2024.txt"
    complete_path.write_text("\n".join(tickers) + "\n", encoding="utf-8")

    chunk_paths = []
    for start in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[start : start + CHUNK_SIZE]
        number = start // CHUNK_SIZE + 1
        path = OUTPUT_DIR / f"sp500_tickers_2000_2024_part_{number}.txt"
        path.write_text("\n".join(chunk) + "\n", encoding="utf-8")
        chunk_paths.append(path)

    print(f"Snapshots used: {len(relevant):,}")
    print(f"Unique tickers: {len(tickers):,}")
    print(f"Complete list: {complete_path.resolve()}")
    print("Upload chunks:")
    for path in chunk_paths:
        count = len(path.read_text(encoding="utf-8").splitlines())
        print(f"  {path.resolve()} ({count} tickers)")


if __name__ == "__main__":
    main()
