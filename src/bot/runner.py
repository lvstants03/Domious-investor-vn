import logging
import pandas as pd
from typing import Dict, Any, Optional, Type
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import BotConfig
from src.database.repository import InvestorRepository
from src.strategies.base import BaseStrategy
from src.strategies.rsi import RSIStrategy
from src.strategies.macd import MACDStrategy
from src.strategies.ma_volume import MAVolumeStrategy
from src.strategies.bollinger import BollingerBandsStrategy
from src.bot.paper_trader import PaperTrader
from src.bot.live_trader import LiveTrader
from src.tcbs.market import market_client
from src.tcbs.deriv_market import deriv_market_client
from src.notifications.discord import send_discord_alert

logger = logging.getLogger("dominus-investor.bot.runner")

STRATEGY_MAP: Dict[str, Type[BaseStrategy]] = {
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "ma_volume": MAVolumeStrategy,
    "bollinger": BollingerBandsStrategy
}

class BotRunner:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = InvestorRepository(db)
        self.paper_trader = PaperTrader(db)
        self.live_trader = LiveTrader(db)

    async def run_bot(self, config_id: int) -> bool:
        """Chay 1 bot duy nhat dua tren config_id"""
        config = await self.repo.get_bot_config(config_id)
        if not config or not config.is_active:
            logger.warning("Bot %s khong ton tai hoac khong active.", config_id)
            return False

        symbol = config.symbol
        strategy_name = config.strategy_name.lower()
        is_deriv = "F2" in symbol or "F1" in symbol  # Kiem tra ma phai sinh co ban

        logger.info("Bot Runner dang xu ly Bot '%s' | Ma: %s | Chien luoc: %s", config.name, symbol, strategy_name)

        try:
            # 1. Lay du lieu lich su
            df = await self._fetch_historical_data(symbol, is_deriv)
            if df.empty or len(df) < 30:
                logger.warning("Khong du du lieu lich su cho ma %s (len: %s)", symbol, len(df))
                return False

            # 2. Khoi tao Strategy
            strategy_cls = STRATEGY_MAP.get(strategy_name)
            if not strategy_cls:
                logger.error("Chien luoc %s khong hop le.", strategy_name)
                return False
                
            strategy = strategy_cls(config.strategy_params)

            # 3. Analyze logic
            signal, confidence, reason, indicators = strategy.analyze(df)
            current_price = float(df["close"].iloc[-1])

            # 4. Luu tin hieu vao DB
            await self.repo.save_signal(
                bot_config_id=config.id,
                strategy_name=config.strategy_name,
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                reason=reason,
                indicators=indicators,
                price=current_price
            )

            if signal == "HOLD":
                return True

            # 5. Tinh toan Size lenh (Quantity)
            qty = self._calculate_order_qty(config, current_price, is_deriv)
            if qty <= 0:
                logger.warning("So luong lenh tinh ra bang 0. Bo qua dat lenh.")
                return False

            # 6. Execute Order (Paper vs Live)
            trader = self.paper_trader if config.mode == "paper" else self.live_trader
            
            logger.info("Kich hoat dat lenh: %s %s ma %s o gia %s (%s mode)", signal, qty, symbol, current_price, config.mode)
            
            success = False
            if signal == "BUY":
                # Kiem tra chot chan Market Regime Gate cho co phieu co so
                if not is_deriv:
                    from src.data_pipeline.market_regime_gate import market_regime_gate
                    m_regime = await market_regime_gate.get_market_regime()
                    if not m_regime.get("is_buy_allowed", True):
                        logger.warning("Market Regime Gate: Tu dong CHAN lenh MUA ma %s vi VNINDEX dang Downtrend.", symbol)
                        return False

                success = await trader.execute_buy(config.id, symbol, qty, current_price, is_derivative=is_deriv)
            elif signal == "SELL":
                success = await trader.execute_sell(config.id, symbol, qty, current_price, is_derivative=is_deriv)

            # 7. Gui thong bao Discord
            if success:
                mode_str = "GIẢ LẬP (PAPER)" if config.mode == "paper" else "THẬT (LIVE)"
                alert_msg = (
                    f"🔔 **TÍN HIỆU GIAO DỊCH BOT {config.name}** ({mode_str})\n"
                    f"▪️ Cổ phiếu: **{symbol}**\n"
                    f"▪️ Lệnh: **{signal}**\n"
                    f"▪️ Số lượng: **{qty}**\n"
                    f"▪️ Giá khớp: **{current_price:,.0f} VND**\n"
                    f"▪️ Lý do: {reason}\n"
                    f"▪️ Chỉ báo: {indicators}"
                )
                await send_discord_alert(alert_msg)

            return success

        except Exception as e:
            logger.error("Loi he thong khi chay bot %s: %s", config.name, str(e), exc_info=True)
            return False

    async def _fetch_historical_data(self, symbol: str, is_deriv: bool) -> pd.DataFrame:
        """Lay historical data thuc te cho chien luoc bot"""
        try:
            from datetime import date, timedelta
            from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher
            
            end_date = date.today().strftime("%Y-%m-%d")
            start_date = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
            
            df = await ohlcv_fetcher.fetch_history(symbol, start_date, end_date)
            if df is not None and not df.empty:
                if "trade_date" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["trade_date"])
                    df.set_index("timestamp", inplace=True)
                return df
            return pd.DataFrame()
        except Exception as e:
            logger.error("Loi khi lay du lieu lich su cho %s: %s", symbol, str(e))
            return pd.DataFrame()

    def _calculate_order_qty(self, config: BotConfig, price: float, is_deriv: bool) -> int:
        # Neu phai sinh: quy quy tinh theo hop dong, 1 hop dong co gia ~ 1300 * 100,000 VND.
        # Nguoi dung trade tu 1-5 hop dong.
        if is_deriv:
            return 1  # Mac dinh 1 hop dong
            
        # Co so:
        # budget_for_order = budget * position_size_pct / 100
        budget_for_order = config.budget * (config.position_size_pct / 100.0)
        
        # O Viet Nam, lo giao dich toi thieu la 100 co phieu.
        # Vi vay, so luong phai la boi so cua 100.
        qty = int(budget_for_order / price)
        qty = (qty // 100) * 100
        return qty
