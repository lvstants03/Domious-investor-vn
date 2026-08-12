import logging
from typing import Tuple, Dict, Any, Optional
import pandas as pd
from src.strategies.base import BaseStrategy

logger = logging.getLogger("dominus-investor.strategies.rsi")

class RSIStrategy(BaseStrategy):
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("RSI", params)
        self.period = int(self.params.get("period", 14))
        self.oversold = float(self.params.get("oversold", 30.0))
        self.overbought = float(self.params.get("overbought", 70.0))
        self.volume_confirm = bool(self.params.get("volume_confirm", True))
        self.volume_multiplier = float(self.params.get("volume_multiplier", 1.5))

    def _calculate_rsi_fallback(self, close_series: pd.Series) -> pd.Series:
        delta = close_series.diff()
        gain = (delta.where(delta > 0, 0.0)).copy()
        loss = (-delta.where(delta < 0, 0.0)).copy()
        
        # Dung Wilder's Moving Average
        avg_gain = gain.rolling(window=self.period, min_periods=self.period).mean()
        avg_loss = loss.rolling(window=self.period, min_periods=self.period).mean()
        
        # Ap dung cong thuc lam muot Wilder
        for i in range(self.period, len(close_series)):
            avg_gain.iloc[i] = (avg_gain.iloc[i-1] * (self.period - 1) + gain.iloc[i]) / self.period
            avg_loss.iloc[i] = (avg_loss.iloc[i-1] * (self.period - 1) + loss.iloc[i]) / self.period
            
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def analyze(self, df: pd.DataFrame) -> Tuple[str, float, str, Dict[str, Any]]:
        if len(df) < self.period + 5:
            return "HOLD", 0.0, "Thieu du lieu lich su", {}

        close = df["close"]
        volume = df["volume"]
        
        # Tinh RSI
        try:
            import pandas_ta as ta
            rsi_series = ta.rsi(close, length=self.period)
            if rsi_series is None or rsi_series.empty:
                rsi_series = self._calculate_rsi_fallback(close)
        except Exception:
            rsi_series = self._calculate_rsi_fallback(close)

        current_rsi = float(rsi_series.iloc[-1])
        prev_rsi = float(rsi_series.iloc[-2])
        current_price = float(close.iloc[-1])
        
        # Tinh volume trung binh 20 phien
        vol_ma = volume.rolling(window=20).mean().iloc[-1]
        current_vol = volume.iloc[-1]

        indicators = {
            "rsi": round(current_rsi, 2),
            "prev_rsi": round(prev_rsi, 2),
            "volume_ma20": round(vol_ma, 1) if not pd.isna(vol_ma) else 0.0,
            "volume": int(current_vol)
        }

        # Kiem tra Volume Confirm neu duoc kich hoat
        vol_ok = True
        if self.volume_confirm and not pd.isna(vol_ma) and vol_ma > 0:
            vol_ok = current_vol > (vol_ma * self.volume_multiplier)

        # Xac dinh tin hieu
        if prev_rsi < self.oversold and current_rsi >= self.oversold:
            # RSI di len tu vung qua ban (Oversold Cross Up)
            if vol_ok:
                reason = f"RSI vuot len tu vung qua ban ({round(prev_rsi,1)} -> {round(current_rsi,1)}) kem volume confirm."
                return "BUY", 0.8, reason, indicators
            else:
                reason = f"RSI vuot len tu vung qua ban ({round(prev_rsi,1)} -> {round(current_rsi,1)}) nhung volume khong du confirm."
                return "HOLD", 0.3, reason, indicators
                
        elif prev_rsi > self.overbought and current_rsi <= self.overbought:
            # RSI di xuong tu vung qua mua (Overbought Cross Down)
            reason = f"RSI giam xuong tu vung qua mua ({round(prev_rsi,1)} -> {round(current_rsi,1)})."
            return "SELL", 0.8, reason, indicators

        # Truong hop dac biet: RSI cực kì thấp hoặc cực kì cao không cần cross
        if current_rsi < (self.oversold - 5) and vol_ok:
            return "BUY", 0.6, f"RSI hien tai rat thap ({round(current_rsi,1)}) - vung qua ban sau.", indicators
        elif current_rsi > (self.overbought + 5):
            return "SELL", 0.6, f"RSI hien tai rat cao ({round(current_rsi,1)}) - vung qua mua sau.", indicators

        return "HOLD", 0.0, "RSI o trang thai trung tinh", indicators

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "period": {"type": "integer", "default": 14, "description": "So phien tinh RSI"},
            "oversold": {"type": "number", "default": 30.0, "description": "Nguong qua ban (mua)"},
            "overbought": {"type": "number", "default": 70.0, "description": "Nguong qua mua (ban)"},
            "volume_confirm": {"type": "boolean", "default": True, "description": "Yeu cau confirm khoi luong dot bien"},
            "volume_multiplier": {"type": "number", "default": 1.5, "description": "Khoi luong gap X lan MA20"}
        }
