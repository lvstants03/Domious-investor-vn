import asyncio
import logging
from datetime import date
from typing import List, Optional

import pandas as pd

logger = logging.getLogger("dominus-investor.paper_trading.trailing_stop")


def _calculate_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """Tinh Average True Range dua tren DataFrame OHLCV."""
    if df is None or len(df) < period + 1:
        return None
    try:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        prev_close = df["close"].shift(1).astype(float)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        atr = tr.rolling(period, min_periods=period).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else None
    except Exception as e:
        logger.warning("Loi tinh ATR: %s", e)
        return None


class TrailingStopManager:
    """
    Quan ly Trailing Stop cho Paper Trades tren backend.
    Chay moi 60 giay qua APScheduler trong gio giao dich (09:00-15:00).

    Logic:
    1. Lay gia real-time qua market_client
    2. Cap nhat highest_price neu gia tang them
    3. Tinh trailing_stop_price = highest_price * (1 - trailing_stop_pct/100)
    4. Neu current_price <= trailing_stop_price -> DONG LENH TRAILING_STOP
    """

    ATR_MULTIPLIER = 2.5      # Stop = entry - 2.5 * ATR
    DEFAULT_TRAIL_PCT = 12.0  # Trailing 12% tu dinh cho song quy (1-3 thang)

    def calculate_atr_stop(
        self, df: pd.DataFrame, entry_price: float,
        atr_period: int = 14,
    ) -> Optional[float]:
        """
        Tinh ATR-based initial stop loss thay the cho gia tri co dinh -7%.
        Tra ve None neu khong du du lieu.
        """
        atr = _calculate_atr(df, atr_period)
        if atr is None:
            return None
        stop = entry_price - (self.ATR_MULTIPLIER * atr)
        return round(stop, 0)

    async def update_all_positions(self) -> None:
        """
        Entry point duoc APScheduler goi moi 60 giay.
        Khong raise exception de tranh lam crash scheduler.
        """
        now_h = date.today().isoformat()   # chi debug
        logger.debug("[TrailingStop] Bat dau update positions (%s)", now_h)
        try:
            await self._run_update_cycle()
        except Exception as e:
            logger.error("[TrailingStop] Loi trong update cycle: %s", e)

    async def _run_update_cycle(self) -> None:
        from src.database.connection import get_db_session
        from src.database.models import PaperTrade
        from sqlalchemy import select, update

        # Import market client de lay gia real-time
        try:
            from src.data_pipeline.ohlcv_cache import ohlcv_cache
        except ImportError:
            logger.warning("[TrailingStop] Khong import duoc ohlcv_cache, bo qua cycle")
            return

        async with get_db_session() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.status == "OPEN")
            )
            open_trades: List[PaperTrade] = list(result.scalars().all())

        if not open_trades:
            return

        logger.info("[TrailingStop] Dang kiem tra %d lenh OPEN...", len(open_trades))
        today = date.today()

        for trade in open_trades:
            try:
                await self._check_one(trade, ohlcv_cache, today)
            except Exception as e:
                logger.warning("[TrailingStop] Loi kiem tra lenh %d (%s): %s",
                               trade.id, trade.symbol, e)

    async def _check_one(self, trade, ohlcv_cache, today) -> None:
        from src.database.connection import get_db_session
        from src.database.models import PaperTrade
        from sqlalchemy import update

        # Lay gia hien tai tu ohlcv_cache (cuoi ngay) hoac market client (real-time)
        current_price = await self._get_current_price(trade.symbol)
        if current_price is None or current_price <= 0:
            return

        # Lay highest_price tu DB (co the None neu cot chua ton tai - dung entry luc do)
        highest_price = getattr(trade, "highest_price", None) or trade.entry_price
        trailing_pct = getattr(trade, "trailing_stop_pct", None) or self.DEFAULT_TRAIL_PCT

        # Cap nhat dinh moi
        new_highest = max(highest_price, current_price)
        trailing_stop_price = new_highest * (1.0 - trailing_pct / 100.0)

        # Co che Break-Even cho vi the quy:
        # Khi lai dat >= +15%, tu dong nang Stop Loss len hoa von (+0.5% phi thue)
        # Nham bao dam mot vi the da vao trend manh khong bao gio bi lo nguoc
        if new_highest >= trade.entry_price * 1.15:
            break_even_price = round(trade.entry_price * 1.005, 0)
            trailing_stop_price = max(trailing_stop_price, break_even_price)

        updates = {"highest_price": new_highest,
                   "trailing_stop_price": trailing_stop_price}

        # Kiem tra kich hoat trailing stop
        if current_price <= trailing_stop_price:
            pnl_pct = round((current_price - trade.entry_price) / trade.entry_price * 100, 2)
            updates.update({
                "status": "CLOSED_WIN" if pnl_pct > 0 else "CLOSED_LOSS",
                "exit_date": today,
                "exit_price": current_price,
                "pnl_pct": pnl_pct,
                "exit_reason": "TRAILING_STOP"
            })
            logger.info("[TrailingStop] DONG lenh %s id=%d: %.2f%% (trailing %.1f%%)",
                        trade.symbol, trade.id, pnl_pct, trailing_pct)

        async with get_db_session() as session:
            await session.execute(
                update(PaperTrade).where(PaperTrade.id == trade.id).values(**updates)
            )
            await session.commit()

    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Lay gia dong cua gan nhat.
        Uu tien: TCBS market client (real-time), fallback: ohlcv_cache (EOD).
        """
        try:
            from src.data_pipeline.ohlcv_cache import ohlcv_cache
            df = ohlcv_cache.get_ohlcv_df(symbol)
            if df is not None and not df.empty:
                return float(df["close"].iloc[-1])
        except Exception:
            pass
        return None


trailing_stop_manager = TrailingStopManager()
