import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.repository import InvestorRepository

logger = logging.getLogger("dominus-investor.bot.paper_trader")

class PaperTrader:
    def __init__(self, db: AsyncSession):
        self.repo = InvestorRepository(db)

    async def execute_buy(self, bot_config_id: int, symbol: str, qty: int, price: float) -> bool:
        total_val = qty * price
        logger.info("PAPER BUY: %s qty: %s at %s. Total: %s", symbol, qty, price, total_val)
        
        # 1. Luu trade vao DB o trang thai FILLED
        trade = await self.repo.save_trade(
            bot_config_id=bot_config_id,
            symbol=symbol,
            action="BUY",
            qty=qty,
            price=price,
            total_value=total_val,
            status="FILLED",
            mode="paper"
        )
        trade.filled_at = datetime.utcnow()

        # 2. Cap nhat vi the Position trong DB
        await self.repo.update_position(
            bot_config_id=bot_config_id,
            symbol=symbol,
            qty_change=qty,
            price=price,
            mode="paper"
        )
        
        return True

    async def execute_sell(self, bot_config_id: int, symbol: str, qty: int, price: float) -> bool:
        # Kiem tra xem co dang nam giu vi the hay khong
        pos = await self.repo.get_position(bot_config_id, symbol)
        if not pos or pos.quantity <= 0:
            logger.warning("PAPER SELL FAILED: Khong co vi the de ban cho %s", symbol)
            return False

        # Ban nhieu nhat bang so luong dang co
        sell_qty = min(qty, pos.quantity)
        total_val = sell_qty * price
        
        # Tinh PnL
        pnl = (price - pos.avg_cost) * sell_qty
        pnl_pct = ((price - pos.avg_cost) / pos.avg_cost * 100) if pos.avg_cost > 0 else 0.0

        logger.info("PAPER SELL: %s qty: %s at %s. PnL: %s (%s%%)", symbol, sell_qty, price, pnl, pnl_pct)

        # 1. Luu trade vao DB o trang thai FILLED
        trade = await self.repo.save_trade(
            bot_config_id=bot_config_id,
            symbol=symbol,
            action="SELL",
            qty=sell_qty,
            price=price,
            total_value=total_val,
            status="FILLED",
            mode="paper"
        )
        trade.filled_at = datetime.utcnow()
        trade.pnl = pnl
        trade.pnl_pct = pnl_pct

        # 2. Cap nhat vi the Position trong DB
        await self.repo.update_position(
            bot_config_id=bot_config_id,
            symbol=symbol,
            qty_change=-sell_qty,
            price=price,
            mode="paper"
        )
        
        return True
