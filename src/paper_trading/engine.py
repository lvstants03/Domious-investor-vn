import logging
from datetime import date, timedelta
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from src.database.models import WyckoffSignal, PaperTrade, OHLCVDaily
from src.data_pipeline.sector_flow_calculator import sector_calculator
from src.paper_trading.sector_exposure import sector_exposure_guard

logger = logging.getLogger("dominus-investor.paper_trading.engine")

PAPER_BUDGET_PER_TRADE = 50_000_000   # 50 trieu moi lenh gia lap
PAPER_STOP_LOSS_BUFFER = 0.005        # Them 0.5% buffer vao stop loss


class PaperTradingEngine:
    """
    Giao dich gia lap (Paper Trading) dua tren tin hieu Wyckoff.
    
    Quy tac:
    - Moi tin hieu Wyckoff hop le (R/R >= 2.0) duoc tu dong tao 1 lenh ao
    - Mua tai Entry Standard (Open T+1 sau tin hieu)
    - Theo doi hang ngay, cap nhat trang thai: OPEN -> CLOSED_WIN/LOSS/EXPIRED
    - Lenh het han sau 30 phien neu chua cham Target hoac StopLoss
    """

    # Vi the nam giu theo quy: 1 - 3 thang (~60 phien)
    MAX_HOLDING_DAYS = 60

    async def create_paper_trade_from_signal(
        self, signal: WyckoffSignal, db_session=None
    ) -> Optional[dict]:
        """
        Tao lenh gia lap tu WyckoffSignal cho vi the quy (1-3 thang).
        Tra ve dict du lieu de luu vao DB, hoac None neu tin hieu khong du tieu chuan.
        
        Kiem tra:
        1. R/R >= 2.5 (chuan vi the quy)
        2. Sector Exposure <= 40% NAV (SectorExposureGuard)
        """
        if signal is None:
            return None

        # Chi tao lenh neu R/R >= 2.5
        if (signal.rr_ratio or 0) < 2.5:
            logger.info("Bo qua tin hieu %s - R/R = %.2f < 2.5", signal.symbol, signal.rr_ratio or 0)
            return None

        entry_price = signal.entry_standard or signal.entry_aggressive
        if not entry_price or entry_price <= 0:
            return None

        # Kiem tra Sector Exposure truoc khi mo lenh
        sector = sector_calculator.get_sector_for_symbol(signal.symbol)
        # Vi the quy: Cat lo theo cau truc ~9%, muc tieu song quy +30%
        stop_loss = signal.stop_loss or (entry_price * 0.91)
        target_price = signal.target_price or (entry_price * 1.30)

        quantity = int(PAPER_BUDGET_PER_TRADE / entry_price / 100) * 100
        if quantity <= 0:
            return None

        proposed_value = entry_price * quantity
        can_open, reason = await sector_exposure_guard.can_open_position(
            signal.symbol, sector, proposed_value, db_session
        )
        if not can_open:
            logger.info("[SectorGuard] Bo qua %s: %s", signal.symbol, reason)
            return None

        return {
            "signal_id": signal.id,
            "symbol": signal.symbol,
            "entry_date": signal.signal_date + timedelta(days=1),  # Mua ngay T+1
            "entry_price": entry_price,
            "quantity": quantity,
            "stop_loss": stop_loss * (1 - PAPER_STOP_LOSS_BUFFER),
            "target_price": target_price,
            "status": "OPEN",
            "trailing_stop_pct": 12.0,   # Trailing 12% tu dinh phu hop song quy
        }

    def update_paper_trades(
        self,
        open_trades: List[PaperTrade],
        latest_prices: Dict[str, float],
        today: date
    ) -> List[dict]:
        """
        Cap nhat trang thai cac lenh OPEN dua tren gia dong cua moi nhat.
        
        Tra ve danh sach dict voi cac lenh can UPDATE trong DB.
        """
        updates = []

        for trade in open_trades:
            if trade.symbol not in latest_prices:
                continue

            current_price = latest_prices[trade.symbol]
            days_held = (today - trade.entry_date).days

            update = {"id": trade.id}

            if current_price <= trade.stop_loss:
                pnl_pct = round((current_price - trade.entry_price) / trade.entry_price * 100, 2)
                update.update({
                    "status": "CLOSED_LOSS",
                    "exit_date": today,
                    "exit_price": current_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "STOP_LOSS"
                })
                logger.info("Paper Trade %s DONG (LOSS): %.2f%%", trade.symbol, pnl_pct)

            elif current_price >= trade.target_price:
                pnl_pct = round((current_price - trade.entry_price) / trade.entry_price * 100, 2)
                update.update({
                    "status": "CLOSED_WIN",
                    "exit_date": today,
                    "exit_price": current_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "TAKE_PROFIT"
                })
                logger.info("Paper Trade %s DONG (WIN): +%.2f%%", trade.symbol, pnl_pct)

            elif days_held >= self.MAX_HOLDING_DAYS:
                pnl_pct = round((current_price - trade.entry_price) / trade.entry_price * 100, 2)
                update.update({
                    "status": "CLOSED_EXPIRED",
                    "exit_date": today,
                    "exit_price": current_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": "EXPIRED"
                })
                logger.info("Paper Trade %s HET HAN: %.2f%%", trade.symbol, pnl_pct)

            if len(update) > 1:
                updates.append(update)

        return updates

    def calculate_pnl_summary(self, closed_trades: List[PaperTrade]) -> dict:
        """
        Tinh toan tong ket hieu suat paper trading.
        So sanh voi VNI Alpha.
        """
        if not closed_trades:
            return {
                "total_trades": 0, "win_rate": 0.0, "avg_pnl_pct": 0.0,
                "total_return_pct": 0.0, "best_trade": None, "worst_trade": None
            }

        pnl_pcts = [t.pnl_pct for t in closed_trades if t.pnl_pct is not None]
        if not pnl_pcts:
            return {"total_trades": len(closed_trades), "win_rate": 0.0, "avg_pnl_pct": 0.0,
                    "total_return_pct": 0.0, "best_trade": None, "worst_trade": None}

        wins = [t for t in closed_trades if (t.pnl_pct or 0) > 0]
        win_rate = round(len(wins) / len(closed_trades) * 100, 1)
        avg_pnl = round(float(np.mean(pnl_pcts)), 2)

        # Tinh tong return kep (compound)
        equity = 100.0
        for p in pnl_pcts:
            equity *= (1 + p / 100)
        total_return = round(equity - 100.0, 2)

        best = max(closed_trades, key=lambda t: t.pnl_pct or -999)
        worst = min(closed_trades, key=lambda t: t.pnl_pct or 999)

        return {
            "total_trades": len(closed_trades),
            "win_rate": win_rate,
            "avg_pnl_pct": avg_pnl,
            "total_return_pct": total_return,
            "best_trade": {"symbol": best.symbol, "pnl_pct": best.pnl_pct},
            "worst_trade": {"symbol": worst.symbol, "pnl_pct": worst.pnl_pct}
        }


paper_engine = PaperTradingEngine()
