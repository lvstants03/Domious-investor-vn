import logging
from typing import Tuple, Dict, Any, Optional
import pandas as pd
from src.strategies.base import BaseStrategy

logger = logging.getLogger("dominus-investor.strategies.ma_volume")

class MAVolumeStrategy(BaseStrategy):
    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("MA_Volume", params)
        self.fast_period = int(self.params.get("fast_period", 5))
        self.slow_period = int(self.params.get("slow_period", 20))
        self.vol_period = int(self.params.get("vol_period", 20))
        self.vol_multiplier = float(self.params.get("vol_multiplier", 1.5))

    def analyze(self, df: pd.DataFrame) -> Tuple[str, float, str, Dict[str, Any]]:
        needed_len = max(self.slow_period, self.vol_period) + 5
        if len(df) < needed_len:
            return "HOLD", 0.0, "Thieu du lieu lich su", {}

        close = df["close"]
        volume = df["volume"]

        # Tinh toan Moving Averages
        ma_fast = close.rolling(window=self.fast_period).mean()
        ma_slow = close.rolling(window=self.slow_period).mean()
        ma_vol = volume.rolling(window=self.vol_period).mean()

        # Gia tri hien tai
        curr_fast = float(ma_fast.iloc[-1])
        prev_fast = float(ma_fast.iloc[-2])
        curr_slow = float(ma_slow.iloc[-1])
        prev_slow = float(ma_slow.iloc[-2])
        
        curr_vol = float(volume.iloc[-1])
        curr_vol_ma = float(ma_vol.iloc[-1])

        indicators = {
            "ma_fast": round(curr_fast, 1),
            "ma_slow": round(curr_slow, 1),
            "volume": int(curr_vol),
            "volume_ma": round(curr_vol_ma, 1)
        }

        # Kiem tra giao cat tang gia (Fast cat len tren Slow) kem theo Volume
        is_golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
        is_vol_surge = curr_vol > (curr_vol_ma * self.vol_multiplier)

        if is_golden_cross:
            if is_vol_surge:
                reason = f"MA Cross Up (MA{self.fast_period} > MA{self.slow_period}) kem theo khoi luong dot bien ({int(curr_vol)} > {int(curr_vol_ma * self.vol_multiplier)})."
                return "BUY", 0.9, reason, indicators
            else:
                reason = f"MA Cross Up nhung khoi luong khong dat tieu chuan dot bien ({int(curr_vol)} <= {int(curr_vol_ma * self.vol_multiplier)})."
                return "HOLD", 0.3, reason, indicators

        # Kiem tra giao cat giam gia (Fast cat xuong Slow)
        is_death_cross = prev_fast >= prev_slow and curr_fast < curr_slow
        if is_death_cross:
            reason = f"MA Cross Down (MA{self.fast_period} < MA{self.slow_period}) - tin hieu ban."
            return "SELL", 0.85, reason, indicators

        return "HOLD", 0.0, "MA song song, khong co tin hieu giao cat", indicators

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "fast_period": {"type": "integer", "default": 5, "description": "Chu ky MA nhanh (vi du: MA5)"},
            "slow_period": {"type": "integer", "default": 20, "description": "Chu ky MA cham (vi du: MA20)"},
            "vol_period": {"type": "integer", "default": 20, "description": "Chu ky MA cho khoi luong"},
            "vol_multiplier": {"type": "number", "default": 1.5, "description": "He so dot bien khoi luong"}
        }
