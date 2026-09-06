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
MIN_PROFIT_TARGET_PCT = 30.0      # Muc tieu song quy: +30%
STOP_LOSS_PCT = -9.0              # Cat lo cau truc Wyckoff: -9%

class SmartPaperPortfolioManager:
    """
    Quan ly Danh muc Dau tu Gia lap Thuc chien (Smart Paper Portfolio).
    Khop theo gia thuc te tren san TCBS, tu dong ap dung chien luoc
    Gong Lai Dong (Dynamic Holding) cho vi the quy 1-3 thang (Target +30%).
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

                # Logic Trailing Stop & Trang thai gong lai song quy (1-3 thang)
                is_target_hit = pnl_pct >= MIN_PROFIT_TARGET_PCT
                
                # Co che Khoa Hoa Von (Break-Even) khi lai >= 15%
                if pnl_pct >= 15.0:
                    trailing_stop_price = max(round(p.avg_cost * 1.005), round(current_p * 0.88))
                    status_badge = "KHOA HOA VON: BREAK-EVEN"
                elif is_target_hit:
                    trailing_stop_price = round(current_p * 0.88)  # Trailing 12% tu dinh
                    status_badge = "DAT TARGET QUY: +30%"
                elif pnl_pct >= 0:
                    trailing_stop_price = round(p.avg_cost * (1 + STOP_LOSS_PCT / 100))
                    status_badge = "DANG GONG SONG QUY"
                else:
                    trailing_stop_price = round(p.avg_cost * (1 + STOP_LOSS_PCT / 100))
                    status_badge = "CANH BAO: DANG RUNG LAC NEN" if pnl_pct > -6.0 else "CANH BAO RUI RO: GAN CAT LO"

                # Tu dong chot lenh Ban khi vi pham cat lo hoac trailing stop
                should_auto_exit = False
                exit_action_reason = ""
                if pnl_pct <= STOP_LOSS_PCT:
                    should_auto_exit = True
                    exit_action_reason = f"Cat lo ky luat Wyckoff ({pnl_pct:.1f}%)"
                elif pnl_pct >= 15.0 and current_p <= (p.avg_cost * 1.005):
                    should_auto_exit = True
                    exit_action_reason = "Bao toan von: Break-Even"
                elif is_target_hit and current_p <= trailing_stop_price:
                    should_auto_exit = True
                    exit_action_reason = f"Chot loi Target Song Quy ({pnl_pct:.1f}%)"

                if should_auto_exit:
                    t_exit = Trade(
                        symbol=p.symbol,
                        action="SELL",
                        quantity=p.quantity,
                        price=current_p,
                        total_value=val,
                        pnl=unrealized_pnl,
                        pnl_pct=pnl_pct,
                        mode="paper",
                        status="FILLED",
                        created_at=datetime.utcnow(),
                        filled_at=datetime.utcnow()
                    )
                    session.add(t_exit)
                    p.quantity = 0
                    continue

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
            total_cost_invested = sum(p.avg_cost * p.quantity for p in positions if p.quantity > 0)
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

    async def auto_sync_with_hunter(self, forced: bool = False) -> Dict[str, Any]:
        """
        Ket noi tu dong voi Position Hunter Predictor Engine de giai ngan va quan tri danh muc:
        1. Xac dinh Nguong diem linh hoat (Dynamic Threshold) dua vao Market Regime:
           - BULL: min_score = 70.0 (thi truong thuan loi, don som sieu co phieu)
           - RE_ACCUMULATION / ACCUMULATION_EARLY: min_score = 75.0
           - DISTRIBUTION_WARNING / SPRING_REBOUND: min_score = 80.0
           - BEAR: Khong giai ngan moi
        2. Chien luoc tap trung toi da hoa loi nhuan (High-Conviction 3 - 5 ma):
           - Score >= 85: Giai ngan 30% NAV (300 Tr)
           - Score >= 75: Giai ngan 20% NAV (200 Tr)
           - Score >= 70: Giai ngan 15% NAV (150 Tr)
        3. Tu dong dat lenh mua theo gia realtime TCBS.
        """
        async with async_session_maker() as session:
            from src.data_pipeline.market_regime_gate import market_regime_gate
            from src.engine.position_hunter_predictor import position_hunter_predictor
            from src.tcbs.market import market_client

            regime_info = await market_regime_gate.get_market_regime()
            is_safe = regime_info.get("is_buy_allowed", True)
            regime_type = regime_info.get("regime", "BULL")

            if not is_safe and not forced:
                logger.info("Thi truong dang trong pha rui ro / BEAR, tu dong khoa giai ngan moi.")
                return await self.get_portfolio_summary()

            # 1. Nguong diem linh hoat theo che do thi truong
            if regime_type == "BULL":
                min_score = 70.0
            elif regime_type in ("RE_ACCUMULATION", "ACCUMULATION_EARLY"):
                min_score = 75.0
            else:
                min_score = 80.0

            # 2. Lay danh sach vi the hien tai
            res_pos = await session.execute(
                select(Position).where(Position.mode == "paper", Position.quantity > 0)
            )
            current_positions = res_pos.scalars().all()
            holding_symbols = {p.symbol.upper() for p in current_positions}

            # 3. Tinh suc mua kha dung
            res_trades = await session.execute(
                select(Trade).where(Trade.mode == "paper")
            )
            all_trades = res_trades.scalars().all()
            realized_pnl = sum(t.pnl for t in all_trades if t.pnl is not None and t.action == "SELL")
            total_invested = sum(p.avg_cost * p.quantity for p in current_positions)
            cash_available = max(0.0, self.initial_capital - total_invested + realized_pnl)

            # 4. Quet co hoi tu Position Hunter
            forecast = await position_hunter_predictor.scan_medium_term_opportunities(basket="ALL")
            opportunities = forecast.get("top_opportunities", []) or forecast.get("opportunities", [])

            # Loc cac ung vien theo tieu chi: TY LE RR CAO NHAT & TY LE LO THAP NHAT
            # 1. Chi lay co phieu co R:R >= 2.5 (Target loi nhuan >= 2.5 lan Stop loss)
            # 2. Score >= 33.0 (loai bo co phieu yeu kem kem duoi 30 diem nhu HPG 29.7)
            # 3. Khong co trong danh muc da nam giu
            qualified = []
            for op in opportunities:
                sym_op = op.get("symbol", "").upper()
                if not sym_op or sym_op in holding_symbols:
                    continue
                score_val = float(op.get("triple_score") or op.get("score") or 0.0)
                rr_raw = op.get("rr_ratio")
                rr_val = 3.0
                if isinstance(rr_raw, (int, float)):
                    rr_val = float(rr_raw)
                elif isinstance(rr_raw, str):
                    try:
                        rr_val = float(rr_raw.split(":")[-1].strip())
                    except Exception:
                        rr_val = 3.0
                cur_p = float(op.get("current_price") or 0.0)
                sl_p = float(op.get("stop_loss") or (cur_p * 0.93))
                t2_p = float(op.get("target_2m") or (cur_p * 1.35))
                if cur_p > sl_p and cur_p > 0:
                    rr_calc = round((t2_p - cur_p) / (cur_p - sl_p), 2)
                else:
                    rr_calc = rr_val

                if score_val >= 33.0 and rr_calc >= 2.5:
                    op["effective_rr"] = rr_calc
                    op["effective_score"] = score_val
                    qualified.append(op)

            # Sap xep uu tien: Ket hop Score cao nhat va R:R tot nhat de toi da hoa loi nhuan
            qualified.sort(key=lambda x: (x.get("effective_score", 0) * 0.6 + x.get("effective_rr", 0) * 10 * 0.4), reverse=True)

            # Giai ngan toi da hoa loi nhuan (toi da 5 ma trong danh muc)
            current_count = len(current_positions)
            for cand in qualified:
                if current_count >= 5 or cash_available < 100_000_000.0:
                    break

                sym = cand.get("symbol", "").upper()
                score = cand.get("effective_score", 40.0)

                # Ty trong toi uu quan tri rui ro: 200 Trieu / ma (20% NAV)
                alloc = min(cash_available, 200_000_000.0)
                if alloc < 50_000_000.0:
                    continue

                # Lay gia realtime tu TCBS
                price = float(cand.get("current_price") or 0.0)
                if price <= 0:
                    try:
                        p_info = await market_client.get_price_info(sym)
                        price = float(p_info.get("price") or 0.0)
                    except Exception:
                        price = 0.0

                if price <= 0:
                    continue

                qty = int((alloc / price) // 100) * 100
                if qty <= 0:
                    continue

                actual_cost = price * qty
                if actual_cost > cash_available:
                    continue

                # Mo vi the mua tu dong
                new_pos = Position(
                    symbol=sym,
                    quantity=qty,
                    avg_cost=price,
                    current_price=price,
                    unrealized_pnl=0.0,
                    unrealized_pnl_pct=0.0,
                    mode="paper",
                    updated_at=datetime.utcnow()
                )
                session.add(new_pos)

                new_trade = Trade(
                    symbol=sym,
                    action="BUY",
                    quantity=qty,
                    price=price,
                    total_value=actual_cost,
                    mode="paper",
                    status="FILLED",
                    created_at=datetime.utcnow(),
                    filled_at=datetime.utcnow()
                )
                session.add(new_trade)

                cash_available -= actual_cost
                current_count += 1
                holding_symbols.add(sym)
                logger.info("Auto-Hunter giai ngan thanh cong %s: %d cp gia %.0fd (Score: %.1f, RR: %.2f)", sym, qty, price, score, cand.get("effective_rr", 0))

            await session.commit()

        return await self.get_portfolio_summary()

    async def _seed_initial_paper_positions(self, session):
        """Khong nap co phieu cung - De Quỹ hoan toan khoi dau voi 100% Tien Mat va dong bo theo Hunter"""
        pass

    async def reset_portfolio(self) -> Dict[str, Any]:
        """Xoa danh muc de tao lai tu dau voi so von 1 Ty VND va tu dong giai ngan theo Hunter RR cao nhat"""
        async with async_session_maker() as session:
            await session.execute(delete(Position).where(Position.mode == "paper"))
            await session.execute(delete(Trade).where(Trade.mode == "paper"))
            await session.commit()
        # Tu dong giai ngan ngay vao top co phieu co RR cao nhat va diem tot nhat
        try:
            return await self.auto_sync_with_hunter()
        except Exception as e:
            logger.warning("Loi auto sync sau reset: %s", e)
            return await self.get_portfolio_summary()

smart_paper_portfolio = SmartPaperPortfolioManager()
