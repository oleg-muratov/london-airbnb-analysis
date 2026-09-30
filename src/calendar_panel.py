from pathlib import Path        # path constants + Path return types
import pandas as pd             # chunked read_csv, concat, to_datetime, to_parquet/read_parquet
from src.data import parse_money, DATA_DIR   # reuse the $-parser and the data/ anchor

CALENDAR_CSV = DATA_DIR / "calendar.csv"
INTERIM_DIR  = DATA_DIR / "interim"
SLIM_PATH    = INTERIM_DIR / "calendar_slim.parquet"

def build_calendar_slim(force: bool = False) -> Path:
    """
    Build the slim calendar parquet cache from data/calendar.csv (one chunked pass, parsed to typed columns). 
    Honesty label: observed — a parsed cache, no transformation beyond parsing.
    """
    if not force and SLIM_PATH.exists():
        return SLIM_PATH
    
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)

    chunks = []
    diverge_count = 0
    total_rows = 0
    curr_chunksize = 2000000
    for chunk in pd.read_csv(
        CALENDAR_CSV,
        parse_dates=["date"],
        usecols = ["listing_id", "date", "available", "price", "adjusted_price"],
        chunksize=curr_chunksize
    ):
        diverge_count += int((chunk["price"] != chunk["adjusted_price"]).sum())
        total_rows += len(chunk)

        avail = chunk["available"].map({"t": True, "f": False})
        assert avail.notna().all(), "unexpected value in 'available'"
        avail = avail.astype(bool)
        price = parse_money(chunk["price"])

        slim = pd.DataFrame({
            "listing_id": chunk["listing_id"],
            "date":       chunk["date"],          # already datetime64 from parse_dates
            "available":  avail,
            "price":      price
        })
        chunks.append(slim)

    full = pd.concat(chunks, ignore_index=True)
    full.to_parquet(SLIM_PATH, engine="pyarrow", index=False)
    print(f"rows            : {len(full):>12,}  (expected 31,050,094)")
    print(f"distinct ids    : {full['listing_id'].nunique():>12,}  (expected 85,068)")
    print(f"date range      : {full['date'].min():%Y-%m-%d} -> {full['date'].max():%Y-%m-%d}  (expected 2019-11-05 -> 2020-11-04)")
    print(f"available share : {full['available'].mean():>12.3%}  (expected 32.7%)")
    print(f"adj != price    : {diverge_count:>12,} ({diverge_count / total_rows:.2%})  (expected 201,477 / 0.65%)")
    return SLIM_PATH

def load_calendar_slim() -> pd.DataFrame:
    build_calendar_slim()          # force=False → builds only if the parquet is missing
    return pd.read_parquet(SLIM_PATH)


if __name__ == "__main__":
    build_calendar_slim(force=True)