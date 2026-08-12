import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd

from src.wyckoff.base_detector import BaseResult

logger = logging.getLogger("dominus-investor.wyckoff.spring_detector")

SPRING_VOLUME_MULTIPLIER = 1.5  # Volume cua Spring phai > MA_vol * 1.5
SPRING_LOOKAHEAD_DAYS = 30      # Chi tim Spring trong N ngay sau Base ket thuc


@dataclass
class SpringResult:
    """Ket qua phat hien tin hieu Spring (gia dung / Wyckoff Spring)."""
    date: date
    low_price: float      # Gia thap nhat trong phien Spring (xuong duoi Base)
    close_price: float    # Gia dong cua trong phien Spring (hoi phuc ve tren Base)
    volume: int           # Volume cua phien Spring
    volume_ratio: float   # Ty le Volume Spring / MA5 Volume


class SpringDetector:
    """
    Phat hien tin hieu Spring theo Wyckoff.

    Dieu kien Spring:
    1. Low < base.support_level (gia xuat hien duoi day Base)
    2. Close > base.support_level (gia hoi phuc lai tren day Base cung phien)
    3. Volume > MA(vol, 5) * SPRING_VOLUME_MULTIPLIER (volume tang manh)
    4. Chi tim trong SPRING_LOOKAHEAD_DAYS ngay sau Base ket thuc
    """

    def detect_spring(self, df: pd.DataFrame, base: BaseResult) -> Optional[SpringResult]:
        """
        Tim tin hieu Spring trong DataFrame OHLCV cho 1 ma.
        Tra ve SpringResult dau tien tim thay, hoac None.
        """
        if df is None or df.empty or base is None:
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)

        # Xac dinh cua so tim kiem: sau Base ket thuc
        try:
            base_end_idx = df.index[df["trade_date"] == base.end_date].tolist()
            if not base_end_idx:
                # Lay phien gan nhat <= base.end_date
                base_end_idx = df.index[df["trade_date"] <= base.end_date].tolist()
                if not base_end_idx:
                    return None
            start_search = base_end_idx[-1] + 1
        except Exception:
            return None

        end_search = min(start_search + SPRING_LOOKAHEAD_DAYS, len(df))
        search_window = df.iloc[start_search:end_search].copy()

        if search_window.empty:
            return None

        # Tinh MA5 volume de so sanh
        # Lay MA5 tu cac phien truoc Base
        pre_base_vol = df.iloc[max(0, start_search - 10): start_search]["volume"]
        ma5_vol = pre_base_vol.mean() if len(pre_base_vol) > 0 else search_window["volume"].mean()

        if ma5_vol == 0:
            return None

        # Quet tung phien tim Spring
        for _, row in search_window.iterrows():
            low_price = float(row["low"])
            close_price = float(row["close"])
            volume = int(row["volume"])
            vol_ratio = volume / ma5_vol

            spring_condition = (
                low_price < base.support_level          # Xuong duoi day Base
                and close_price >= base.support_level   # Dong cua tren hoac bang day Base
                and vol_ratio >= SPRING_VOLUME_MULTIPLIER
            )

            if spring_condition:
                logger.info(
                    "Phat hien Spring cho ma tai ngay %s: Low=%.0f, Close=%.0f, VolRatio=%.2f",
                    row["trade_date"], low_price, close_price, vol_ratio
                )
                return SpringResult(
                    date=row["trade_date"],
                    low_price=round(low_price, 0),
                    close_price=round(close_price, 0),
                    volume=volume,
                    volume_ratio=round(vol_ratio, 2)
                )

        return None


spring_detector = SpringDetector()
