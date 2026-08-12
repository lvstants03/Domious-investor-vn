import httpx
import logging
from typing import Dict, Any, List
from src.config import settings
from src.tcbs.auth import auth_provider

logger = logging.getLogger("dominus-investor.tcbs.margin")

class TCBSMarginClient:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL

    async def _get_headers(self) -> Dict[str, str]:
        token = await auth_provider.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

    async def get_margin_limit(self) -> Dict[str, Any]:
        """4.10. Han muc margin (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {"margin_limit": 1000000000.0, "used_limit": 300000000.0, "available_limit": 700000000.0}

        url = f"{self.base_url}/margin/limit"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay han muc margin: %s", str(e))
            raise e

    async def get_margin_ratio_risk(self) -> Dict[str, Any]:
        """4.11. Ty le margin & rui ro (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {
                "margin_ratio": 55.4,          # Ty le thuc te
                "maintenance_ratio": 40.0,     # Ty le duy tri
                "call_ratio": 35.0,            # Ty le call margin
                "force_sell_ratio": 30.0,      # Ty le giai chap
                "risk_status": "NORMAL"        # NORMAL | WARNING | CALL | FORCE_SELL
            }

        url = f"{self.base_url}/margin/ratio"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay ty le margin & rui ro: %s", str(e))
            raise e

    async def get_loan_packages(self) -> List[Dict[str, Any]]:
        """4.12. Goi vay bo tro (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return [
                {"package_id": "T10", "name": "Vay 10 ngay uu dai", "interest_rate_annual": 8.5},
                {"package_id": "T90", "name": "Vay thuong 90 ngay", "interest_rate_annual": 11.5}
            ]

        url = f"{self.base_url}/margin/packages"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay danh sach goi vay bo tro: %s", str(e))
            raise e

    async def get_loans(self) -> List[Dict[str, Any]]:
        """4.13. Danh sach khoan vay (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return [
                {
                    "loan_id": "L-12345",
                    "package_id": "T90",
                    "principal": 300000000.0,
                    "interest_accrued": 1245000.0,
                    "start_date": "2026-07-01",
                    "due_date": "2026-09-28"
                }
            ]

        url = f"{self.base_url}/margin/loans"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay danh sach khoan vay: %s", str(e))
            raise e

    async def lookup_debt(self) -> Dict[str, Any]:
        """4.17. Tra cuu no (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return {
                "total_debt": 301245000.0,
                "principal_debt": 300000000.0,
                "interest_debt": 1245000.0,
                "fee_debt": 0.0
            }

        url = f"{self.base_url}/margin/debt"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi tra cuu no margin: %s", str(e))
            raise e

    async def get_interest_packages(self) -> List[Dict[str, Any]]:
        """4.18. Tra cuu goi lai suat margin (GET)"""
        if settings.TCBS_API_KEY == "dummy_api_key":
            return [
                {"package_code": "VIP_TCBS", "interest_rate": 9.9, "duration_days": 365}
            ]

        url = f"{self.base_url}/margin/interest-packages"
        try:
            headers = await self._get_headers()
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error("Loi khi lay danh sach goi lai suat margin: %s", str(e))
            raise e

margin_client = TCBSMarginClient()
