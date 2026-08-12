import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional, Literal
import pandas as pd
import pandas_ta as ta

from src.wyckoff.base_detector import BaseResult
from src.wyckoff.spring_detector import SpringResult

logger = logging.getLogger("dominus-investor.wyckoff.retest_detector")

RETEST_DRY_VOL_RATIO = 0.8   # Volume Retest phai < MA_vol * 0.8 (volume kho - xac nhan)
RETEST_LOOKAHEAD_DAYS = 20   # Tim Retest trong N ngay sau Spring
RETEST_PROXIMITY_PCT = 0.02  # Gia phai cham MA20 hoac dinh cu trong pham vi 2%


@dataclass
class RetestResult:
    """Ket qua phat hien Retest sau Breakout."""
    date: date
    price: float
    volume_ratio: float
    retest_type: Literal["ma20", "resistance"]  # Cham MA20 hay cham muc khang cu cu


class RetestDetector:
    """
    Phat hien Retest sau khi co phieu Breakout khoi Base.

    Dieu kien:
    1. Gia phai pha vo resistance_level cua Base (Breakout)
    2. Sau do gia quay ve cham MA20 hoac muc khang cu cu (resistance_level)
    3. Volume trong phien Retest phai kho (< MA_vol * RETEST_DRY_VOL_RATIO)
    4. Chi tim trong RETEST_LOOKAHEAD_DAYS ngay sau Spring
    """

    def detect_retest(
        self,
        df: pd.DataFrame,
        base: BaseResult,
        spring: SpringResult
    ) -> Optional[RetestResult]:
        """
        Tim Retest trong DataFrame OHLCV sau khi xay ra Spring/Breakout.
        """
        if df is None or df.empty or base is None or spring is None:
            return None

        df = df.sort_values("trade_date").reset_index(drop=True)

        # Tim vi tri phien Spring de bat dau quet
        try:
            spring_idx = df.index[df["trade_date"] == spring.date].tolist()
            if not spring_idx:
                spring_idx = df.index[df["trade_date"] <= spring.date].tolist()
                if not spring_idx:
                    return None
            start_search = spring_idx[-1] + 1
        except Exception:
            return None

        end_search = min(start_search + RETEST_LOOKAHEAD_DAYS, len(df))
        search_window = df.iloc[start_search:end_search].copy().reset_index(drop=True)

        if len(search_window) < 3:
            return None

        # Tinh MA20 cho toan bo df truoc do de co MA20 chinh xac trong cua so quet
        ma20_series = ta.ema(df["close"], length=20)
        pre_vol = df.iloc[max(0, start_search - 10): start_search]["volume"]
        ma5_vol = pre_vol.mean() if len(pre_vol) > 0 else df["volume"].mean()

        if ma5_vol == 0:
            return None

        for local_idx, row in search_window.iterrows():
            # Lay MA20 tuong ung
            global_idx = start_search + local_idx
            ma20_val = float(ma20_series.iloc[global_idx]) if global_idx < len(ma20_series) else None

            low = float(row["low"])
            high = float(row["high"])
            close = float(row["close"])
            vol_ratio = int(row["volume"]) / ma5_vol
            resistance = base.resistance_level

            # Volume phai kho (xac nhan Retest, khong phai down trend)
            if vol_ratio >= RETEST_DRY_VOL_RATIO:
                continue

            retest_type = None
            # Kiem tra cham MA20
            if ma20_val is not None:
                if low <= ma20_val * (1 + RETEST_PROXIMITY_PCT) and high >= ma20_val * (1 - RETEST_PROXIMITY_PCT):
                    retest_type = "ma20"

            # Kiem tra cham muc khang cu cu (resistance level cua Base)
            if retest_type is None:
                if low <= resistance * (1 + RETEST_PROXIMITY_PCT) and high >= resistance * (1 - RETEST_PROXIMITY_PCT):
                    retest_type = "resistance"

            if retest_type is not None:
                logger.info(
                    "Phat hien Retest tai ngay %s: Price=%.0f, VolRatio=%.2f, Type=%s",
                    row["trade_date"], close, vol_ratio, retest_type
                )
                return RetestResult(
                    date=row["trade_date"],
                    price=round(close, 0),
                    volume_ratio=round(vol_ratio, 2),
                    retest_type=retest_type
                )

        return None


retest_detector = RetestDetector()
