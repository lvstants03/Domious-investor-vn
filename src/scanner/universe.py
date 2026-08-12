import logging
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import ScanUniverse

logger = logging.getLogger("dominus-investor.scanner.universe")

# Danh sach ~50 ma co phieu thanh khoan cao mac dinh de seeding neu database trong
DEFAULT_UNIVERSE = [
    # VN30 & Bluechips
    "FPT", "HPG", "VNM", "VIC", "VHM", "VRE", "VCB", "BID", "CTG", "MBB", "TCB", "VPB", 
    "ACB", "STB", "HDB", "TPB", "MSB", "MWG", "PNJ", "GAS", "PLX", "POW", "SAB", "VJC", 
    "BVH", "GVR", "BCM", "SSB", "SHB", "VIB",
    # Dinh gia, chung khoan, bat dong san duoc quan tam
    "SSI", "VND", "VCI", "HCM", "FTS", "MBS", "DXG", "NLG", "KDH", "PDR", "DIG", "CEO",
    "GEX", "KBC", "VGC", "DGC", "DPM", "DCM", "HSG", "NKG", "PC1", "REE", "PVD", "PVS"
]

async def get_scan_symbols(db: AsyncSession) -> List[str]:
    """Lay danh sach cac ma co phieu can scan tu database"""
    result = await db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
    universes = result.scalars().all()
    
    if not universes:
        logger.info("Scan universe trong. Tien hanh seed danh sach mac dinh vao DB...")
        # Gieo mac dinh
        for sym in DEFAULT_UNIVERSE:
            db.add(ScanUniverse(symbol=sym, exchange="HOSE", is_active=True))
        await db.commit()
        return DEFAULT_UNIVERSE
        
    return [u.symbol for u in universes if not u.is_blacklisted]
