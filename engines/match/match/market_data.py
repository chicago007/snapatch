"""KRX 일봉 조회·티커 CSV."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from pykrx import stock

logging.getLogger("pykrx").setLevel(logging.CRITICAL)
logging.getLogger("pykrx").propagate = False


def normalize_ticker(raw: str) -> str:
    return str(raw).strip().strip("'").zfill(6)


def get_stock_data(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    return stock.get_market_ohlcv_by_date(start_date, end_date, ticker)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna()


def close_series(df: pd.DataFrame):
    import numpy as np

    return df["종가"].astype(float).values


def read_tickers(csv_path: Path) -> list[str]:
    df = pd.read_csv(csv_path)
    return [normalize_ticker(x) for x in df["ticker"]]
