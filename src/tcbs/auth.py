import httpx
import logging
import time
import json
import os
import base64
from typing import Optional, Dict, Any
from src.config import settings

logger = logging.getLogger("dominus-investor.tcbs.auth")

TOKEN_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".tcbs_token")

class TCBSAuthenticator:
    def __init__(self):
        self.base_url = settings.TCBS_BASE_URL
        self.api_key = settings.TCBS_API_KEY
        self._token: Optional[str] = None
        self._expires_at: float = 0.0  # Unix timestamp
        self._otp_id: Optional[str] = None
        self._load_token_from_file()
        
    def _load_token_from_file(self):
        """Doc token da luu tu tep de tranh phai nhap lai OTP sau moi lan reload"""
        if os.path.exists(TOKEN_FILE_PATH):
            try:
                with open(TOKEN_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._token = data.get("token")
                    self._expires_at = data.get("expires_at", 0.0)
                    logger.info("Da khoi phuc JWT Token TCBS tu cache file. Con han den: %s", 
                                time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self._expires_at)))
            except Exception as e:
                logger.warning("Khong the doc token cache file: %s", str(e))

    def _save_token_to_file(self):
        """Ghi token xuong file de cache"""
        try:
            with open(TOKEN_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "token": self._token,
                    "expires_at": self._expires_at
                }, f)
            logger.info("Da luu JWT Token TCBS vao cache file.")
        except Exception as e:
            logger.error("Khong the ghi token vao cache file: %s", str(e))

    def clear_token(self):
        """Xoa file cache token va reset trang thai trong bo nho"""
        self._token = None
        self._expires_at = 0.0
        self._otp_id = None
        if os.path.exists(TOKEN_FILE_PATH):
            try:
                os.remove(TOKEN_FILE_PATH)
                logger.info("Da xoa file cache token TCBS.")
            except Exception as e:
                logger.error("Khong the xoa file cache token: %s", str(e))

    async def get_token(self, force_refresh: bool = False) -> str:
        """Lay token hien tai, kiem tra han dung."""
        now = time.time()
        
        # Con han su dung (buffer 5 phut)
        buffer_seconds = settings.JWT_REFRESH_BUFFER_MIN * 60
        if self._token and not force_refresh and (self._expires_at - now > buffer_seconds):
            return self._token
            
        if not self._token:
            raise ValueError("JWT Token TCBS chua duoc xac thuc hoac da het han. Vui long gui OTP tren giao dien.")
                
        return self._token

    def get_custody_code(self) -> str:
        """Giai ma custodyCode tu JWT token, neu loi hoac chua co thi lay tu settings"""
        if not self._token:
            return settings.TCBS_CUSTODY_CODE
            
        try:
            parts = self._token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                payload_json = base64.b64decode(payload_b64).decode("utf-8")
                payload = json.loads(payload_json)
                
                # Tim custodyCode trong payload
                for key in ["custodyID", "custodyCode", "custody_code", "username", "custodycd", "sub"]:
                    if key in payload and payload[key]:
                        val = str(payload[key]).strip().upper()
                        # Custody code TCBS luon co dang 105Cxxxxxx (10 ky tu)
                        if len(val) == 10 and val.isalnum() and val.startswith("105C"):
                            return val
        except Exception as e:
            logger.warning("Loi giai ma custody code tu token: %s. Su dung settings mac dinh.", str(e))
            
        return settings.TCBS_CUSTODY_CODE


    async def request_otp(self) -> str:
        """Buoc 1: Yeu cau OTP tu TCBS, tra ve otpId"""
        url = f"{self.base_url}/gaia/v1/oauth2/openapi/request-otp"
        body = {"apiKey": self.api_key}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                self._otp_id = data.get("otpId")
                logger.info("Yeu cau OTP thanh cong. Nhan duoc otpId: %s", self._otp_id)
                return self._otp_id
        except Exception as e:
            logger.error("Loi khi yeu cau OTP tu TCBS: %s", str(e))
            raise e

    async def submit_otp(self, otp: str, otp_id: Optional[str] = None) -> str:
        """Gui OTP de lay JWT Token (otpId la tuy chon)"""
        url = f"{self.base_url}/gaia/v1/oauth2/openapi/token"
        body = {
            "apiKey": self.api_key,
            "otp": otp
        }
        
        # Chi gui otpId len TCBS neu co gia tri va khong rong (danh cho SMS OTP)
        # Neu khong gui otpId, TCBS mac dinh hieu la Smart iOTP offline
        use_otp_id = otp_id if otp_id is not None else self._otp_id
        if use_otp_id and str(use_otp_id).strip():
            body["otpId"] = str(use_otp_id).strip()
            
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=body)
                response.raise_for_status()
                data = response.json()
                
                self._token = data.get("token")
                expires_in = data.get("expires_in") or 86400
                self._expires_at = time.time() + float(expires_in)
                
                self._save_token_to_file()
                logger.info("Xac thuc OTP va lay JWT Token TCBS thanh cong. Het han sau %s giay.", expires_in)
                return self._token
        except Exception as e:
            logger.error("Loi khi gui OTP de lay Token tu TCBS: %s", str(e))
            raise e

    def clear_token(self):
        """Xoa token hien tai va cache file khi phat hien token het han hoac bi loi 401"""
        self._token = None
        self._expires_at = 0.0
        if os.path.exists(TOKEN_FILE_PATH):
            try:
                os.remove(TOKEN_FILE_PATH)
                logger.info("Da xoa cache JWT Token TCBS do loi 401 hoac het han.")
            except Exception as e:
                logger.error("Khong the xoa cache file token: %s", str(e))


auth_provider = TCBSAuthenticator()

from functools import wraps

def catch_tcbs_unauthorized(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 401:
                logger.warning("Phat hien loi 401 tu TCBS. Dang xoa cache token...")
                auth_provider.clear_token()
            elif hasattr(e, "response") and hasattr(e.response, "status_code") and e.response.status_code == 401:
                logger.warning("Phat hien loi 401 tu TCBS. Dang xoa cache token...")
                auth_provider.clear_token()
            raise e
    return wrapper

# Trigger reload for empty token test
