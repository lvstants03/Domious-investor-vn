import httpx
import logging
from typing import Optional, Dict, Any, List
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.deriv_orders")

class TCBSDerivativesOrderClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def get_positions(self) -> List[Dict[str, Any]]:
        """6.x. Vi the phai sinh"""
        url = f"{self.base_url}/orders/derivatives/positions"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay danh sach vi the phai sinh: %s", str(e))
            raise e

    async def place_deriv_order(self, symbol: str, action: str, qty: int, price: float, order_type: str = "LO") -> Dict[str, Any]:
        """6.x. Dat lenh phai sinh"""
        url = f"{self.base_url}/orders/derivatives"
        body = {
            "symbol": symbol,
            "action": action.upper(),  # BUY or SELL
            "quantity": qty,
            "price": price,
            "order_type": order_type
        }
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi dat lenh phai sinh %s %s: %s", action, symbol, str(e))
            raise e

    async def modify_deriv_order(self, order_id: str, qty: int, price: float) -> Dict[str, Any]:
        """6.x. Sua lenh phai sinh"""
        url = f"{self.base_url}/orders/derivatives/{order_id}"
        body = {
            "quantity": qty,
            "price": price
        }
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.put(url, json=body, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi sua lenh phai sinh ID %s: %s", order_id, str(e))
            raise e

    async def cancel_deriv_order(self, order_id: str) -> Dict[str, Any]:
        """6.x. Huy lenh phai sinh"""
        url = f"{self.base_url}/orders/derivatives/{order_id}"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi huy lenh phai sinh ID %s: %s", order_id, str(e))
            raise e

deriv_order_client = TCBSDerivativesOrderClient()
