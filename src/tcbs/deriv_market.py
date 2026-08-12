import httpx
import logging
from typing import Dict, Any
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.deriv_market")

class TCBSDerivativesMarketClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def get_deriv_price(self, symbol: str) -> Dict[str, Any]:
        """7.1. Thong tin ma, gia phai sinh (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {
                "symbol": symbol,
                "current_price": 1325.0,
                "change": 4.5,
                "percent_change": 0.34,
                "open_interest": 42500,
                "basis": -2.3,
                "trading_volume": 125000,
                "highest": 1328.0,
                "lowest": 1318.5
            }

        url = f"{self.base_url}/market/derivatives/{symbol}/price"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay thong tin gia phai sinh ma %s: %s", symbol, str(e))
            raise e

deriv_market_client = TCBSDerivativesMarketClient()
