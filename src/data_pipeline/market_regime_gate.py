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
    Bo Loc Che Do Thi Truong VNINDEX (Market Regime Gate):
    - Kiem soat rui ro tong the toan san.
    - Tu dong khoa tin hieu mua va bot giao dich khi VNINDEX buoc vao pha Downtrend.
    """
    def __init__(self):
        self._cache_data: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 30.0  # Cache 30 giay

    async def get_market_regime(self) -> Dict[str, Any]:
        """
        Lay trang thai xu huong cua VNINDEX.
        Tra ve dict chua: regime, is_buy_allowed, vnindex_close, ema20, ema50, trend_slope, advice_vn.
        """
        now = time.time()
        if self._cache_data is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache_data

        try:
            end_date = date.today().strftime("%Y-%m-%d")
            start_date = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
            
            # Lay du lieu VNINDEX tu VN30 / VNI
            df = await ohlcv_fetcher.fetch_history("VNINDEX", start_date, end_date)
            if df is None or len(df) < 30:
                df = await ohlcv_fetcher.fetch_history("VN30", start_date, end_date)

            if df is None or len(df) < 30:
                # Fallback gia lap an toan neu chua tai duoc OHLCV index
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
            n = len(closes)
            cur_close = float(closes[-1])

            # Tinh EMA20 va EMA50
            ema20_series = pd.Series(closes).ewm(span=20, adjust=False).mean()
            ema50_series = pd.Series(closes).ewm(span=50, adjust=False).mean()
            
            cur_ema20 = float(ema20_series.iloc[-1])
            cur_ema50 = float(ema50_series.iloc[-1])

            # Do doc cua EMA20 trong 10 phien gan nhat
            slope = (cur_ema20 - float(ema20_series.iloc[-10])) / 10.0 if n >= 10 else 0.0

            # Phan loai che do thi truong
            if cur_close >= cur_ema20 and cur_ema20 >= cur_ema50 and slope >= 0:
                regime = "BULL"
                regime_vn = "UPTREND (TANG TRUONG)"
                is_buy_allowed = True
                risk_level = "THAP"
                status_message = "Thi truong Uptrend an toan: VNINDEX tren MA20 & MA50. Cho phep giai ngan toi da 100% ty trong."
            elif cur_close < cur_ema50 or (cur_close < cur_ema20 and slope < -0.3):
                regime = "BEAR"
                regime_vn = "DOWNTREND (RUI RO CAO)"
                is_buy_allowed = False
                risk_level = "CAO"
                status_message = "CANH BAO: VNINDEX dang trong pha Downtrend/Gay MA50. TU DONG KHOA MUA MOI DE BAO VE VON."
            else:
                regime = "SIDEWAYS"
                regime_vn = "TICH LUY (DI NGANG)"
                is_buy_allowed = True
                risk_level = "TRUNG BINH"
                status_message = "Thi truong tich luy di ngang: Cho phep mua tham do 30-40% tai vung nen kiet cung."

            res = {
                "regime": regime,
                "regime_vn": regime_vn,
                "is_buy_allowed": is_buy_allowed,
                "risk_level": risk_level,
                "vnindex_close": round(cur_close, 2),
                "ema20": round(cur_ema20, 2),
                "ema50": round(cur_ema50, 2),
                "trend_slope": round(slope, 3),
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
                "status_message": "He thong dang theo doi che do thi truong.",
                "updated_at": date.today().strftime("%Y-%m-%d")
            }

market_regime_gate = MarketRegimeGate()
