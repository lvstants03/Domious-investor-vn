import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from src.database.connection import get_db_session
from src.database.models import SignalLog

logger = logging.getLogger("dominus-investor.intelligence.signal_logger")

class SignalLogger:
    """
    Module ghi nhan va luu tru moi tin hieu tu PositionHunterPredictor vao CSDL
    phuc vu danh gia Track Record va tinh ty le thang.
    """

    def validate_signal(self, data: Dict[str, Any]) -> bool:
        """Kiem tra tinh hop le cua du lieu tin hieu dau vao"""
        symbol = str(data.get("symbol", "")).strip().upper()
        if not symbol or len(symbol) < 3 or len(symbol) > 10:
            logger.warning("Tin hieu bo qua do ma symbol khong hop le: %s", symbol)
            return False

        try:
            score = float(data.get("score", 0.0))
            if score < 0.0 or score > 100.0:
                logger.warning("Tin hieu %s bo qua do score ngoai pham vi: %s", symbol, score)
                return False
        except (ValueError, TypeError):
            return False

        try:
            price = float(data.get("price_entry", data.get("current_price", 0.0)))
            if price <= 0.0:
                logger.warning("Tin hieu %s bo qua do price <= 0: %s", symbol, price)
                return False
        except (ValueError, TypeError):
            return False

        return True

    async def log_signal(self, data: Dict[str, Any]) -> Optional[int]:
        """
        Luu mot tin hieu don le vao bang signals_log
        """
        if not self.validate_signal(data):
            return None

        symbol = str(data.get("symbol", "")).strip().upper()
        score = float(data.get("score", 0.0))
        regime = str(data.get("regime", "SIDEWAYS"))
        price_entry = float(data.get("price_entry", data.get("current_price", 0.0)))
        sector = data.get("sector") or data.get("sector_name")
        shark_flow = float(data.get("shark_flow", data.get("shark_net_val", 0.0))) if data.get("shark_flow") is not None else None
        news_boost = float(data.get("news_boost", 0.0))
        action_badge = data.get("action_badge")

        try:
            async with get_db_session() as session:
                record = SignalLog(
                    symbol=symbol,
                    score=score,
                    regime=regime,
                    price_entry=price_entry,
                    sector=sector,
                    shark_flow=shark_flow,
                    news_boost=news_boost,
                    action_badge=action_badge,
                    signaled_at=datetime.utcnow()
                )
                session.add(record)
                await session.flush()
                signal_id = record.id
                await session.commit()
                logger.info("Da ghi log tin hieu ID %s cho ma %s (Score: %.1f, Boost: %.1f)", signal_id, symbol, score, news_boost)
                return signal_id
        except Exception as e:
            logger.error("Loi khi ghi log tin hieu %s: %s", symbol, str(e))
            return None

    async def log_batch_signals(self, signals: List[Dict[str, Any]]) -> List[int]:
        """
        Luu hang loat tin hieu tu dot scan cua PositionHunter
        """
        saved_ids = []
        for s in signals:
            sid = await self.log_signal(s)
            if sid is not None:
                saved_ids.append(sid)
        return saved_ids

signal_logger = SignalLogger()
