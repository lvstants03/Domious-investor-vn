import asyncio
import hashlib
import logging
from datetime import datetime, time
from typing import Dict, Any, List, Optional
import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from src.config import settings
from src.database.connection import get_db_session
from src.database.models import NewsItem

logger = logging.getLogger("dominus-investor.intelligence.news_crawler")

RSS_FEEDS = [
    {"source": "CafeF TTCK", "url": "https://cafef.vn/rss/thi-truong-chung-khoan.rss"},
    {"source": "CafeF Vi Mo", "url": "https://cafef.vn/rss/kinh-te-vi-mo.rss"},
    {"source": "VnEconomy", "url": "https://vneconomy.vn/chung-khoan.rss"},
    {"source": "Vietstock", "url": "https://vietstock.vn/rss/thi-truong.rss"},
    {"source": "Bao Dau Tu", "url": "https://baodautu.vn/chung-khoan.rss"},
    {"source": "Tuoi Tre KT", "url": "https://tuoitre.vn/rss/kinh-te.rss"},
    {"source": "Reuters Biz", "url": "https://feeds.reuters.com/reuters/businessNews"},
]

class NewsCrawler:
    """
    Module thu thap tin tuc tai chinh va kinh te vi mo tu cac kenh RSS uy tin,
    loc trung lap bang URL hash va luu tru vao bang news_items.
    """

    def __init__(self):
        self.trading_start = time(8, 30)
        self.trading_end = time(16, 0)

    def is_in_trading_hours(self) -> bool:
        """Kiem tra xem thoi diem hien tai co nam trong gio giao dich khong"""
        now_time = datetime.now().time()
        return self.trading_start <= now_time <= self.trading_end

    def _hash_url(self, url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()

    def _clean_html(self, raw_html: str) -> str:
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator=" ", strip=True)

    async def fetch_feed(self, feed_info: Dict[str, str]) -> List[Dict[str, Any]]:
        """Lay noi dung tin tu mot dia chi RSS cu the"""
        source = feed_info["source"]
        feed_url = feed_info["url"]
        items: List[Dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DominusBot/1.0"
                }
                resp = await client.get(feed_url, headers=headers)
                if resp.status_code != 200:
                    logger.warning("Khong the lay feed tu %s, status code: %s", source, resp.status_code)
                    return items

                parsed = feedparser.parse(resp.text)
                for entry in parsed.entries[:20]:
                    title = entry.get("title", "").strip()
                    link = entry.get("link", "").strip()
                    summary_raw = entry.get("summary", "") or entry.get("description", "")
                    summary = self._clean_html(summary_raw)[:1000]

                    if not title or not link:
                        continue

                    pub_date = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            pub_date = datetime(*entry.published_parsed[:6])
                        except Exception:
                            pub_date = datetime.utcnow()
                    else:
                        pub_date = datetime.utcnow()

                    items.append({
                        "source": source,
                        "title": title,
                        "url": link,
                        "url_hash": self._hash_url(link),
                        "summary": summary,
                        "published_at": pub_date
                    })
        except Exception as e:
            logger.error("Loi khi crawl feed %s: %s", source, str(e))

        return items

    async def crawl_all_sources(self) -> List[Dict[str, Any]]:
        """
        Crawl song song toan bo 8 nguon RSS, loc cac link da ton tai trong CSDL.
        """
        tasks = [self.fetch_feed(f) for f in RSS_FEEDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_entries: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, list):
                all_entries.extend(r)

        if not all_entries:
            logger.info("Khong co tin tuc moi nao duoc tim thay tu cac nguon RSS.")
            return []

        # Loc trung lap voi CSDL
        new_items: List[Dict[str, Any]] = []
        hashes = [e["url_hash"] for e in all_entries]

        try:
            async with get_db_session() as session:
                stmt = select(NewsItem.url_hash).where(NewsItem.url_hash.in_(hashes))
                res = await session.execute(stmt)
                existing_hashes = set(res.scalars().all())

                for entry in all_entries:
                    if entry["url_hash"] not in existing_hashes:
                        new_item = NewsItem(
                            source=entry["source"],
                            title=entry["title"],
                            url=entry["url"],
                            url_hash=entry["url_hash"],
                            summary=entry["summary"],
                            published_at=entry["published_at"],
                            crawled_at=datetime.utcnow(),
                            is_processed=False,
                            is_injected=False
                        )
                        session.add(new_item)
                        existing_hashes.add(entry["url_hash"])
                        new_items.append(entry)

                await session.commit()
                logger.info("Da thu thap va luu moi %d ban tin vao CSDL.", len(new_items))
        except Exception as e:
            logger.error("Loi khi luu tin tuc crawl vao CSDL: %s", str(e))

        return new_items

news_crawler = NewsCrawler()
