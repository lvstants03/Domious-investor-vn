import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("dominus-investor.wyckoff.base_detector")

# Tham so phat hien Base
MIN_BASE_DAYS = 20          # Base phai ton tai it nhat N phien
MAX_BASE_DAYS = 120         # Gioi han tim kiem Base
BASE_TIGHTNESS_RATIO = 0.6  # Bien do Base <= 60% trung binh bien do lich su
MIN_AVG_VOLUME = 200_000    # Volume trung binh toi thieu de xem xet ma


@dataclass
class BaseResult:
    """Ket qua phat hien vung tich luy (Base)."""
    start_date: date
    end_date: date
    support_level: float      # Muc ho tro (day thap nhat cua Base)
    resistance_level: float   # Muc khang cu (dinh cao nhat cua Base)
    avg_volume: float         # Volume trung binh trong Base
    tightness_ratio: float    # Ty le bien do Base / bien do lich su (cang nho cang chat)
    base_length_days: int


class BaseDetector:
    """Phat hien vung tich luy (Base / Consolidation Zone) theo Wyckoff."""

    def _find_pivot_points(self, df: pd.DataFrame, window: int = 5) -> tuple:
        """
        Tim cac diem xoay (Pivot High va Pivot Low) trong chuoi OHLCV.
        Pivot High: High[i] la dinh so voi window phien xung quanh.
        Pivot Low: Low[i] la day so voi window phien xung quanh.
        Tra ve (index_highs, index_lows).
        """
        highs = df["high"].values
        lows = df["low"].values
        n = len(highs)

        pivot_highs = []
        pivot_lows = []

        for i in range(window, n - window):
            if highs[i] == max(highs[i - window: i + window + 1]):
                pivot_highs.append(i)
            if lows[i] == min(lows[i - window: i + window + 1]):
                pivot_lows.append(i)

        return pivot_highs, pivot_lows

    def detect_base(self, df: pd.DataFrame, lookback: int = 60) -> Optional[BaseResult]:
        """
        Phat hien vung tich luy trong N phien gan nhat cua co phieu.

        Dieu kien Base hop le:
        1. Ma co Volume trung binh >= MIN_AVG_VOLUME
        2. Tim khoang thoi gian trong lookback phien co:
           - (High_max - Low_min) <= trung binh bien do lich su * BASE_TIGHTNESS_RATIO
           - Khoang thoi gian >= MIN_BASE_DAYS phien
        3. Lay Base gần nhat (Base dang hinh thanh gan day nhat)
        """
        if df is None or len(df) < MAX_BASE_DAYS + 10:
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)

        # Kiem tra thanh khoan toi thieu
        avg_vol = df["volume"].mean()
        if avg_vol < MIN_AVG_VOLUME:
            return None

        # Tinh bien do lich su trung binh (High - Low hang ngay)
        df["daily_range"] = df["high"] - df["low"]
        avg_range = df["daily_range"].mean()

        if avg_range == 0:
            return None

        # Lay N phien gan nhat de tim Base
        recent_df = df.iloc[-lookback:].reset_index(drop=True)

        # Quet tu cuoi ve dau de tim Base gan nhat
        best_base = None
        best_end_idx = len(recent_df) - 1

        for end_idx in range(len(recent_df) - 1, MIN_BASE_DAYS - 1, -1):
            for start_idx in range(max(0, end_idx - MAX_BASE_DAYS), end_idx - MIN_BASE_DAYS + 1):
                window = recent_df.iloc[start_idx: end_idx + 1]
                window_high = window["high"].max()
                window_low = window["low"].min()
                window_range = window_high - window_low
                tightness = window_range / avg_range

                if tightness <= BASE_TIGHTNESS_RATIO:
                    base_len = end_idx - start_idx + 1
                    base_avg_vol = window["volume"].mean()
                    best_base = BaseResult(
                        start_date=window["trade_date"].iloc[0],
                        end_date=window["trade_date"].iloc[-1],
                        support_level=round(window_low, 0),
                        resistance_level=round(window_high, 0),
                        avg_volume=round(base_avg_vol, 0),
                        tightness_ratio=round(tightness, 3),
                        base_length_days=base_len
                    )
                    return best_base  # Lay Base dau tien tim thay (gân nhat)

        return best_base


base_detector = BaseDetector()
