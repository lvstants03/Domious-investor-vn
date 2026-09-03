import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from src.config import settings
from src.intelligence.news_crawler import news_crawler
from src.intelligence.macro_classifier import macro_classifier
from src.intelligence.gemini_narrator import gemini_narrator
from src.intelligence.track_record import track_record_evaluator
from src.intelligence.news_catalyst_booster import news_catalyst_booster
from src.publish.discord_channels import discord_publisher
from src.data_pipeline.big_order_tracker import big_order_tracker

logger = logging.getLogger("dominus-investor.publish.scheduler")

class MediaScheduler:
    """
    APScheduler tu dong hoa toan bo chu ky thu thap tin tuc,
    phan loai vi mo bang AI va xuat ban ban tin len Discord.
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")

    async def job_crawl_and_classify(self):
        """Task crawl tin moi va phan loai vi mo qua Gemini"""
        logger.info("[CRON] Bat dau crawl tin tuc tu RSS...")
        try:
            new_items = await news_crawler.crawl_all_sources()
            if new_items:
                classified_count = await macro_classifier.classify_unprocessed_news(limit=15)
                logger.info("[CRON] Da phan loai %d tin tuc vi mo.", classified_count)
                # Lam moi cache catalyst
                await news_catalyst_booster._refresh_cache_if_needed()
        except Exception as e:
            logger.error("[CRON] Loi trong job crawl va classify tin: %s", str(e))

    async def job_morning_brief(self):
        """Task xuat ban ban tin sang luc 07:00"""
        logger.info("[CRON] Chuan bi xuat ban Ban Tin Sang...")
        try:
            brief_text = await gemini_narrator.generate_morning_brief()
            await discord_publisher.publish_morning_brief(brief_text)
            logger.info("[CRON] Da xuat ban thanh cong Ban Tin Sang.")
        except Exception as e:
            logger.error("[CRON] Loi khi xuat ban Ban Tin Sang: %s", str(e))

    async def job_session_open(self):
        """Task xuat ban ban tin mo cua luc 09:05"""
        logger.info("[CRON] Chuan bi xuat ban Canh Bao Mo Phien...")
        try:
            open_text = await gemini_narrator.generate_session_open()
            await discord_publisher.publish_morning_brief(open_text)
        except Exception as e:
            logger.error("[CRON] Loi khi xuat ban Canh Bao Mo Phien: %s", str(e))

    async def job_realtime_whale_check(self):
        """Task kiem tra lenh Ca Map dot bien trong gio giao dich"""
        if not news_crawler.is_in_trading_hours():
            return
        try:
            overview = big_order_tracker.get_overview()
            top_stocks = overview.get("top_stocks", [])
            for st in top_stocks[:3]:
                net_val = float(st.get("net_val", 0.0))
                net_ty = net_val / 1e9
                if net_ty >= 5.0:  # Ca map gom tren 5 ty VND
                    sym = st.get("symbol", "")
                    reason = f"Dong tien mua chu dong dot bien {net_ty:+.1f} Ty trong phien."
                    await discord_publisher.publish_shark_alert(sym, "Co phieu dan song", net_ty, reason)
        except Exception as e:
            logger.error("[CRON] Loi khi kiem tra realtime Ca Map: %s", str(e))

    async def job_session_close(self):
        """Task xuat ban tong ket phien luc 15:35"""
        logger.info("[CRON] Chuan bi xuat ban Tong Ket Phien...")
        try:
            close_text = await gemini_narrator.generate_session_close()
            await discord_publisher.publish_session_close(close_text)
            logger.info("[CRON] Da xuat ban Tong Ket Phien thanh cong.")
        except Exception as e:
            logger.error("[CRON] Loi khi xuat ban Tong Ket Phien: %s", str(e))

    async def job_evaluate_track_record(self):
        """Task danh gia hieu qua T+3/T+5 luc 16:30"""
        logger.info("[CRON] Bat dau danh gia Track Record T+3 va T+5...")
        try:
            res = await track_record_evaluator.evaluate_pending_signals()
            logger.info("[CRON] Ket qua danh gia Track Record: %s", res)
        except Exception as e:
            logger.error("[CRON] Loi khi danh gia Track Record: %s", str(e))

    async def job_weekly_strategy(self):
        """Task xuat ban chien luoc tuan Thu 7 09:00"""
        logger.info("[CRON] Chuan bi xuat ban Chien Luoc Tuan...")
        try:
            weekly_text = await gemini_narrator.generate_weekly_analysis()
            await discord_publisher.publish_weekly_analysis(weekly_text)
            logger.info("[CRON] Da xuat ban Chien Luoc Tuan thanh cong.")
        except Exception as e:
            logger.error("[CRON] Loi khi xuat ban Chien Luoc Tuan: %s", str(e))

    def setup_jobs(self):
        """Dang ky cac jobs theo lich bieu da xac nhan"""
        # 06:50 Crawl tin sang
        self.scheduler.add_job(
            self.job_crawl_and_classify,
            CronTrigger(hour=6, minute=50),
            id="job_crawl_morning",
            replace_existing=True
        )

        # 07:00 Ban tin sang
        self.scheduler.add_job(
            self.job_morning_brief,
            CronTrigger(hour=7, minute=0),
            id="job_morning_brief",
            replace_existing=True
        )

        # 09:00 Crawl tin dau gio
        self.scheduler.add_job(
            self.job_crawl_and_classify,
            CronTrigger(hour=9, minute=0),
            id="job_crawl_open",
            replace_existing=True
        )

        # 09:05 Canh bao mo phien
        self.scheduler.add_job(
            self.job_session_open,
            CronTrigger(hour=9, minute=5),
            id="job_session_open",
            replace_existing=True
        )

        # 15 phut/lan trong gio giao dich: Crawl & Whale Check
        crawl_interval = getattr(settings, "CRAWL_INTERVAL_TRADING_MIN", 15)
        self.scheduler.add_job(
            self.job_crawl_and_classify,
            IntervalTrigger(minutes=crawl_interval),
            id="job_crawl_trading_interval",
            replace_existing=True
        )
        self.scheduler.add_job(
            self.job_realtime_whale_check,
            IntervalTrigger(minutes=15),
            id="job_whale_check_interval",
            replace_existing=True
        )

        # 15:30 Crawl tin cuoi phien
        self.scheduler.add_job(
            self.job_crawl_and_classify,
            CronTrigger(hour=15, minute=30),
            id="job_crawl_close",
            replace_existing=True
        )

        # 15:35 Tong ket phien
        self.scheduler.add_job(
            self.job_session_close,
            CronTrigger(hour=15, minute=35),
            id="job_session_close",
            replace_existing=True
        )

        # 16:30 Danh gia Track Record
        self.scheduler.add_job(
            self.job_evaluate_track_record,
            CronTrigger(hour=16, minute=30),
            id="job_evaluate_track_record",
            replace_existing=True
        )

        # Thu 7 09:00 Chien luoc tuan
        self.scheduler.add_job(
            self.job_weekly_strategy,
            CronTrigger(day_of_week="sat", hour=9, minute=0),
            id="job_weekly_strategy",
            replace_existing=True
        )

    def start(self):
        """Khoi dong scheduler"""
        self.setup_jobs()
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Dominus Media Intelligence Scheduler da khoi dong thanh cong.")

    def stop(self):
        """Dung scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Dominus Media Intelligence Scheduler da tam dung.")

media_scheduler = MediaScheduler()
