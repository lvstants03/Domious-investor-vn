from typing import Dict, Any
import pandas as pd
from src.scanner.criteria.base import BaseCriterion
from src.data_pipeline.indicators import indicators

class VolumeFlowCriterion(BaseCriterion):
    def __init__(self):
        super().__init__("Volume & Flow", 0.3)

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> float:
        price_info = data.get("price_info", {})
        foreign_info = data.get("foreign_info", {})
        ohlcv = data.get("ohlcv")
        
        score = 0.0
        
        # 1. Danh gia Volume dot bien (Z-Score 50 phien)
        has_z_score = False
        if ohlcv is not None and isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty and len(ohlcv) >= 30:
            try:
                # Tinh Z-Score 50 phien
                vol_series = ohlcv["volume"].astype(float)
                z_score = indicators.z_score_latest(vol_series, period=50)
                if z_score is not None:
                    has_z_score = True
                    # Z-Score > 3: 60 diem (Dot bien cực mạnh)
                    # Z-Score > 1.5: 45 diem
                    # Z-Score > 0: 30 diem
                    # Z-Score <= 0: 15 diem
                    if z_score > 3.0:
                        score += 60.0
                    elif z_score > 1.5:
                        score += 45.0
                    elif z_score > 0:
                        score += 30.0
                    else:
                        score += 15.0
            except Exception:
                pass

        if not has_z_score:
            # Fallback neu khong co ohlcv hoac tinh loi
            volume = price_info.get("volume", 0)
            if volume > 2000000:
                score += 50.0
            elif volume > 1000000:
                score += 35.0
            elif volume > 500000:
                score += 20.0
            else:
                score += 10.0

        # 2. Danh gia khoi ngoai mua rong (Foreign Net Buy) - Chiếm 40% trong so
        net_buy_val = foreign_info.get("net_buy_value", 0.0)
        
        if net_buy_val > 10000000000:  # Tren 10 Ty VND mua rong
            score += 40.0
        elif net_buy_val > 5000000000:  # Tren 5 Ty
            score += 30.0
        elif net_buy_val > 1000000000:  # Tren 1 Ty
            score += 20.0
        elif net_buy_val > 0:           # Mua rong duong
            score += 10.0
        elif net_buy_val < -5000000000: # Ban rong tren 5 Ty (Diem tru)
            score -= 10.0

        # Gioi han diem trong khoang [0.0, 100.0]
        return max(0.0, min(100.0, score))
