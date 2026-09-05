import logging
from typing import Dict, Any, List, Tuple
from src.scanner.criteria.volume_flow import VolumeFlowCriterion
from src.scanner.criteria.technical import TechnicalCriterion

logger = logging.getLogger("dominus-investor.scanner.scorer")

class ScannerScorer:
    def __init__(self):
        self.volume_criterion = VolumeFlowCriterion()
        self.technical_criterion = TechnicalCriterion()

    def score_all(self, all_data: Dict[str, Dict[str, Any]]) -> List[Tuple[str, float, Dict[str, float]]]:
        """
        Tinh toan composite score cho tat ca cac co phieu dua tren du lieu quet duoc.
        
        Returns:
            Danh sach cac tuple: (symbol, composite_score, detail_scores)
            duoc sap xep giam dan theo composite_score.
        """
        scored_list = []

        for symbol, data in all_data.items():
            # 1. Tinh diem Volume & Flow (Trong so 0.5 - Uu tien cao nhat)
            vol_score = self.volume_criterion.evaluate(symbol, data)
            
            # 2. Tinh diem Technical (Trong so 0.3)
            tech_score = self.technical_criterion.evaluate(symbol, data)
            
            # FIX: lay foreign_info tu data dict dung scope
            foreign_info = data.get("foreign_info", {}) if isinstance(data, dict) else {}

            # 3. Diem Momentum/Trend (Trong so 0.2)
            # Diem co ban
            wyckoff_score = 60.0
            ohlcv = data.get("ohlcv")
            if ohlcv is not None and not ohlcv.empty:
                try:
                    close_prices = ohlcv["close"].astype(float)
                    ma200 = close_prices.rolling(200, min_periods=30).mean().iloc[-1]
                    last_close = close_prices.iloc[-1]
                    if ma200 > 0:
                        dist = abs(last_close - ma200) / ma200
                        if dist <= 0.05:
                            wyckoff_score = 85.0
                        elif dist <= 0.10:
                            wyckoff_score = 75.0
                except Exception:
                    pass

            inst_score = 50.0
            net_buy_val = float(foreign_info.get("net_buy_value", 0.0))
            if net_buy_val > 5000000000:
                inst_score = 85.0
            elif net_buy_val > 1000000000:
                inst_score = 70.0
            elif net_buy_val < -5000000000:
                inst_score = 20.0


            # 4. Tinh Confidence Score moi: (0.4 * Wyckoff_Base_Score) + (0.3 * Volume_ZScore) + (0.2 * Institutional_Flow_Score) + (0.1 * Sentiment_Score)
            sentiment_score = 50.0
            composite_score = (0.4 * wyckoff_score) + (0.3 * vol_score) + (0.2 * inst_score) + (0.1 * sentiment_score)
            
            detail_scores = {
                "volume_flow": round(vol_score, 1),
                "technical": round(tech_score, 1),
                "momentum": round(composite_score, 1)
            }
            
            scored_list.append((symbol, round(composite_score, 2), detail_scores))

        # Sap xep giam dan theo diem composite
        scored_list.sort(key=lambda x: x[1], reverse=True)
        return scored_list

scorer = ScannerScorer()
