from typing import Dict, Any
from src.scanner.criteria.base import BaseCriterion

class VolumeFlowCriterion(BaseCriterion):
    def __init__(self):
        super().__init__("Volume & Flow", 0.3)

    def evaluate(self, symbol: str, data: Dict[str, Any]) -> float:
        price_info = data.get("price_info", {})
        foreign_info = data.get("foreign_info", {})
        
        score = 0.0
        
        # 1. Danh gia Volume dot bien (Hieu nang dong tien)
        # So sanh volume hien tai. Gia su ta lay tu price_info
        volume = price_info.get("volume", 0)
        
        # Thiet lap cac muc volume danh gia
        if volume > 2000000:  # Tren 2 Trieu co phieu khớp
            score += 50.0
        elif volume > 1000000:
            score += 35.0
        elif volume > 500000:
            score += 20.0
        else:
            score += 10.0

        # 2. Danh gia khoi ngoai mua rong (Foreign Net Buy)
        net_buy_val = foreign_info.get("net_buy_value", 0.0)
        
        if net_buy_val > 10000000000:  # Tren 10 Ty VND mua rong
            score += 50.0
        elif net_buy_val > 5000000000:  # Tren 5 Ty
            score += 40.0
        elif net_buy_val > 1000000000:  # Tren 1 Ty
            score += 30.0
        elif net_buy_val > 0:           # Mua rong duong
            score += 20.0
        elif net_buy_val < -5000000000: # Ban rong tren 5 Ty (Diem tru)
            score -= 10.0

        # Gioi han diem trong khoang [0.0, 100.0]
        return max(0.0, min(100.0, score))
