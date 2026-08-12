import logging
import aiohttp
from src.config import settings

logger = logging.getLogger("dominus-investor.notifications.discord")

async def send_discord_alert(message: str) -> bool:
    """Gui thong bao toi Discord Webhook"""
    
    # Kiem tra xem co bat thong bao Discord khong
    if not settings.DISCORD_ENABLED:
        logger.info("[MOCK DISCORD ALERT] %s", message)
        return True

    # Lay Discord Webhook tu config / env
    # Neu can lay bot token hoac chat id rieng: co the dung webhook rieng
    webhook_url = getattr(settings, "DISCORD_WEBHOOK_URL", None)
    if not webhook_url or webhook_url == "https://discord.com/api/webhooks/your_webhook_here":
        logger.warning("Discord webhook URL chua duoc cau hinh hop le.")
        logger.info("[FALLBACK DISCORD ALERT] %s", message)
        return False

    payload = {
        "content": message
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload, timeout=10.0) as response:
                if response.status in [200, 204]:
                    logger.info("Gui thong bao toi Discord thanh cong.")
                    return True
                else:
                    text = await response.text()
                    logger.error("Loi khi gui Discord Webhook (%s): %s", response.status, text)
                    return False
    except Exception as e:
        logger.error("Loi ket noi khi gui thong bao Discord: %s", str(e))
        return False
