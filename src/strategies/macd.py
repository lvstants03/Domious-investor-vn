import logging
from typing import Tuple, Dict, Any, Optional
import pandas as pd
from src.strategies.base import BaseStrategy

logger = logging.getLogger("dominus-investor.strategies.macd")

class MACDStrategy(BaseStrategy):
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("MACD", params)
        self.fast = int(self.params.get("fast", 12))
        self.slow = int(self.params.get("slow", 26))
        self.signal = int(self.params.get("signal", 9))

    def _calculate_macd_fallback(self, close_series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = close_series.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close_series.ewm(span=self.slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def analyze(self, df: pd.DataFrame) -> Tuple[str, float, str, Dict[str, Any]]:
        if len(df) < self.slow + self.signal:
            return "HOLD", 0.0, "Thieu du lieu lich su", {}

        close = df["close"]
        
        try:
            import pandas_ta as ta
            # Tinh toan bang pandas_ta
            macd_df = ta.macd(close, fast=self.fast, slow=self.slow, signal=self.signal)
            if macd_df is None or macd_df.empty:
                macd_line, signal_line, hist = self._calculate_macd_fallback(close)
            else:
                # pandas_ta dat ten cot theo dinh dang: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
                macd_line = macd_df.iloc[:, 0]
                hist = macd_df.iloc[:, 1]
                signal_line = macd_df.iloc[:, 2]
        except Exception:
            macd_line, signal_line, hist = self._calculate_macd_fallback(close)

        curr_macd = float(macd_line.iloc[-1])
        prev_macd = float(macd_line.iloc[-2])
        curr_sig = float(signal_line.iloc[-1])
        prev_sig = float(signal_line.iloc[-2])
        curr_hist = float(hist.iloc[-1])
        prev_hist = float(hist.iloc[-2])

        indicators = {
            "macd": round(curr_macd, 3),
            "signal": round(curr_sig, 3),
            "histogram": round(curr_hist, 3),
            "prev_histogram": round(prev_hist, 3)
        }

        # Kiem tra giao cat Golden Cross (MACD vuot Signal - Hist tu am sang duong)
        if prev_hist <= 0 < curr_hist:
            # Golden cross
            reason = f"MACD Golden Cross: MACD line cat len tren Signal line (Hist: {round(prev_hist,3)} -> {round(curr_hist,3)})."
            confidence = 0.8
            # Tang do tin cay neu diem giao cat o duoi truc 0 (vung gia thap/tich luy)
            if curr_macd < 0:
                confidence = 0.85
                reason += " Diem giao cat duoi duong 0 (tin hieu manh)."
            return "BUY", confidence, reason, indicators

        # Kiem tra giao cat Death Cross (MACD xuong duoi Signal - Hist tu duong sang am)
        elif prev_hist >= 0 > curr_hist:
            # Death cross
            reason = f"MACD Death Cross: MACD line cat xuong duoi Signal line (Hist: {round(prev_hist,3)} -> {round(curr_hist,3)})."
            confidence = 0.8
            if curr_macd > 0:
                confidence = 0.85
                reason += " Diem giao cat tren duong 0 (tin hieu manh)."
            return "SELL", confidence, reason, indicators

        return "HOLD", 0.0, "MACD khong co tin hieu giao cat", indicators

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "fast": {"type": "integer", "default": 12, "description": "Chu ky EMA nhanh"},
            "slow": {"type": "integer", "default": 26, "description": "Chu ky EMA cham"},
            "signal": {"type": "integer", "default": 9, "description": "Chu ky duong Signal"}
        }
