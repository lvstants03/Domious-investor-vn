import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from datetime import timedelta
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import BotConfig, Trade, Position, StrategySignal, MarketSnapshot, ScanUniverse, ScanResult

logger = logging.getLogger("dominus-investor.database.repository")

class InvestorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # --- Bot Config ---
    async def get_bot_config(self, config_id: int) -> Optional[BotConfig]:
        result = await self.db.execute(select(BotConfig).where(BotConfig.id == config_id))
        return result.scalars().first()

    async def get_active_bot_configs(self) -> List[BotConfig]:
        result = await self.db.execute(select(BotConfig).where(BotConfig.is_active == True))
        return list(result.scalars().all())

    async def save_bot_config(self, name: str, strategy: str, symbol: str, mode: str, budget: float, params: Dict[str, Any]) -> BotConfig:
        config = BotConfig(
            name=name,
            strategy_name=strategy,
            symbol=symbol.upper(),
            mode=mode,
            budget=budget,
            strategy_params=params
        )
        self.db.add(config)
        await self.db.flush()
        return config

    # --- Trades ---
    async def save_trade(self, bot_config_id: Optional[int], symbol: str, action: str, qty: int, price: float, total_value: float, status: str, mode: str, order_id_tcbs: Optional[str] = None) -> Trade:
        trade = Trade(
            bot_config_id=bot_config_id,
            symbol=symbol.upper(),
            action=action.upper(),
            quantity=qty,
            price=price,
            total_value=total_value,
            status=status,
            mode=mode,
            order_id_tcbs=order_id_tcbs
        )
        self.db.add(trade)
        await self.db.flush()
        return trade

    # --- Positions ---
    async def get_position(self, bot_config_id: int, symbol: str) -> Optional[Position]:
        result = await self.db.execute(
            select(Position).where(Position.bot_config_id == bot_config_id, Position.symbol == symbol.upper())
        )
        return result.scalars().first()

    async def update_position(self, bot_config_id: int, symbol: str, qty_change: int, price: float, mode: str) -> Position:
        pos = await self.get_position(bot_config_id, symbol)
        if not pos:
            pos = Position(
                bot_config_id=bot_config_id,
                symbol=symbol.upper(),
                quantity=0,
                avg_cost=0.0,
                current_price=price,
                mode=mode
            )
            self.db.add(pos)
            await self.db.flush()

        if qty_change > 0:  # Mua vao
            new_qty = pos.quantity + qty_change
            pos.avg_cost = ((pos.quantity * pos.avg_cost) + (qty_change * price)) / new_qty
            pos.quantity = new_qty
        elif qty_change < 0:  # Ban ra
            new_qty = max(0, pos.quantity + qty_change)
            pos.quantity = new_qty
            if new_qty == 0:
                pos.avg_cost = 0.0

        pos.current_price = price
        pos.unrealized_pnl = (pos.current_price - pos.avg_cost) * pos.quantity
        pos.unrealized_pnl_pct = ((pos.current_price - pos.avg_cost) / pos.avg_cost * 100) if pos.avg_cost > 0 else 0.0
        
        await self.db.flush()
        return pos

    # --- Signals ---
    async def save_signal(self, bot_config_id: Optional[int], strategy_name: str, symbol: str, signal: str, confidence: float, reason: str, indicators: Dict[str, Any], price: float) -> StrategySignal:
        sig = StrategySignal(
            bot_config_id=bot_config_id,
            strategy_name=strategy_name,
            symbol=symbol.upper(),
            signal=signal.upper(),
            confidence=confidence,
            reason=reason,
            indicator_values=indicators,
            price_at_signal=price
        )
        self.db.add(sig)
        await self.db.flush()
        return sig

    # --- Scanner ---
    async def get_scan_universe(self) -> List[ScanUniverse]:
        result = await self.db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
        return list(result.scalars().all())

    async def save_scan_result(self, symbol: str, composite: float, tech: float, volume: float, momentum: float, risk: float, signals: Dict[str, Any], price: float, vol: int, foreign_buy: float, rank: int) -> ScanResult:
        res = ScanResult(
            symbol=symbol.upper(),
            composite_score=composite,
            technical_score=tech,
            volume_score=volume,
            momentum_score=momentum,
            risk_score=risk,
            signals=signals,
            price_at_scan=price,
            volume_at_scan=vol,
            foreign_net_buy=foreign_buy,
            rank_in_scan=rank
        )
        self.db.add(res)
        await self.db.flush()
        return res

    async def get_latest_scan_results(self) -> List[ScanResult]:
        """Lay tat ca ket qua cua dot quet gan day nhat (lech khong qua 5s so voi record moi nhat)"""
        max_time_res = await self.db.execute(select(func.max(ScanResult.scan_time)))
        max_time = max_time_res.scalar()
        if not max_time:
            return []
        
        stmt = select(ScanResult).where(
            ScanResult.scan_time >= max_time - timedelta(seconds=5)
        ).order_by(ScanResult.rank_in_scan.asc())
        
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
