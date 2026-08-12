import asyncio
import logging
from datetime import date, timedelta
from typing import List, Dict, Any
from src.tcbs.market import market_client
from src.data_pipeline.ohlcv_fetcher import OHLCVFetcher

logger = logging.getLogger("dominus-investor.scanner.data_fetcher")
ohlcv_fetcher = OHLCVFetcher()

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

                    # 4. Tai lich su gia ohlcv (90 ngày) dung de tinh Z-Score 50 va Abnormal Return
                    end_dt = date.today().strftime("%Y-%m-%d")
                    start_dt = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
                    ohlcv = await ohlcv_fetcher.fetch_history(symbol, start_dt, end_dt)

                    results[symbol] = {
                        "price_info": price_info,
                        "foreign_info": foreign_info,
                        "supply_demand": supply_demand,
                        "ohlcv": ohlcv
                    }
                except Exception as e:
                    logger.warning("Khong the tai data cho ma %s: %s", symbol, str(e))

        # Chay async song song
        await asyncio.gather(*(fetch_one(s) for s in symbols))
        logger.info("Tai thong tin hoan tat. Thanh cong: %s/%s ma.", len(results), len(symbols))
        return results

data_fetcher = ScannerDataFetcher()
