import httpx
import logging
from typing import Dict, Any, List
from src.config import settings
from src.tcbs.auth import auth_provider, catch_tcbs_unauthorized

logger = logging.getLogger("dominus-investor.tcbs.market")

class TCBSMarketClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    # --- Mock Helpers ---
    def _mock_price_info(self, symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "price": 128500.0 if symbol == "FPT" else 74200.0,
            "change": 1500.0,
            "percent_change": 1.18,
            "open": 127000.0,
            "high": 129000.0,
            "low": 126500.0,
            "volume": 2850000,
            "total_val": 365000000000
        }

    def _mock_foreign_room(self, symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "foreign_owned_pct": 49.0 if symbol == "FPT" else 15.4,
            "foreign_room_left": 0 if symbol == "FPT" else 150000000,
            "net_buy_volume": 120000,
            "net_buy_value": 15420000000
        }

    def _mock_deals(self, symbol: str) -> List[Dict[str, Any]]:
        return [
            {"price": 128000.0, "volume": 500000, "value": 64000000000, "time": "14:15:22"}
        ]

    def _mock_match_history(self, symbol: str) -> List[Dict[str, Any]]:
        return [
            {"price": 128500.0, "volume": 5000, "time": "14:29:59"},
            {"price": 128400.0, "volume": 12000, "time": "14:29:45"},
            {"price": 128500.0, "volume": 2000, "time": "14:29:30"}
        ]

    def _mock_supply_demand_15m(self, symbol: str) -> List[Dict[str, Any]]:
        return [
            {"time": "14:15", "buy_vol": 150000, "sell_vol": 120000, "match_price": 128300.0},
            {"time": "14:30", "buy_vol": 220000, "sell_vol": 140000, "match_price": 128500.0}
        ]

    def _mock_supply_demand_daily(self, symbol: str) -> List[Dict[str, Any]]:
        return [
            {"date": "2026-08-06", "buy_vol": 2500000, "sell_vol": 2100000, "close": 127000.0},
            {"date": "2026-08-07", "buy_vol": 2850000, "sell_vol": 2400000, "close": 128500.0}
        ]

    def _mock_supply_demand_monthly(self, symbol: str) -> List[Dict[str, Any]]:
        return [
            {"month": "2026-07", "buy_vol": 45000000, "sell_vol": 42000000, "avg_price": 122000.0},
            {"month": "2026-08", "buy_vol": 12000000, "sell_vol": 10000000, "avg_price": 127500.0}
        ]

    def _mock_ticker_info(self, symbol: str) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "company_name": "Cong ty Co phan FPT" if symbol == "FPT" else f"Cong ty Co phan {symbol}",
            "exchange": "HOSE",
            "industry": "Cong nghe thong tin" if symbol == "FPT" else "Tai chinh",
            "market_cap": 182000000000000 if symbol == "FPT" else 155000000000000,
            "shares_outstanding": 1460000000 if symbol == "FPT" else 2090000000
        }

    # --- API Methods ---
    @catch_tcbs_unauthorized
    async def get_price_info(self, symbol: str) -> Dict[str, Any]:
        """Lấy giá cổ phiếu thời gian thực từ /tartarus/v1/tickerCommons"""
        url = f"{self.base_url}/tartarus/v1/tickerCommons?tickers={symbol}"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                # Trich xuat phan tu dau tien trong mang data
                if "data" in data and len(data["data"]) > 0:
                    item = data["data"][0]
                    return {
                        "symbol": item.get("symbol", symbol),
                        "price": float(item.get("matchPrice", 0.0)),
                        "change": float(item.get("change", 0.0)),
                        "percent_change": float(item.get("changePercent", 0.0)),
                        "open": float(item.get("open", 0.0)),
                        "high": float(item.get("high", 0.0)),
                        "low": float(item.get("low", 0.0)),
                        "volume": int(item.get("totalVol", 0)),
                        "total_val": float(item.get("totalVal", 0.0))
                    }
                else:
                    raise ValueError(f"Khong tim thay thong tin cho ma {symbol}")
        except Exception as e:
            logger.error("Loi khi lay thong tin gia ma %s tu TCBS: %s", symbol, str(e))
            raise e

    @catch_tcbs_unauthorized
    async def get_foreign_room(self, symbol: str) -> Dict[str, Any]:
        """Lấy thông tin room nước ngoài từ /tartarus/v1/tickerSnaps"""
        # Thử tìm kiếm trong rổ HOSE (index=1), HNX (index=3) và Upcom (index=5)
        indices = [1, 3, 5]
        for idx in indices:
            url = f"{self.base_url}/tartarus/v1/tickerSnaps?index={idx}"
            try:
                headers = await self._get_headers()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        if "data" in data:
                            for item in data["data"]:
                                if item.get("symbol") == symbol:
                                    buy_qtty = float(item.get("buyForeignQtty") or 0)
                                    sell_qtty = float(item.get("sellForeignQtty") or 0)
                                    match_price = float(item.get("matchPrice") or 0.0)
                                    net_buy_vol = buy_qtty - sell_qtty
                                    return {
                                        "symbol": symbol,
                                        "foreign_owned_pct": 0.0,
                                        "foreign_room_left": float(item.get("room") or 0),
                                        "net_buy_volume": net_buy_vol,
                                        "net_buy_value": net_buy_vol * match_price
                                    }
            except Exception as e:
                logger.warning("Loi khi quet tickerSnaps index %d cho ma %s: %s", idx, symbol, str(e))
        
        raise ValueError(f"Khong tim thay thong tin room nuoc ngoai cho ma {symbol}")

    @catch_tcbs_unauthorized
    async def get_put_through_deals(self, symbol: str) -> List[Dict[str, Any]]:
        """Lấy thông tin giao dịch thỏa thuận thực tế của TCBS từ /tartarus/v1/putThroughSnaps"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            # Trả về dummy deals chất lượng cao để demo dòng tiền ngầm khi chạy giả lập
            import random
            from datetime import datetime, timedelta
            now = datetime.now()
            deals = []
            if symbol in ["HPG", "VIC", "FPT", "GEE"]:
                # Tạo 1 deal thỏa thuận lớn
                price = 28000.0 if symbol == "HPG" else 42000.0 if symbol == "VIC" else 130000.0
                vol = random.randint(5, 15) * 100000 # 500k to 1.5M
                pct_diff = random.choice([3.2, 4.5, -2.5, -4.0])
                deal_price = price * (1 + pct_diff / 100)
                deals.append({
                    "time": (now - timedelta(minutes=random.randint(10, 60))).strftime("%H:%M:%S"),
                    "volume": vol,
                    "price": round(deal_price, 1),
                    "value": vol * deal_price,
                    "price_diff_pct": pct_diff
                })
            return deals

        # Gọi API thực tế từ TCBS
        url = f"{self.base_url}/tartarus/v1/putThroughSnaps"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    deals = []
                    for item in data.get("data", []):
                        if item.get("symbol") == symbol:
                            vol = float(item.get("totalVol") or 0.0)
                            price = float(item.get("price") or 0.0)
                            ref_price = float(item.get("refPrice") or price or 1.0)
                            price_diff = ((price - ref_price) / ref_price) * 100
                            deals.append({
                                "time": item.get("time", "15:00:00"),
                                "volume": vol,
                                "price": price,
                                "value": vol * price,
                                "price_diff_pct": round(price_diff, 2)
                            })
                    return deals
                return []
        except Exception as e:
            logger.warning("Loi khi lay putThroughSnaps tu TCBS cho ma %s: %s", symbol, str(e))
            return []

    async def get_deals(self, symbol: str) -> List[Dict[str, Any]]:
        """Fallback get_deals goi den put_through_deals"""
        return await self.get_put_through_deals(symbol)

    @catch_tcbs_unauthorized
    async def get_match_history(self, symbol: str) -> List[Dict[str, Any]]:
        """Lấy lịch sử khớp lệnh khớp trong phiên từ /nyx/v1/intraday/{ticker}/his/paging"""
        url = f"{self.base_url}/nyx/v1/intraday/{symbol}/his/paging?page=0&size=50"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "data" in data:
                    result = []
                    for item in data["data"]:
                        result.append({
                            "price": float(item.get("p", 0.0)),
                            "volume": int(item.get("v", 0)),
                            "time": item.get("t", "")
                        })
                    return result
                return []
        except Exception as e:
            logger.error("Loi khi lay lich su khop ma %s tu TCBS: %s", symbol, str(e))
            raise e

    async def get_supply_demand_15m(self, symbol: str) -> List[Dict[str, Any]]:
        """Lấy cung cầu 15 phút (Trống do TCBS openapi khong ho tro)"""
        return []

    async def get_supply_demand_daily(self, symbol: str) -> List[Dict[str, Any]]:
        """Lấy cung cầu hàng ngày (Trống do TCBS openapi khong ho tro)"""
        return []

    async def get_supply_demand_monthly(self, symbol: str) -> List[Dict[str, Any]]:
        """Lấy cung cầu hàng tháng (Trống do TCBS openapi khong ho tro)"""
        return []

    async def lookup_ticker_info(self, symbol: str) -> Dict[str, Any]:
        """Tra cứu thông tin cơ bản chứng khoán"""
        return {
            "symbol": symbol,
            "company_name": f"Cong ty Co phan {symbol}",
            "exchange": "HOSE",
            "industry": "Chua xac dinh",
            "market_cap": 0,
            "shares_outstanding": 0
        }

    @catch_tcbs_unauthorized
    async def get_all_foreign_rooms(self) -> Dict[str, Dict[str, Any]]:
        """Tải trước room nước ngoài của tất cả các sàn (HOSE, HNX, UPCOM) để cache"""
        cache = {}
        indices = [1, 3, 5]
        for idx in indices:
            url = f"{self.base_url}/tartarus/v1/tickerSnaps?index={idx}"
            try:
                headers = await self._get_headers()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        if "data" in data:
                            for item in data["data"]:
                                symbol = item.get("symbol")
                                if symbol:
                                    buy_qtty = float(item.get("buyForeignQtty") or 0)
                                    sell_qtty = float(item.get("sellForeignQtty") or 0)
                                    match_price = float(item.get("matchPrice") or 0.0)
                                    net_buy_vol = buy_qtty - sell_qtty
                                    cache[symbol] = {
                                        "symbol": symbol,
                                        "foreign_owned_pct": 0.0,
                                        "foreign_room_left": float(item.get("room") or 0),
                                        "net_buy_volume": net_buy_vol,
                                        "net_buy_value": net_buy_vol * match_price
                                    }
            except Exception as e:
                logger.warning("Loi khi quet tickerSnaps index %d cho cache: %s", idx, str(e))
        return cache


market_client = TCBSMarketClient()
