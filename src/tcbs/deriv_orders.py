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
        if settings.TCBS_API_KEY == "dummy_api_key":
            return [
                {
                    "symbol": "VN30F2608",
                    "position_type": "LONG",
                    "quantity": 2,
                    "avg_cost": 1320.5,
                    "current_price": 1325.0,
                    "unrealized_pnl": 900000.0  # 4.5 points * 2 contracts * 100,000 VND/point
                }
            ]

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
        if settings.TCBS_API_KEY == "dummy_api_key":
            import uuid
            order_id = f"DR-{uuid.uuid4().hex[:8].upper()}"
            logger.info("MOCK PLACE DERIV ORDER: %s %s contracts %s at %s (%s) -> ID: %s", action, qty, symbol, price, order_type, order_id)
            return {
                "order_id": order_id,
                "status": "SUCCESS",
                "message": "Lenh phai sinh dat thanh cong (MOCK)",
                "symbol": symbol,
                "action": action,
                "qty": qty,
                "price": price,
                "order_type": order_type
            }

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
        if settings.TCBS_API_KEY == "dummy_api_key":
            logger.info("MOCK MODIFY DERIV ORDER: ID %s to qty: %s, price: %s", order_id, qty, price)
            return {
                "order_id": order_id,
                "status": "SUCCESS",
                "message": "Lenh phai sinh sua thanh cong (MOCK)",
                "qty": qty,
                "price": price
            }

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
        if settings.TCBS_API_KEY == "dummy_api_key":
            logger.info("MOCK CANCEL DERIV ORDER: ID %s", order_id)
            return {
                "order_id": order_id,
                "status": "SUCCESS",
                "message": "Lenh phai sinh huy thanh cong (MOCK)"
            }

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
