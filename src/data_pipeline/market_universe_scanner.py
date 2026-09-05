import logging
import asyncio
from typing import Dict, Any, List
from datetime import datetime
from src.tcbs.market import market_client

logger = logging.getLogger("dominus-investor.pipeline.universe_scanner")

class MarketUniverseScanner:
    """
    Pipeline quét động 100% vũ trụ cổ phiếu trên cả 3 sàn (HOSE, HNX, UPCOM) từ TCBS API.
    Tuyệt đối không sử dụng bất kỳ mảng danh sách mã tĩnh hay mockdata nào.
    """

    def __init__(self):
        self._universe_cache: List[Dict[str, Any]] = []
        self._sector_cache: Dict[str, str] = {}
        self._last_scan_time: float = 0.0

    def get_symbol_sector(self, symbol: str) -> str:
        """Lấy tên nhóm ngành chính thức từ sector_map bộ nhớ đệm"""
        from src.data_pipeline.sector_map import get_sector_by_symbol
        return get_sector_by_symbol(symbol)

    async def scan_market_universe(self, min_liquidity_ty: float = 2.0) -> List[Dict[str, Any]]:
        """
        Quét trực tiếp toàn bộ dữ liệu thị trường từ TCBS tickerSnaps (HOSE: 1, HNX: 3, UPCOM: 5).
        """
        import time
        now = time.time()
        if self._universe_cache and (now - self._last_scan_time) < 120.0:
            return self._universe_cache

        discovered: List[Dict[str, Any]] = []

        async def _fetch_index(idx):
            try:
                snaps = await asyncio.wait_for(market_client.get_ticker_snaps(index=idx), timeout=1.8)
                return (idx, snaps if isinstance(snaps, list) else [])
            except Exception:
                return (idx, [])

        try:
            results = await asyncio.gather(_fetch_index(1), _fetch_index(3), _fetch_index(5))
            for index_id, snaps in results:
                for item in snaps:
                    sym = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
                    if not sym or len(sym) > 5 or not sym.isalpha():
                        continue

                    raw_price = float(item.get("matchPrice") or item.get("price") or item.get("closePrice") or item.get("refPrice") or 0.0)
                    last_price = round(raw_price * 1000) if (0 < raw_price < 1000) else round(raw_price)
                    
                    vol = int(item.get("totalVolume") or item.get("totalMatchVol") or 0)
                    raw_val = float(item.get("totalValue") or item.get("totalMatchVal") or 0.0)
                    val_vnd = raw_val if raw_val > 0 else (last_price * vol)
                    val_ty = val_vnd / 1e9

                    # Lay khoi ngoai
                    f_buy = float(item.get("buyForeignQtty") or 0)
                    f_sell = float(item.get("sellForeignQtty") or 0)
                    f_net_vol = f_buy - f_sell
                    f_room = float(item.get("room") or item.get("foreign_room_left") or 0.0)

                    exchange_name = "HOSE" if index_id == 1 else ("HNX" if index_id == 3 else "UPCOM")

                    # Lay nganh dong
                    sector_name = item.get("industryName") or item.get("sector") or self.get_symbol_sector(sym)

                    # Loc dinh luong: Giu cac ma co thanh khoan tich cuc hoac khoi luong giao dich
                    if val_ty >= min_liquidity_ty or vol >= 5000:
                        discovered.append({
                            "symbol": sym,
                            "exchange": exchange_name,
                            "sector": sector_name,
                            "last_price": last_price,
                            "volume": vol,
                            "val_ty": val_ty,
                            "foreign_net_vol": f_net_vol,
                            "foreign_room": f_room
                        })
        except Exception as e:
            logger.error("Loi khi quet market universe: %s", str(e))

        # Loại bỏ trùng lặp mã
        unique_map: Dict[str, Dict[str, Any]] = {}
        for d in discovered:
            unique_map[d["symbol"]] = d

        if unique_map:
            self._universe_cache = list(unique_map.values())
            self._last_scan_time = now
            logger.info("Da quet dong thanh cong %s co phieu toan thi truong tu TCBS.", len(self._universe_cache))
        elif not self._universe_cache:
            # Truy van tu Database ScanUniverse de luon co du lieu san sang
            try:
                from src.database.connection import async_session_maker
                from src.database.models import ScanUniverse
                from sqlalchemy import select
                async with async_session_maker() as session:
                    res = await session.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
                    db_symbols = res.scalars().all()
                    if db_symbols:
                        self._universe_cache = [
                            {
                                "symbol": u.symbol,
                                "exchange": u.exchange or "HOSE",
                                "sector": await self.get_symbol_sector(u.symbol),
                                "last_price": 0,
                                "volume": 0,
                                "val_ty": 0.0,
                                "foreign_net_vol": 0,
                                "foreign_room": 0.0
                            }
                            for u in db_symbols
                        ]
            except Exception as e:
                logger.debug("Loi doc ScanUniverse tu DB: %s", str(e))

        return self._universe_cache

universe_scanner = MarketUniverseScanner()
