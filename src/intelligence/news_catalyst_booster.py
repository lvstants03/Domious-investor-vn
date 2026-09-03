import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import select, and_
from src.config import settings
from src.database.connection import get_db_session
from src.database.models import NewsItem

logger = logging.getLogger("dominus-investor.intelligence.news_catalyst_booster")

class NewsCatalystBooster:
    """
    Singleton inject News Catalyst Score truc tiep vao PositionHunterPredictor o Layer 5.
    Tang hoac giam diem co phieu dua vao cac su kien tin tuc vi mo dot bien trong 24 gio qua.
    """

    def __init__(self):
        self._cache_news: List[Dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._cache_ttl: float = 300.0  # 5 phut lam moi cache tin tuc
        self.max_boost = getattr(settings, "NEWS_BOOST_MAX", 15.0)
        self.impact_threshold = getattr(settings, "NEWS_IMPACT_THRESHOLD", 6.0)

    async def _refresh_cache_if_needed(self):
        """Cap nhat cache danh sach tin tuc co tac dong lon trong 24h qua"""
        now_ts = time.time()
        if self._cache_news and (now_ts - self._cache_time) < self._cache_ttl:
            return

        since_24h = datetime.utcnow() - timedelta(hours=24)
        try:
            async with get_db_session() as session:
                stmt = select(NewsItem).where(
                    and_(
                        NewsItem.is_processed == True,
                        NewsItem.published_at >= since_24h,
                        NewsItem.impact_score >= self.impact_threshold
                    )
                ).order_by(NewsItem.published_at.desc())
                res = await session.execute(stmt)
                records = res.scalars().all()

                cached = []
                for r in records:
                    cached.append({
                        "id": r.id,
                        "title": r.title,
                        "category": r.category,
                        "sentiment": r.sentiment,
                        "impact_score": r.impact_score,
                        "sectors_affected": r.sectors_affected or [],
                        "symbols_affected": r.symbols_affected or [],
                        "published_at": r.published_at or datetime.utcnow()
                    })
                self._cache_news = cached
                self._cache_time = now_ts
                logger.debug("Da lam moi cache news catalyst: %d tin tuc tac dong lon", len(cached))
        except Exception as e:
            logger.error("Loi khi lam moi cache news catalyst: %s", str(e))

    def get_news_boost(self, symbol: str, sector: Optional[str] = None) -> float:
        """
        Tinh toan diem boost [-15.0, +15.0] cho mot ma co phieu.
        Cong thuc: boost += sentiment * impact_score * time_decay
        - time_decay: 1.5 neu < 2h, 1.0 neu < 8h, 0.6 neu < 24h
        """
        sym_upper = symbol.strip().upper()
        total_boost = 0.0
        now = datetime.utcnow()

        for news in self._cache_news:
            is_match = False
            # Khop truc tiep theo ma co phieu
            if sym_upper in news["symbols_affected"]:
                is_match = True
            # Hoac khop theo nhom nganh
            elif sector and sector in news["sectors_affected"]:
                is_match = True

            if not is_match:
                continue

            # Tinh he so suy giam thoi gian (time decay)
            age_hours = max(0.0, (now - news["published_at"]).total_seconds() / 3600.0)
            if age_hours <= 2.0:
                decay = 1.5
            elif age_hours <= 8.0:
                decay = 1.0
            else:
                decay = 0.6

            delta = news["sentiment"] * news["impact_score"] * decay
            total_boost += delta

        # Gioi han tong boost trong [-NEWS_BOOST_MAX, +NEWS_BOOST_MAX]
        clamped = max(-self.max_boost, min(self.max_boost, total_boost))
        return round(clamped, 1)

    def get_news_context(self, symbol: str, sector: Optional[str] = None) -> str:
        """
        Lay giai thich ngan gon ve tin tuc dang tac dong len co phieu
        """
        sym_upper = symbol.strip().upper()
        for news in self._cache_news:
            if sym_upper in news["symbols_affected"] or (sector and sector in news["sectors_affected"]):
                boost = self.get_news_boost(sym_upper, sector)
                sign = "+" if boost > 0 else ""
                direction = "huong loi" if boost > 0 else ("chiu anh huong" if boost < 0 else "trung lap")
                return f"{news['title']} ({direction}, {sign}{boost} diem)"
        return "Khong co tin tuc dot bien trong 24h qua"

    def get_top_beneficiaries(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Lay danh sach cac co phieu dang huong loi manh nhat tu tin tuc phuc vu ban tin
        """
        beneficiaries: Dict[str, Dict[str, Any]] = {}
        for news in self._cache_news:
            if news["sentiment"] <= 0:
                continue
            for sym in news["symbols_affected"]:
                boost = self.get_news_boost(sym)
                if boost > 0:
                    if sym not in beneficiaries or boost > beneficiaries[sym]["news_boost"]:
                        beneficiaries[sym] = {
                            "symbol": sym,
                            "news_boost": boost,
                            "catalyst_title": news["title"],
                            "impact_score": news["impact_score"],
                            "reason": f"Huong loi tu {news['category']} ({news['title']})"
                        }

        sorted_list = sorted(beneficiaries.values(), key=lambda x: x["news_boost"], reverse=True)
        return sorted_list[:limit]

news_catalyst_booster = NewsCatalystBooster()
