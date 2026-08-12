import logging
from typing import Tuple, Dict, Any
from src.database.models import Position, BotConfig

logger = logging.getLogger("dominus-investor.risk.manager")

class RiskManager:
    def check_stop_loss_take_profit(self, config: BotConfig, position: Position, current_price: float) -> Tuple[bool, str, str]:
        """
        Kiem tra vi the hien tai co cham cac nguong Cat lo / Chot loi khong.
        
        Returns:
            Tuple: (trigger_action, action_type, reason)
            - trigger_action: True neu can ban/dong vi the ngay
            - action_type: 'SELL' hoac 'HOLD'
            - reason: ly do kich hoat
        """
        if not position or position.quantity <= 0:
            return False, "HOLD", "Khong co vi the dang giu"

        avg_cost = position.avg_cost
        if avg_cost <= 0:
            return False, "HOLD", "Gia von khong hop le"

        # Tinh toan % thay doi gia hien tai so voi gia von
        change_pct = ((current_price - avg_cost) / avg_cost) * 100.0
        
        # 1. Kiem tra Cat lo (Stop Loss)
        # Nguoi dung truyen stop_loss_pct dang duong (vi du: 5.0 nghia la giam 5% cat lo)
        stop_loss_pct = abs(config.stop_loss_pct)
        if change_pct <= -stop_loss_pct:
            reason = f"Vi the ma {position.symbol} da cham nguong CAT LO: Giam {change_pct:.2f}% (Nguong: -{stop_loss_pct}%)."
            return True, "SELL", reason

        # 2. Kiem tra Chot loi (Take Profit)
        take_profit_pct = abs(config.take_profit_pct)
        if change_pct >= take_profit_pct:
            reason = f"Vi the ma {position.symbol} da cham nguong CHOT LOI: Tang +{change_pct:.2f}% (Nguong: +{take_profit_pct}%)."
            return True, "SELL", reason

        return False, "HOLD", f"Vi the an toan. Bien dong hien tai: {change_pct:+.2f}%",

    def validate_position_size(self, config: BotConfig, proposed_qty: int, price: float) -> bool:
        """Kiem tra xem quy mo lenh co vuot qua phan tram ngan sach cho phep khong"""
        max_order_val = config.budget * (config.position_size_pct / 100.0)
        proposed_val = proposed_qty * price
        
        # Cho phep sai lech nhe do lam tron lo 100 co phieu
        if proposed_val > (max_order_val * 1.15):
            logger.warning("Proposed size %s (val: %s) exceeds config limit %s", proposed_qty, proposed_val, max_order_val)
            return False
            
        return True

    def calculate_kelly_size(self, win_rate: float, win_loss_ratio: float) -> float:
        """
        Tinh ty le rui ro toi uu theo cong thuc Kelly (dung Half-Kelly de an toan).
        win_rate: 0.0 - 1.0 (vi du 0.55)
        win_loss_ratio: win_avg / loss_avg (vi du 2.0)
        """
        if win_rate <= 0 or win_loss_ratio <= 0:
            return 0.015  # Rui ro mac dinh 1.5%

        kelly = win_rate - (1.0 - win_rate) / win_loss_ratio
        safe_kelly = kelly * 0.5
        
        # Gioi han muc rui ro trong khoang 1% - 5% tai san
        return max(0.01, min(0.05, safe_kelly))

    def calculate_position_size(self, equity: float, risk_pct: float, atr: float, price: float, multiplier: float = 2.0) -> int:
        """
        Tinh khoi luong co phieu mua dua tren ATR.
        equity: Tong so du tai khoan
        risk_pct: Ty le rui ro chiu dung cho moi trade (0.01 - 0.05)
        atr: Chi bao ATR(14)
        price: Gia co phieu hien tai
        """
        if atr <= 0 or price <= 0 or equity <= 0:
            return 0

        risk_value = equity * risk_pct
        stop_loss_dist = atr * multiplier

        if stop_loss_dist <= 0:
            return 0

        qty = int(risk_value / stop_loss_dist)
        
        # Lam tron ve lo 100
        qty = (qty // 100) * 100

        # Gioi han vi the khong vuot qua 20% equity de dam bao da dang hoa danh muc
        max_qty = int((equity * 0.20) / price / 100) * 100

        return min(qty, max_qty)

    def allocate_positions(self, symbol: str, total_qty: int) -> dict:
        """
        Chia khoi luong thanh 3 vi the A/B/C theo ke hoach:
        - Vi the A (40%): Mua ngay tai Spring.
        - Vi the B (40%): Mua gia tang khi xac nhan MA20.
        - Vi the C (20%): Mua luot ngan han T+ khi retest.
        """
        qty_a = (int(total_qty * 0.4) // 100) * 100
        qty_b = (int(total_qty * 0.4) // 100) * 100
        qty_c = total_qty - qty_a - qty_b

        qty_c = (qty_c // 100) * 100

        return {
            "symbol": symbol,
            "total_qty": qty_a + qty_b + qty_c,
            "position_a_qty": qty_a,
            "position_b_qty": qty_b,
            "position_c_qty": qty_c
        }
