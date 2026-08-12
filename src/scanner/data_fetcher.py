import asyncio
import logging
from typing import List, Dict, Any
from src.tcbs.market import market_client

logger = logging.getLogger("dominus-investor.scanner.data_fetcher")

class ScannerDataFetcher:
    async def fetch_all_market_data(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Lay thong tin thi truong cua tat ca cac ma can scan"""
        logger.info("Bat dau tai thong tin thi truong cho %s ma...", len(symbols))
        
        # Tải trước toàn bộ room nước ngoài để cache, tránh spam requests
        try:
            foreign_rooms_cache = await market_client.get_all_foreign_rooms()
        except Exception as e:
            logger.warning("Khong the tai truoc room nuoc ngoai: %s. Se dung fallback.", str(e))
            foreign_rooms_cache = {}

        results = {}
        # Dung semaphore de gioi han concurrency tranh bi rate limit TCBS API
        sem = asyncio.Semaphore(5)

        async def fetch_one(symbol: str):
            async with sem:
                try:
                    # 1. Lay thong tin gia va volume hien tai
                    price_info = await market_client.get_price_info(symbol)
                    
                    # 2. Tra cuu khoi ngoai tu cache da tai san, neu khong co thi dung fallback mac dinh
                    foreign_info = foreign_rooms_cache.get(symbol)
                    if not foreign_info:
                        foreign_info = {
                            "symbol": symbol,
                            "foreign_owned_pct": 0.0,
                            "foreign_room_left": 0.0,
                            "net_buy_volume": 0.0,
                            "net_buy_value": 0.0
                        }
                        
                    # 3. Lay cung cau 15m trong phien
                    supply_demand = await market_client.get_supply_demand_15m(symbol)

                    results[symbol] = {
                        "price_info": price_info,
                        "foreign_info": foreign_info,
                        "supply_demand": supply_demand
                    }
                except Exception as e:
                    logger.warning("Khong the tai data cho ma %s: %s", symbol, str(e))

        # Chay async song song
        await asyncio.gather(*(fetch_one(s) for s in symbols))
        logger.info("Tai thong tin hoan tat. Thanh cong: %s/%s ma.", len(results), len(symbols))
        return results

data_fetcher = ScannerDataFetcher()
