from typing import Dict, Any
from src.scanner.criteria.base import BaseCriterion

class TechnicalCriterion(BaseCriterion):
    def __init__(self):
        super().__init__("Technical Indicators", 0.4)

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> float:
        price_info = data.get("price_info", {})
        
        score = 50.0  # Diem trung tinh
        
        # Dan gia tren thay doi gia (% change)
        pct_change = price_info.get("percent_change", 0.0)
        
        # Bien do tang gia tot, the hien xu huong ky thuat khoe
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

        # Gia su ho tro lay them du lieu tu tin hieu RSI gia lap neu khong co DB o day
        # De don gian hoa và dam bao toc do quet, ta dung pct_change de phan anh suc manh xu huong
        return max(0.0, min(100.0, score))
