import httpx
import logging
from typing import Dict, Any
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.money")

class TCBSMoneyClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def transfer_internal(self, amount: float, from_account: str, to_account: str) -> Dict[str, Any]:
        """3.1. Chuyen tien noi bo (POST)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {"status": "SUCCESS", "message": f"Da chuyen {amount} tu {from_account} sang {to_account} (MOCK)"}

        url = f"{self.base_url}/money/transfer"
        body = {
            "amount": amount,
            "from_account": from_account,
            "to_account": to_account
        }
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi chuyen tien noi bo: %s", str(e))
            raise e

    async def deposit_margin(self, amount: float, account_id: str) -> Dict[str, Any]:
        """3.3. Nop ky quy (POST)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {"status": "SUCCESS", "message": f"Da nop ky quy {amount} vao tai khoan {account_id} (MOCK)"}

        url = f"{self.base_url}/money/margin/deposit"
        body = {
            "amount": amount,
            "account_id": account_id
        }
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi nop ky quy: %s", str(e))
            raise e

    async def withdraw_margin(self, amount: float, account_id: str) -> Dict[str, Any]:
        """3.2. Rut ky quy (POST)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {"status": "SUCCESS", "message": f"Da rut ky quy {amount} tu tai khoan {account_id} (MOCK)"}

        url = f"{self.base_url}/money/margin/withdraw"
        body = {
            "amount": amount,
            "account_id": account_id
        }
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi rut ky quy: %s", str(e))
            raise e

money_client = TCBSMoneyClient()
