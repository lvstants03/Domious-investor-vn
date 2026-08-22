import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.database.connection import get_db_session
from src.database.repository import InvestorRepository
from src.bot.runner import BotRunner

logger = logging.getLogger("dominus-investor.bot.scheduler")

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

    def start(self):
        if self._running:
            return
        
        self._running = True
        # Lập lịch chạy quét bot định kỳ mỗi 30 giây
        self.scheduler.add_job(
            self._execute_all_bots,
            "interval",
            seconds=30,
            id="trading_bot_job",
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Bot Scheduler da khoi chay.")

    def stop(self):
        if not self._running:
            return
        self.scheduler.shutdown()
        self._running = False
        logger.info("Bot Scheduler da dung.")

bot_scheduler = BotScheduler()
