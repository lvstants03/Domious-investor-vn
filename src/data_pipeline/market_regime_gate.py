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
                    timeout=7.0
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug("Fetch VNINDEX timeout/err: %s", e)
                df = None

            if df is None or len(df) < 30:
                try:
                    df = await asyncio.wait_for(
                        ohlcv_fetcher.fetch_history("VN30", start_date, end_date),
                        timeout=5.0
                    )
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug("Fetch VN30 timeout/err: %s", e)
                    df = None

            if df is None or len(df) < 30:
                # Neu da co cache du lieu that truoc do thi giu nguyen
                if self._cache_data is not None and self._cache_data.get("vnindex_close", 0) > 0:
                    return self._cache_data

                # Khong luu vao self._cache_data de lan sau thu lai ngay
                return {
                    "regime": "UPDATING",
                    "regime_vn": "DANG CAP NHAT",
                    "is_buy_allowed": True,
                    "risk_level": "TRUNG BINH",
                    "vnindex_close": 0.0,
                    "ema20": 0.0,
                    "ema50": 0.0,
                    "trend_slope": 0.0,
                    "status_message": "Dang dong bo du lieu nen VN-INDEX tu so giao dich.",
                    "updated_at": date.today().strftime("%Y-%m-%d")
                }

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
                regime_vn = "PHÂN PHỐI ĐỈNH (CẢNH BÁO SẮP DOWNTREND)"
                is_buy_allowed = False
                risk_level = "CAO"
                status_message = "CẢNH BÁO SỚM: VNINDEX xuất hiện tín hiệu phân phối vùng đỉnh (RSI quá mua + dòng tiền chốt lời). Đề xuất hạ tỷ trọng, chủ động chốt lời bảo toàn vốn."
            # 2. ACCUMULATION EARLY (Tich luy day - Canh bao sap Uptrend)
            elif cur_close < cur_ema50 and rsi < 40 and slope > -0.1:
                regime = "ACCUMULATION_EARLY"
                regime_vn = "TÍCH LŨY ĐÁY (CẢNH BÁO SẮP UPTREND)"
                is_buy_allowed = True
                risk_level = "THẤP"
                status_message = "CƠ HỘI CHÂN SÓNG: VNINDEX tạo đáy tích lũy cạn cung. Cho phép mua gom thăm dò 30% - 40% ở các mã dẫn sóng."
            # 3. SPRING REBOUND (Dao chieu rut chan ky thuat)
            elif cur_close < cur_ema50 and (cur_close > float(lows[-1]) * 1.015) and rsi < 35:
                regime = "SPRING_REBOUND"
                regime_vn = "PHỤC HỒI CHÂN SÓNG (RÚT CHÂN ĐẢO CHIỀU)"
                is_buy_allowed = True
                risk_level = "TRUNG BÌNH"
                status_message = "Tín hiệu bắt đáy Spring: Thị trường rũ bỏ thành công và rút chân mạnh. Cho phép mua lướt T+ tỷ trọng nhỏ 15-20%."
            # 4. BULL MARKUP (Uptrend bung no)
            elif cur_close >= cur_ema20 and cur_ema20 >= cur_ema50 and slope >= 0:
                regime = "BULL"
                regime_vn = "UPTREND (TĂNG TRƯỞNG BÙNG NỔ)"
                is_buy_allowed = True
                risk_level = "THẤP"
                status_message = "Thị trường Uptrend an toàn: VNINDEX trên MA20 & MA50. Cho phép giải ngân tối đa 100% tỷ trọng."
            # 5. BEAR DOWNTREND (Downtrend gay MA50)
            elif cur_close < cur_ema50 and slope < -0.2:
                regime = "BEAR"
                regime_vn = "DOWNTREND (RỦI RO CAO)"
                is_buy_allowed = False
                risk_level = "CAO"
                status_message = "CẢNH BÁO: VNINDEX đang trong pha Downtrend/Gãy MA50. TỰ ĐỘNG KHÓA MUA MỚI ĐỂ BẢO VỆ VỐN."
            # 6. RE_ACCUMULATION (Tai tich luy giu MA20)
            else:
                regime = "RE_ACCUMULATION"
                regime_vn = "TÁI TÍCH LŨY (GIỮ VỮNG MA20)"
                is_buy_allowed = True
                risk_level = "TRUNG BÌNH"
                status_message = "Thị trường tái tích lũy: VNINDEX kiểm định vùng hỗ trợ MA20. Cho phép mua gia tăng khi test cung thành công."

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
            if self._cache_data is not None and self._cache_data.get("vnindex_close", 0) > 0:
                return self._cache_data
            return {
                "regime": "UPDATING",
                "regime_vn": "ĐANG CẬP NHẬT",
                "is_buy_allowed": True,
                "risk_level": "TRUNG BÌNH",
                "vnindex_close": 0.0,
                "ema20": 0.0,
                "ema50": 0.0,
                "trend_slope": 0.0,
                "rsi": 50.0,
                "status_message": "Đang khởi tạo dữ liệu chỉ số VN-INDEX.",
                "updated_at": date.today().strftime("%Y-%m-%d")
            }

market_regime_gate = MarketRegimeGate()
