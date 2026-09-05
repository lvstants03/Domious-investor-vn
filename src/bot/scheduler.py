import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.database.connection import get_db_session
from src.database.repository import InvestorRepository
from src.bot.runner import BotRunner

logger = logging.getLogger("dominus-investor.bot.scheduler")


def _is_trading_hours() -> bool:
    """Kiem tra co dang trong gio giao dich khong (09:00 - 15:05)."""
    now = datetime.now().time()
    from datetime import time
    return time(9, 0) <= now <= time(15, 5)


class BotScheduler:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running = False

    async def _execute_all_bots(self):
        """Quet va chay tat ca cac bot dang hoat dong"""
        logger.info("Scheduler bat dau chu ky quet bot...")
        async with get_db_session() as session:
            repo = InvestorRepository(session)
            active_bots = await repo.get_active_bot_configs()

            if not active_bots:
                logger.info("Khong co bot nao dang o trang thai HOAT DONG.")
                return

            logger.info("Tim thay %s bot dang active. Bat dau thuc thi...", len(active_bots))

            runner = BotRunner(session)
            for bot in active_bots:
                try:
                    await runner.run_bot(bot.id)
                except Exception as e:
                    logger.error("Loi khi chay bot %s: %s", bot.name, str(e))

    async def _run_trailing_stop(self):
        """Chay TrailingStopManager neu dang trong gio giao dich."""
        if not _is_trading_hours():
            return
        try:
            from src.paper_trading.trailing_stop_manager import trailing_stop_manager
            await trailing_stop_manager.update_all_positions()
        except Exception as e:
            logger.error("Loi TrailingStopManager: %s", e)

    async def _warm_up_ohlcv_cache(self):
        """
        Pre-fetch OHLCV sau phien giao dich (16:35) cho toan bo Universe.
        Dam bao scoring engine co du lieu thuc hom sau.
        """
        try:
            from src.data_pipeline.ohlcv_cache import ohlcv_cache
            from src.engine.position_hunter_predictor import VN100_SYMBOLS
            import asyncio

            symbols = list(VN100_SYMBOLS)
            logger.info("Bat dau warm-up OHLCV cache cho %d ma...", len(symbols))
            # Chay trong thread de khong block event loop
            await asyncio.get_event_loop().run_in_executor(
                None, ohlcv_cache.warm_up, symbols
            )
        except Exception as e:
            logger.error("Loi warm-up OHLCV cache: %s", e)

    def start(self):
        if self._running:
            return

        self._running = True

        # Job 1: Quet bot trading dinh ky moi 30 giay
        self.scheduler.add_job(
            self._execute_all_bots,
            "interval",
            seconds=30,
            id="trading_bot_job",
            replace_existing=True,
        )

        # Job 2: Trailing Stop - kiem tra moi 60 giay trong gio giao dich
        self.scheduler.add_job(
            self._run_trailing_stop,
            "interval",
            seconds=60,
            id="trailing_stop_job",
            replace_existing=True,
        )

        # Job 3: Warm-up OHLCV cache sau phien giao dich (16:35 hang ngay)
        self.scheduler.add_job(
            self._warm_up_ohlcv_cache,
            "cron",
            hour=16,
            minute=35,
            id="daily_ohlcv_warmup",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Bot Scheduler da khoi chay (3 jobs: trading_bot | trailing_stop | ohlcv_warmup).")

    def stop(self):
        if not self._running:
            return
        self.scheduler.shutdown()
        self._running = False
        logger.info("Bot Scheduler da dung.")


bot_scheduler = BotScheduler()

