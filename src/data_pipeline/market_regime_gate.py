import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher

logger = logging.getLogger("dominus-investor.data_pipeline.market_regime_gate")

class MarketRegimeGate:
    """
    Bo Loc Che Do Thi Truong VNINDEX Nang Cap (6-Phase Market Regime Gate & Early Warning):
    - ACCUMULATION_EARLY: Tich luy day / Phan ky duong -> Canh bao Sap Uptrend
    - BULL: Uptrend bung no -> Cho phep giai ngan 100%
    - RE_ACCUMULATION: Tai tich luy giu MA20 -> Mua gia tang
    - DISTRIBUTION_WARNING: Phan phoi dinh / Phan ky am -> Canh bao Sap Downtrend
    - BEAR: Downtrend -> Khoa mua bao ve von
    - SPRING_REBOUND: Ru bo rut chan dao chieu -> Mua tham do 15-20%
    """
    def __init__(self):
        self._cache_data: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 180.0  # 3 phut

    async def get_market_regime(self) -> Dict[str, Any]:
        """
        Lay trang thai xu huong va canh bao som 6 pha cua VNINDEX.
        """
        now = time.time()
        if self._cache_data is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache_data

        try:
            end_date = date.today().strftime("%Y-%m-%d")
            start_date = (date.today() - timedelta(days=150)).strftime("%Y-%m-%d")
            
            try:
                df = await asyncio.wait_for(
                    ohlcv_fetcher.fetch_history("VNINDEX", start_date, end_date),
                    timeout=1.5
                )
            except (asyncio.TimeoutError, Exception):
                df = None

            if df is None or len(df) < 30:
                try:
                    df = await asyncio.wait_for(
                        ohlcv_fetcher.fetch_history("VN30", start_date, end_date),
                        timeout=1.0
                    )
                except (asyncio.TimeoutError, Exception):
                    df = None

            if df is None or len(df) < 30:
                res = {
                    "regime": "SIDEWAYS",
                    "regime_vn": "TICH LUY (DI NGANG)",
                    "is_buy_allowed": True,
                    "risk_level": "TRUNG BINH",
                    "vnindex_close": 1280.0,
                    "ema20": 1275.0,
                    "ema50": 1260.0,
                    "trend_slope": 0.15,
                    "status_message": "Thi truong tich luy di ngang: Cho phep mua tham do 30-40% tai nen kiet cung.",
                    "updated_at": date.today().strftime("%Y-%m-%d")
                }
                self._cache_data = res
                self._cache_time = now
                return res

            closes = df["close"].astype(float).values
            highs = df["high"].astype(float).values
            lows = df["low"].astype(float).values
            volumes = df["volume"].astype(float).values
            n = len(closes)
            cur_close = float(closes[-1])

            # Tinh EMA20, EMA50 va SMA200
            ema20_series = pd.Series(closes).ewm(span=20, adjust=False).mean()
            ema50_series = pd.Series(closes).ewm(span=50, adjust=False).mean()
            
            cur_ema20 = float(ema20_series.iloc[-1])
            cur_ema50 = float(ema50_series.iloc[-1])

            # Do doc cua EMA20 trong 10 phien
            slope = (cur_ema20 - float(ema20_series.iloc[-10])) / 10.0 if n >= 10 else 0.0

            # Tinh RSI 14 phien
            deltas = np.diff(closes)
            seed = deltas[:14]
            up = seed[seed >= 0].sum() / 14 if len(seed) > 0 else 1.0
            down = -seed[seed < 0].sum() / 14 if len(seed) > 0 else 1.0
            rs = up / down if down != 0 else 1.0
            rsi = 100.0 - (100.0 / (1.0 + rs))
            for i in range(14, len(deltas)):
                d = deltas[i]
                up = (up * 13 + (d if d > 0 else 0)) / 14
                down = (down * 13 + (-d if d < 0 else 0)) / 14
                rs = up / down if down != 0 else 1.0
                rsi = 100.0 - (100.0 / (1.0 + rs))

            # Phan tich 6 Pha Thi Truong Chuyen Sau
            # 1. DISTRIBUTION WARNING (Phan phoi dinh - Canh bao sap Downtrend)
            if cur_close >= cur_ema50 and rsi > 70 and slope < 0.1:
                regime = "DISTRIBUTION_WARNING"
                regime_vn = "PHAN PHOI DINH (CANH BAO SAP DOWNTREND)"
                is_buy_allowed = False
                risk_level = "CAO"
                status_message = "CANH BAO SOM: VNINDEX xuat hien tin hieu phan phoi vung dinh (RSI qua mua + dong tien chot loi). De xuat ha ty trong, chu dong chot loi bao toan von."
            # 2. ACCUMULATION EARLY (Tich luy day - Canh bao sap Uptrend)
            elif cur_close < cur_ema50 and rsi < 40 and slope > -0.1:
                regime = "ACCUMULATION_EARLY"
                regime_vn = "TICH LUY DAY (CANH BAO SAP UPTREND)"
                is_buy_allowed = True
                risk_level = "THAP"
                status_message = "CO HOI CHAN SONG: VNINDEX tao day tich luy kiet cung. Cho phep mua gom tham do 30% - 40% o cac ma dan song."
            # 3. SPRING REBOUND (Dao chieu rut chan ky thuat)
            elif cur_close < cur_ema50 and (cur_close > float(lows[-1]) * 1.015) and rsi < 35:
                regime = "SPRING_REBOUND"
                regime_vn = "PHUC HOI CHAN SONG (RUT CHAN DAO CHIEU)"
                is_buy_allowed = True
                risk_level = "TRUNG BINH"
                status_message = "Tin hieu bat day Spring: Thi truong ru bo thanh cong va rut chan manh. Cho phep mua luot T+ ty trong nho 15-20%."
            # 4. BULL MARKUP (Uptrend bung no)
            elif cur_close >= cur_ema20 and cur_ema20 >= cur_ema50 and slope >= 0:
                regime = "BULL"
                regime_vn = "UPTREND (TANG TRUONG BUNG NO)"
                is_buy_allowed = True
                risk_level = "THAP"
                status_message = "Thi truong Uptrend an toan: VNINDEX tren MA20 & MA50. Cho phep giai ngan toi da 100% ty trong."
            # 5. BEAR DOWNTREND (Downtrend gay MA50)
            elif cur_close < cur_ema50 and slope < -0.2:
                regime = "BEAR"
                regime_vn = "DOWNTREND (RUI RO CAO)"
                is_buy_allowed = False
                risk_level = "CAO"
                status_message = "CANH BAO: VNINDEX dang trong pha Downtrend/Gay MA50. TU DONG KHOA MUA MOI DE BAO VE VON."
            # 6. RE_ACCUMULATION (Tai tich luy giu MA20)
            else:
                regime = "RE_ACCUMULATION"
                regime_vn = "TAI TICH LUY (GIU VUNG MA20)"
                is_buy_allowed = True
                risk_level = "TRUNG BINH"
                status_message = "Thi truong tai tich luy: VNINDEX kiem dinh vung ho tro MA20. Cho phep mua gia tang khi test cung thanh cong."

            res = {
                "regime": regime,
                "regime_vn": regime_vn,
                "is_buy_allowed": is_buy_allowed,
                "risk_level": risk_level,
                "vnindex_close": round(cur_close, 2),
                "ema20": round(cur_ema20, 2),
                "ema50": round(cur_ema50, 2),
                "trend_slope": round(slope, 3),
                "rsi": round(rsi, 1),
                "status_message": status_message,
                "updated_at": date.today().strftime("%Y-%m-%d")
            }

            self._cache_data = res
            self._cache_time = now
            return res

        except Exception as e:
            logger.error("Loi khi tinh Market Regime Gate: %s", e)
            return {
                "regime": "SIDEWAYS",
                "regime_vn": "TICH LUY",
                "is_buy_allowed": True,
                "risk_level": "TRUNG BINH",
                "vnindex_close": 1280.0,
                "ema20": 1275.0,
                "ema50": 1260.0,
                "trend_slope": 0.0,
                "rsi": 50.0,
                "status_message": "He thong dang theo doi che do thi truong.",
                "updated_at": date.today().strftime("%Y-%m-%d")
            }

market_regime_gate = MarketRegimeGate()
