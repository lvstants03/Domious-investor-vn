from typing import Dict, Any
import pandas as pd
from src.scanner.criteria.base import BaseCriterion
from src.data_pipeline.indicators import indicators

class TechnicalCriterion(BaseCriterion):
    def __init__(self):
        super().__init__("Technical Indicators", 0.4)

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> float:
        price_info = data.get("price_info", {})
        ohlcv = data.get("ohlcv")
        
        score = 50.0  # Diem trung tinh
        
        # 1. Tinh diem tu chi bao ky thuat thuc te (RSI, MACD, Abnormal Return)
        has_indicators = False
        if ohlcv is not None and isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty and len(ohlcv) >= 30:
            try:
                close_series = ohlcv["close"].astype(float)
                rsi = indicators.rsi_latest(close_series)
                abnormal = indicators.calculate_abnormal_return(close_series, period=10)
                
                tech_points = 50.0
                # RSI trong vung 45-65: Tich luy tot
                if rsi is not None:
                    if 45.0 <= rsi <= 65.0:
                        tech_points += 20.0
                    elif rsi > 75.0: # Qua mua (Giam diem)
                        tech_points -= 15.0
                    elif rsi < 30.0: # Qua ban
                        tech_points += 10.0
                        
                # Abnormal Return truoc tin tuc
                if abnormal is not None:
                    # Neu Abnormal Return tang qua nong (> 4%) truoc tin -> Tin da bi ro ri, duoi theo rui ro
                    if abnormal > 4.0:
                        tech_points -= 10.0
                    # Neu Abnormal Return on dinh gan 0 -> Tin that, mua an toan
                    elif -1.0 <= abnormal <= 1.5:
                        tech_points += 15.0
                        
                score = tech_points
                has_indicators = True
            except Exception:
                pass
                
        if not has_indicators:
            # Fallback dua tren percent_change phien hom nay
            pct_change = price_info.get("percent_change", 0.0)
            if 1.0 <= pct_change < 3.0:
                score += 20.0
            elif 3.0 <= pct_change < 5.0:
                score += 35.0
            elif pct_change >= 5.0:
                score += 45.0
            elif -2.0 <= pct_change < 0.0:
                score -= 10.0
            elif pct_change < -2.0:
                score -= 20.0

        return max(0.0, min(100.0, score))
