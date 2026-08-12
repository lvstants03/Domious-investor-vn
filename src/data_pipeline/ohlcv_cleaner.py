import logging
import pandas as pd
import numpy as np

logger = logging.getLogger("dominus-investor.data_pipeline.ohlcv_cleaner")

# Nguong phat hien volume bat thuong: gap 5 lan MA5 vol
ANOMALY_VOLUME_MULTIPLIER = 5.0
# Gia tri volume toi thieu de ma duoc coi la co thanh khoan
MIN_DAILY_VOLUME = 50_000


class OHLCVCleaner:
    """Lam sach va chuan hoa du lieu OHLCV truoc khi luu vao DB."""

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pipeline lam sach du lieu cho 1 ma:
        1. Loai bo phien Volume = 0 (ngay nghi le TCBS tra ve 0)
        2. Sap xep theo ngay tang dan
        3. Forward-fill gap toi da 1 ngay cho gia (khong duoc forward-fill volume)
        4. Danh dau phien volume bat thuong (is_anomaly = True)
        """
        if df is None or df.empty:
            return df

        df = df.copy()
        df = df.sort_values("trade_date").reset_index(drop=True)

        # Buoc 1: Loai bo phien Volume = 0 hoac NaN
        before = len(df)
        df = df[df["volume"] > 0].reset_index(drop=True)
        removed = before - len(df)
        if removed > 0:
            logger.debug("Loai bo %d phien volume = 0", removed)

        if df.empty:
            return df

        # Buoc 2: Forward-fill NaN trong gia (toi da 1 ngay, khong fill volume)
        price_cols = ["open", "high", "low", "close"]
        df[price_cols] = df[price_cols].ffill(limit=1)

        # Buoc 3: Danh dau phien volume bat thuong
        df["ma5_vol"] = df["volume"].rolling(5, min_periods=1).mean()
        df["is_anomaly"] = df["volume"] > (df["ma5_vol"] * ANOMALY_VOLUME_MULTIPLIER)
        df = df.drop(columns=["ma5_vol"])

        # Buoc 4: Loai bo hang con thieu du lieu gia
        df = df.dropna(subset=price_cols)

        return df.reset_index(drop=True)

    def detect_splits(self, df: pd.DataFrame) -> list:
        """
        Phat hien kha nang chia tach co phieu bang cach kiem tra ty le thay doi gia dot ngot > 30%.
        Tra ve danh sach ngay nghi ngo co chia tach.
        """
        if df is None or len(df) < 2:
            return []

        df = df.sort_values("trade_date").reset_index(drop=True)
        pct_change = df["close"].pct_change().abs()
        split_dates = df.loc[pct_change > 0.30, "trade_date"].tolist()

        if split_dates:
            logger.warning("Phat hien %d ngay nghi ngo chia tach: %s", len(split_dates), split_dates)

        return split_dates

    def filter_liquid(self, symbols_dfs: dict, min_avg_vol: int = MIN_DAILY_VOLUME) -> dict:
        """
        Loai bo ma co thanh khoan kem (trung binh volume < min_avg_vol).
        Tra ve dict da loc.
        """
        filtered = {}
        for symbol, df in symbols_dfs.items():
            if df is None or df.empty:
                continue
            avg_vol = df["volume"].mean()
            if avg_vol >= min_avg_vol:
                filtered[symbol] = df
            else:
                logger.info("Loai ma %s do thanh khoan kem (avg vol: %d)", symbol, int(avg_vol))
        return filtered


ohlcv_cleaner = OHLCVCleaner()
