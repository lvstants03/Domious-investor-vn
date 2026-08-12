import logging
from datetime import date
from typing import Optional, Tuple
import pandas as pd
import pandas_ta as ta
import numpy as np

from src.data_pipeline.indicators import indicators

logger = logging.getLogger("dominus-investor.data_pipeline.market_regime")

# Nguong do doc de phan loai xu huong
SLOPE_BULL_THRESHOLD = 0.0
SLOPE_BEAR_THRESHOLD = 0.0


class MarketRegimeCalculator:
    """
    Tinh Market Regime (xu huong thi truong tong the) dua tren VNI/VN30.
    
    Logic:
    - BULL  = EMA20 > EMA50 VA slope(EMA20, 10) > 0
    - BEAR  = EMA20 < EMA50 VA slope(EMA20, 10) < 0
    - SIDEWAYS = con lai
    """

    def calculate(self, vnindex_df: pd.DataFrame) -> Optional[dict]:
        """
        Input: DataFrame OHLCV cua VNI (cot close la bat buoc).
        Output: dict {regime_date, vnindex_close, regime, ema20, ema50, trend_slope}
        """
        if vnindex_df is None or len(vnindex_df) < 55:
            logger.warning("Khong du du lieu VNI de tinh Market Regime (can it nhat 55 phien)")
            return None

        close = vnindex_df["close"]
        trade_dates = vnindex_df["trade_date"]

        ema20_series = ta.ema(close, length=20)
        ema50_series = ta.ema(close, length=50)

        if ema20_series is None or ema50_series is None:
            return None

        ema20_val = float(ema20_series.iloc[-1]) if not pd.isna(ema20_series.iloc[-1]) else None
        ema50_val = float(ema50_series.iloc[-1]) if not pd.isna(ema50_series.iloc[-1]) else None

        if ema20_val is None or ema50_val is None:
            return None

        # Do doc cua EMA20 trong 10 phien gan nhat
        slope = indicators.linear_regression_slope(ema20_series.dropna(), period=10)

        # Xac dinh Regime
        if ema20_val > ema50_val and (slope is not None and slope > SLOPE_BULL_THRESHOLD):
            regime = "BULL"
        elif ema20_val < ema50_val and (slope is not None and slope < SLOPE_BEAR_THRESHOLD):
            regime = "BEAR"
        else:
            regime = "SIDEWAYS"

        latest_date = trade_dates.iloc[-1]
        latest_close = float(close.iloc[-1])

        return {
            "regime_date": latest_date,
            "vnindex_close": latest_close,
            "regime": regime,
            "ema20": round(ema20_val, 2),
            "ema50": round(ema50_val, 2),
            "trend_slope": round(slope, 4) if slope is not None else None
        }

    def classify_symbol_regime(self, close: pd.Series) -> str:
        """
        Tinh regime don gian cho 1 ma co phieu cu the (dung trong Wyckoff filter).
        Tra ve: 'BULL', 'BEAR', hoac 'SIDEWAYS'
        """
        if len(close) < 55:
            return "SIDEWAYS"

        ema20 = ta.ema(close, length=20)
        ema50 = ta.ema(close, length=50)

        if ema20 is None or ema50 is None:
            return "SIDEWAYS"

        last_ema20 = float(ema20.iloc[-1])
        last_ema50 = float(ema50.iloc[-1])
        slope = indicators.linear_regression_slope(ema20.dropna(), period=10)

        if last_ema20 > last_ema50 and slope is not None and slope > 0:
            return "BULL"
        elif last_ema20 < last_ema50 and slope is not None and slope < 0:
            return "BEAR"
        return "SIDEWAYS"

    async def calculate_market_breadth(self, db_session) -> float:
        """
        Tinh % so ma co phieu trong ScanUniverse co Close < MA200.
        """
        from src.database.models import ScanUniverse, OHLCVDaily
        from sqlalchemy import select

        univ_result = await db_session.execute(
            select(ScanUniverse.symbol).where(ScanUniverse.is_active == True)
        )
        symbols = [r[0] for r in univ_result.all()]
        if not symbols:
            return 0.0

        under_ma200_count = 0
        valid_symbols = 0

        for sym in symbols:
            result = await db_session.execute(
                select(OHLCVDaily.close)
                .where(OHLCVDaily.symbol == sym)
                .order_by(OHLCVDaily.trade_date.desc())
                .limit(200)
            )
            closes = [r[0] for r in result.all()]
            if len(closes) < 200:
                continue

            valid_symbols += 1
            ma200 = sum(closes) / 200
            latest_close = closes[0]
            if latest_close < ma200:
                under_ma200_count += 1

        if valid_symbols == 0:
            return 0.0

        return round((under_ma200_count / valid_symbols) * 100, 2)

    async def check_regime_lock(self, vni_df: pd.DataFrame, db_session) -> Tuple[bool, str]:
        """
        Kiem tra dieu kien khoa he thong (LOCKED):
        1. % co phieu duoi MA200 > 70%
        2. VNI co do doc < -2% trong 10 phien
        """
        if vni_df is None or len(vni_df) < 10:
            return False, "Khong du du lieu de kiem tra"

        breadth = await self.calculate_market_breadth(db_session)

        vni_close = vni_df["close"].values
        vni_slope_pct = ((vni_close[-1] - vni_close[-10]) / vni_close[-10]) * 100

        is_locked = False
        reasons = []

        if breadth > 70.0:
            is_locked = True
            reasons.append(f"Do rong thi truong: {breadth}% co phieu duoi MA200 (> 70%)")

        if vni_slope_pct < -2.0:
            is_locked = True
            reasons.append(f"Do doc VNI 10 phien: {vni_slope_pct:.2f}% (< -2.0%)")

        reason_str = " | ".join(reasons) if is_locked else "Thi truong on dinh"
        return is_locked, reason_str


market_regime_calc = MarketRegimeCalculator()
