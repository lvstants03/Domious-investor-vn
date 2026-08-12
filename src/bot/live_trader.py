import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.repository import InvestorRepository
from src.tcbs.orders import equity_order_client
from src.tcbs.deriv_orders import deriv_order_client

logger = logging.getLogger("dominus-investor.bot.live_trader")

class LiveTrader:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = InvestorRepository(db)

    async def execute_buy(self, bot_config_id: int, symbol: str, qty: int, price: float, is_derivative: bool = False) -> bool:
        total_val = qty * price
        logger.info("LIVE BUY: %s qty: %s at %s. (Phai sinh: %s)", symbol, qty, price, is_derivative)

        try:
            # 1. Goi API TCBS
            if is_derivative:
                res = await deriv_order_client.place_deriv_order(symbol, "BUY", qty, price)
            else:
                res = await equity_order_client.place_order(symbol, "BUY", qty, price)
            
            order_id = res.get("order_id")
            status = "PENDING" if res.get("status") == "SUCCESS" else "FAILED"
            msg = res.get("message", "")

            # 2. Luu trade vao DB
            await self.repo.save_trade(
                bot_config_id=bot_config_id,
                symbol=symbol,
                action="BUY",
                qty=qty,
                price=price,
                total_value=total_val,
                status=status,
                mode="live",
                order_id_tcbs=order_id
            )
            
            if status == "FAILED":
                logger.error("LIVE BUY API FAILED: %s", msg)
                return False
                
            logger.info("LIVE BUY PLACED. Order ID: %s", order_id)
            return True

        except Exception as e:
            logger.error("Loi khi dat lenh Live BUY: %s", str(e))
            # Luu loi vao DB
            await self.repo.save_trade(
                bot_config_id=bot_config_id,
                symbol=symbol,
                action="BUY",
                qty=qty,
                price=price,
                total_value=total_val,
                status="FAILED",
                mode="live"
            )
            return False

    async def execute_sell(self, bot_config_id: int, symbol: str, qty: int, price: float, is_derivative: bool = False) -> bool:
        # Kiem tra vi the trong DB
        pos = await self.repo.get_position(bot_config_id, symbol)
        if not pos or pos.quantity <= 0:
            logger.warning("LIVE SELL FAILED: Khong co vi the dang nam giu.")
            return False

        sell_qty = min(qty, pos.quantity)
        total_val = sell_qty * price
        logger.info("LIVE SELL: %s qty: %s at %s.", symbol, sell_qty, price)

        try:
            # 1. Goi API TCBS
            if is_derivative:
                res = await deriv_order_client.place_deriv_order(symbol, "SELL", sell_qty, price)
            else:
                res = await equity_order_client.place_order(symbol, "SELL", sell_qty, price)
            
            order_id = res.get("order_id")
            status = "PENDING" if res.get("status") == "SUCCESS" else "FAILED"
            msg = res.get("message", "")

            # 2. Luu trade vao DB
            await self.repo.save_trade(
                bot_config_id=bot_config_id,
                symbol=symbol,
                action="SELL",
                qty=sell_qty,
                price=price,
                total_value=total_val,
                status=status,
                mode="live",
                order_id_tcbs=order_id
            )
            
            if status == "FAILED":
                logger.error("LIVE SELL API FAILED: %s", msg)
                return False
                
            logger.info("LIVE SELL PLACED. Order ID: %s", order_id)
            return True

        except Exception as e:
            logger.error("Loi khi dat lenh Live SELL: %s", str(e))
            await self.repo.save_trade(
                bot_config_id=bot_config_id,
                symbol=symbol,
                action="SELL",
                qty=sell_qty,
                price=price,
                total_value=total_val,
                status="FAILED",
                mode="live"
            )
            return False
