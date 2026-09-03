import logging
from datetime import datetime
from typing import Dict, Any, Optional
from src.config import settings
from src.notifications.discord import send_discord_embed

logger = logging.getLogger("dominus-investor.publish.discord_channels")

class DiscordChannelPublisher:
    """
    Module phu trach xuat ban noi dung toi 4 kenh Discord rieng biet
    su dung Rich Embed format chuyen nghiep.
    """

    def _get_webhook_for_channel(self, channel_key: str) -> Optional[str]:
        mapping = {
            "ban_tin_sang": getattr(settings, "DISCORD_WEBHOOK_MORNING", None),
            "ca_map_alert": getattr(settings, "DISCORD_WEBHOOK_SHARK", None),
            "tong_ket_phien": getattr(settings, "DISCORD_WEBHOOK_CLOSE", None),
            "phan_tich_tuan": getattr(settings, "DISCORD_WEBHOOK_WEEKLY", None),
        }
        return mapping.get(channel_key) or getattr(settings, "DISCORD_WEBHOOK_URL", None)

    async def publish_morning_brief(self, text_content: str, date_str: Optional[str] = None) -> bool:
        """Xuat ban Ban Tin Sang toi kenh #ban-tin-sang"""
        d_str = date_str or datetime.now().strftime("%d/%m/%Y")
        webhook = self._get_webhook_for_channel("ban_tin_sang")

        embed = {
            "title": f"[DOMINUS CAPITAL] BAN TIN SANG | {d_str}",
            "description": text_content,
            "color": 0x00FF88,  # Emerald Green
            "footer": {
                "text": "Dominus Media Intelligence Engine | 5-Layer Quant x News Catalyst"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        return await send_discord_embed(embed_dict=embed, webhook_url=webhook)

    async def publish_shark_alert(self, symbol: str, sector: str, net_ty: float, reason: str) -> bool:
        """Xuat ban Canh Bao Ca Map toi kenh #ca-map-alert"""
        webhook = self._get_webhook_for_channel("ca_map_alert")
        color = 0x00E5FF if net_ty > 0 else 0xFF3366

        embed = {
            "title": f"CANH BAO CA MAP GOM: {symbol} (+{net_ty:.1f} Ty VND)",
            "description": f"Phat hien lenh gom lon dot bien tu Smart Money tren san.",
            "color": color,
            "fields": [
                {"name": "Ma co phieu", "value": symbol, "inline": True},
                {"name": "Nhom nganh", "value": sector, "inline": True},
                {"name": "Gia tri gom rong", "value": f"{net_ty:+.1f} Ty", "inline": True},
                {"name": "Danh gia chi tiet", "value": reason, "inline": False}
            ],
            "footer": {
                "text": "Real-time Whale Tracker | Dominus Investor"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        return await send_discord_embed(embed_dict=embed, webhook_url=webhook)

    async def publish_session_close(self, text_content: str) -> bool:
        """Xuat ban Tong Ket Phien toi kenh #tong-ket-phien"""
        d_str = datetime.now().strftime("%d/%m/%Y")
        webhook = self._get_webhook_for_channel("tong_ket_phien")

        embed = {
            "title": f"[DOMINUS CAPITAL] TONG KET PHIEN GIAO DICH | {d_str}",
            "description": text_content,
            "color": 0x9966FF,  # Purple
            "footer": {
                "text": "Dominus Capital Daily Market Wrap"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        return await send_discord_embed(embed_dict=embed, webhook_url=webhook)

    async def publish_weekly_analysis(self, text_content: str) -> bool:
        """Xuat ban Bao Cao Chien Luoc Tuan toi kenh #phan-tich-tuan"""
        webhook = self._get_webhook_for_channel("phan_tich_tuan")

        embed = {
            "title": "[DOMINUS CAPITAL] CHIEN LUOC & DANH MUC DAU TU TUAN",
            "description": text_content,
            "color": 0xFFA500,  # Gold/Orange
            "footer": {
                "text": "Dominus Weekly Portfolio Strategy"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        return await send_discord_embed(embed_dict=embed, webhook_url=webhook)

discord_publisher = DiscordChannelPublisher()
