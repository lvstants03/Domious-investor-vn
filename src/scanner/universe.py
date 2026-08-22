import logging
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import ScanUniverse
from src.data_pipeline.market_universe_scanner import universe_scanner

logger = logging.getLogger("dominus-investor.scanner.universe")

async def get_scan_symbols(db: AsyncSession) -> List[str]:
    """Lấy danh sách các mã cổ phiếu cần scan từ database hoặc tự động quét toàn sàn từ TCBS"""
    result = await db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
    universes = result.scalars().all()
    
    if not universes:
        logger.info("Scan universe trong DB chưa có. Quét động toàn sàn từ TCBS API...")
        active_stocks = await universe_scanner.scan_market_universe(min_liquidity_ty=2.0)
        symbols = [s["symbol"] for s in active_stocks]
        
        for s in active_stocks:
            db.add(ScanUniverse(symbol=s["symbol"], exchange=s.get("exchange", "HOSE"), is_active=True))
        await db.commit()
        return symbols
        
    return [u.symbol for u in universes if not u.is_blacklisted]
