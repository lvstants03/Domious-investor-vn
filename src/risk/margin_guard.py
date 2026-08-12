import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.tcbs.margin import margin_client
from src.database.models import MarginSnapshot
from src.notifications.discord import send_discord_alert

logger = logging.getLogger("dominus-investor.risk.margin_guard")

class MarginGuard:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_account_margin(self, account_id: str) -> dict:
        """Quet thong tin margin de giam sat rui ro tai khoan"""
        logger.info("Dang thuc hien giam sat margin cho tai khoan: %s...", account_id)
        
        try:
            # 1. Lay ty le hien tai tu TCBS Client
            margin_data = await margin_client.get_margin_ratio_risk()
            ratio = margin_data.get("margin_ratio", 100.0)
            status = margin_data.get("risk_status", "NORMAL")
            
            # Lay them thong tin no tu margin client
            debt_data = await margin_client.lookup_debt()
            total_debt = debt_data.get("total_debt", 0.0)

            # 2. Luu Snapshot vao DB
            snapshot = MarginSnapshot(
                account_id=account_id,
                margin_ratio=ratio,
                loan_balance=total_debt,
                risk_level=status,
                timestamp=datetime.utcnow()
            )
            self.db.add(snapshot)
            await self.db.flush()

            # 3. Canh bao qua Discord neu he so thap (WARNING / CALL / FORCE_SELL)
            if status != "NORMAL":
                level_mapping = {
                    "WARNING": "⚠️ **CẢNH BÁO MARGIN (WARNING)**",
                    "CALL": "🚨 **CUỘC GỌI KÝ QUỸ (MARGIN CALL)**",
                    "FORCE_SELL": "❌ **CƯỠNG CHẾ BÁN GIẢI CHẤP (FORCE SELL)**"
                }
                
                alert_title = level_mapping.get(status, "⚠️ **RỦI RO TÀI KHOẢN**")
                alert_msg = (
                    f"{alert_title}\n"
                    f"▪️ Tài khoản: **{account_id}**\n"
                    f"▪️ Tỷ lệ ký quỹ hiện tại: **{ratio}%**\n"
                    f"▪️ Tổng nợ vay hiện tại: **{total_debt:,.0f} VND**\n"
                    f"▪️ Trạng thái: **{status}**\n"
                    f"‼️ Vui lòng nộp thêm tiền hoặc bán bớt cổ phiếu để nâng tỷ lệ ký quỹ an toàn."
                )
                await send_discord_alert(alert_msg)
                
            return margin_data
            
        except Exception as e:
            logger.error("Loi khi quet ti le margin tai khoan %s: %s", account_id, str(e))
            return {}
