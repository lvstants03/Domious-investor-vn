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
            
            # 3. Diem Momentum/Trend (Trong so 0.2)
            # Tinh truc tiep dua tren percent_change tu price_info
            price_info = data.get("price_info", {})
            pct_change = price_info.get("percent_change", 0.0)
            momentum_score = 50.0 + (pct_change * 10.0)
            momentum_score = max(0.0, min(100.0, momentum_score))

            # 4. Tinh Composite Score (Diem tong hop)
            composite_score = (vol_score * 0.5) + (tech_score * 0.3) + (momentum_score * 0.2)
            
            detail_scores = {
                "volume_flow": round(vol_score, 1),
                "technical": round(tech_score, 1),
                "momentum": round(momentum_score, 1)
            }
            
            scored_list.append((symbol, round(composite_score, 2), detail_scores))

        # Sap xep giam dan theo diem composite
        scored_list.sort(key=lambda x: x[1], reverse=True)
        return scored_list

scorer = ScannerScorer()
