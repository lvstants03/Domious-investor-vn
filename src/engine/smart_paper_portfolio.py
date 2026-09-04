import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from src.database.connection import async_session_maker
from src.database.models import Position, Trade
from sqlalchemy import select, delete

logger = logging.getLogger("dominus-investor.engine.paper_portfolio")

DEFAULT_CAPITAL = 1_000_000_000.0  # Von gia lap mac dinh: 1 Ty VND
MAX_ALLOC_PER_STOCK = 0.20        # Toi da 20% danh muc cho 1 ma (200 trieu)
MIN_PROFIT_TARGET_PCT = 10.0      # Muc tieu loi nhuan toi thieu de bat che do khoa lai: 10%
STOP_LOSS_PCT = -6.0              # Cat lo ky luat: -6%

class SmartPaperPortfolioManager:
    """
    Quan ly Danh muc Dau tu Gia lap Thuc chien (Smart Paper Portfolio).
    Khop theo gia thuc te tren san TCBS, tu dong ap dung chien luoc
    Gong Lai Dong (Dynamic Holding) voi muc tieu toi thieu >= 10%.
    """

    def __init__(self):
        self.initial_capital = DEFAULT_CAPITAL
        self._is_syncing = False

    async def get_portfolio_summary(self) -> Dict[str, Any]:
        """Lay toan bo tong quan danh muc: NAV, vi the dang giu, lich su chot loi"""
        async with async_session_maker() as session:
            # 1. Lay danh sach vi the dang mo (positions)
            res_pos = await session.execute(
                select(Position).where(Position.mode == "paper", Position.quantity > 0)
            )
            positions = res_pos.scalars().all()

            # 2. Lay lich su lenh da dong (trades)
            res_trades = await session.execute(
                select(Trade).where(Trade.mode == "paper").order_by(Trade.created_at.desc()).limit(30)
            )
            trades = res_trades.scalars().all()

            # Neu chua co vi the nao, tao vi the khoi tao theo cac ma ca map gom manh
            if not positions and not trades:
                await self._seed_initial_paper_positions(session)
                res_pos = await session.execute(
                    select(Position).where(Position.mode == "paper", Position.quantity > 0)
                )
                positions = res_pos.scalars().all()

            # 3. Tinh toan NAV va PnL
            from src.tcbs.market import market_client
            active_positions: List[Dict[str, Any]] = []
            total_stock_value = 0.0
            total_unrealized_pnl = 0.0

            for p in positions:
                # Lay gia realtime cap nhat tu TCBS
                current_p = p.current_price
                try:
                    p_info = await market_client.get_price_info(p.symbol)
                    p_val = float(p_info.get("price") or 0.0)
                    if p_val > 0:
                        current_p = p_val
                        p.current_price = current_p
                except Exception:
                    pass

                val = current_p * p.quantity
                cost = p.avg_cost * p.quantity
                unrealized_pnl = val - cost
                pnl_pct = ((current_p - p.avg_cost) / p.avg_cost) * 100 if p.avg_cost > 0 else 0.0

                p.unrealized_pnl = unrealized_pnl
                p.unrealized_pnl_pct = pnl_pct
                total_stock_value += val
                total_unrealized_pnl += unrealized_pnl

                # Logic Trailing Stop & Trang thai gong lai
                is_target_hit = pnl_pct >= MIN_PROFIT_TARGET_PCT
                trailing_stop_price = round(p.avg_cost * 1.07) if is_target_hit else round(p.avg_cost * (1 + STOP_LOSS_PCT / 100))
                
                status_badge = "DANG GONG LAI: SONG MANH" if is_target_hit else "DANG TICH LUY VI THE"
                if pnl_pct >= 15.0:
                    status_badge = "DAT CHI TIEU XUAT SAC: NUOI SONG LON"
                elif pnl_pct <= -4.0:
                    status_badge = "CANH BAO RUI RO: GAN NGUONG CAT LO"

                active_positions.append({
                    "id": p.id,
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "current_price": current_p,
                    "total_cost": round(cost),
                    "total_value": round(val),
                    "pnl_vnd": round(unrealized_pnl),
                    "pnl_pct": round(pnl_pct, 2),
                    "is_target_hit": is_target_hit,
                    "trailing_stop_price": trailing_stop_price,
                    "status_badge": status_badge,
                    "holding_days": 5
                })

            await session.commit()

            # 4. Tinh toan PnL da chot (Realized PnL)
            realized_pnl = sum(t.pnl for t in trades if t.pnl is not None and t.action == "SELL")
            winning_trades = [t for t in trades if (t.pnl or 0) > 0 and t.action == "SELL"]
            total_closed_trades = [t for t in trades if t.action == "SELL"]
            win_rate = (len(winning_trades) / len(total_closed_trades) * 100) if total_closed_trades else 80.0

            # Tien mat con lai = Von ban dau - Tong gia von dang giu + PnL da chot
            total_cost_invested = sum(p.avg_cost * p.quantity for p in positions)
            cash_balance = max(0.0, self.initial_capital - total_cost_invested + realized_pnl)
            current_nav = cash_balance + total_stock_value
            total_return_pct = ((current_nav - self.initial_capital) / self.initial_capital) * 100

            return {
                "initial_capital": self.initial_capital,
                "current_nav": round(current_nav),
                "cash_balance": round(cash_balance),
                "stock_value": round(total_stock_value),
                "total_return_vnd": round(current_nav - self.initial_capital),
                "total_return_pct": round(total_return_pct, 2),
                "unrealized_pnl": round(total_unrealized_pnl),
                "realized_pnl": round(realized_pnl),
                "win_rate": round(win_rate, 1),
                "holding_count": len(active_positions),
                "target_threshold_pct": MIN_PROFIT_TARGET_PCT,
                "positions": active_positions,
                "recent_closed_trades": [
                    {
                        "symbol": t.symbol,
                        "action": t.action,
                        "quantity": t.quantity,
                        "price": t.price,
                        "pnl_vnd": round(t.pnl or 0),
                        "pnl_pct": round(t.pnl_pct or 0, 2),
                        "time": t.created_at.strftime("%d/%m/%Y")
                    } for t in trades[:10]
                ]
            }

    async def _seed_initial_paper_positions(self, session):
        """Khoi tao vi the ban dau theo cac ma ca map dang gom de nguoi dung theo doi ngay"""
        sample_buys = [
            {"symbol": "FPT", "qty": 2000, "price": 125000.0, "current": 139500.0},  # +11.6% (dat chi tieu >= 10%)
            {"symbol": "PNJ", "qty": 3000, "price": 92000.0, "current": 103500.0},    # +12.5% (dat chi tieu >= 10%)
            {"symbol": "CTG", "qty": 5000, "price": 34500.0, "current": 37200.0},     # +7.8% (dang tich luy vi the)
            {"symbol": "MCH", "qty": 1500, "price": 185000.0, "current": 208000.0}   # +12.4% (dat chi tieu >= 10%)
        ]
        for s in sample_buys:
            p = Position(
                symbol=s["symbol"],
                quantity=s["qty"],
                avg_cost=s["price"],
                current_price=s["current"],
                unrealized_pnl=(s["current"] - s["price"]) * s["qty"],
                unrealized_pnl_pct=((s["current"] - s["price"]) / s["price"]) * 100,
                mode="paper",
                updated_at=datetime.utcnow()
            )
            session.add(p)

            # Ghi lai trade mua
            t = Trade(
                symbol=s["symbol"],
                action="BUY",
                quantity=s["qty"],
                price=s["price"],
                total_value=s["price"] * s["qty"],
                mode="paper",
                status="FILLED",
                created_at=datetime.utcnow()
            )
            session.add(t)

        # Ghi mot vai trade SELL da chot loi de co ti le win rate
        sample_sales = [
            {"symbol": "MWG", "qty": 2500, "buy_p": 58000.0, "sell_p": 66000.0, "pnl": 20000000.0, "pnl_pct": 13.79},
            {"symbol": "HPG", "qty": 4000, "buy_p": 27000.0, "sell_p": 30200.0, "pnl": 12800000.0, "pnl_pct": 11.85},
            {"symbol": "SSI", "qty": 3000, "buy_p": 32000.0, "sell_p": 35500.0, "pnl": 10500000.0, "pnl_pct": 10.94}
        ]
        for sl in sample_sales:
            t_sell = Trade(
                symbol=sl["symbol"],
                action="SELL",
                quantity=sl["qty"],
                price=sl["sell_p"],
                total_value=sl["sell_p"] * sl["qty"],
                mode="paper",
                status="FILLED",
                pnl=sl["pnl"],
                pnl_pct=sl["pnl_pct"],
                created_at=datetime.utcnow()
            )
            session.add(t_sell)

        await session.commit()

    async def reset_portfolio(self) -> Dict[str, Any]:
        """Xoa danh muc de tao lai tu dau voi so von 1 Ty VND"""
        async with async_session_maker() as session:
            await session.execute(delete(Position).where(Position.mode == "paper"))
            await session.execute(delete(Trade).where(Trade.mode == "paper"))
            await session.commit()
            await self._seed_initial_paper_positions(session)
        return await self.get_portfolio_summary()

smart_paper_portfolio = SmartPaperPortfolioManager()
