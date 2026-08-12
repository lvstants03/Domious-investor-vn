import logging
from typing import Tuple, Dict, Any, Optional
import pandas as pd
from src.strategies.base import BaseStrategy

logger = logging.getLogger("dominus-investor.strategies.bollinger")

class BollingerBandsStrategy(BaseStrategy):
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("BollingerBands", params)
        self.period = int(self.params.get("period", 20))
        self.std_dev = float(self.params.get("std_dev", 2.0))
        self.rsi_period = int(self.params.get("rsi_period", 14))

    def _calculate_rsi(self, close_series: pd.Series) -> pd.Series:
        delta = close_series.diff()
        gain = (delta.where(delta > 0, 0.0)).copy()
        loss = (-delta.where(delta < 0, 0.0)).copy()
        avg_gain = gain.rolling(window=self.rsi_period).mean()
        avg_loss = loss.rolling(window=self.rsi_period).mean()
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def analyze(self, df: pd.DataFrame) -> Tuple[str, float, str, Dict[str, Any]]:
        needed_len = max(self.period, self.rsi_period) + 5
        if len(df) < needed_len:
            return "HOLD", 0.0, "Thieu du lieu lich su", {}

        close = df["close"]
        
        # Tinh toan Bollinger Bands
        sma = close.rolling(window=self.period).mean()
        rstd = close.rolling(window=self.period).std()
        upper_band = sma + (self.std_dev * rstd)
        lower_band = sma - (self.std_dev * rstd)

        # Tinh RSI de confirm
        rsi_series = self._calculate_rsi(close)

        curr_price = float(close.iloc[-1])
        curr_upper = float(upper_band.iloc[-1])
        curr_lower = float(lower_band.iloc[-1])
        curr_sma = float(sma.iloc[-1])
        curr_rsi = float(rsi_series.iloc[-1])

        indicators = {
            "price": curr_price,
            "upper_band": round(curr_upper, 1),
            "lower_band": round(curr_lower, 1),
            "middle_band": round(curr_sma, 1),
            "rsi": round(curr_rsi, 1) if not pd.isna(curr_rsi) else 50.0
        }

        # Kiem tra tin hieu Mua (Cham Lower Band & RSI < 40)
        if curr_price <= curr_lower:
            if not pd.isna(curr_rsi) and curr_rsi < 40:
                reason = f"Gia cham bang duoi ({round(curr_price,1)} <= {round(curr_lower,1)}) kem tin hieu RSI qua ban ({round(curr_rsi,1)} < 40)."
                return "BUY", 0.85, reason, indicators
            else:
                reason = f"Gia cham bang duoi nhung RSI chua dong thuan ({round(curr_rsi,1)} >= 40)."
                return "HOLD", 0.2, reason, indicators

        # Kiem tra tin hieu Ban (Cham Upper Band & RSI > 60)
        elif curr_price >= curr_upper:
            if not pd.isna(curr_rsi) and curr_rsi > 60:
                reason = f"Gia cham bang tren ({round(curr_price,1)} >= {round(curr_upper,1)}) kem tin hieu RSI qua mua ({round(curr_rsi,1)} > 60)."
                return "SELL", 0.85, reason, indicators
            else:
                reason = f"Gia cham bang tren nhung RSI chua dong thuan ({round(curr_rsi,1)} <= 60)."
                return "HOLD", 0.2, reason, indicators

        return "HOLD", 0.0, "Gia dao dong trong vung Bollinger Bands", indicators

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "period": {"type": "integer", "default": 20, "description": "Chu ky SMA cho Bollinger Bands"},
            "std_dev": {"type": "number", "default": 2.0, "description": "He so do lech chuan (Standard Deviation)"},
            "rsi_period": {"type": "integer", "default": 14, "description": "Chu ky RSI bo tro confirm"}
        }
