import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
from src.config import settings

logger = logging.getLogger("dominus-investor.notifications.discord")

async def send_discord_alert(message: str, webhook_url: Optional[str] = None) -> bool:
    """Gui thong bao van ban toi Discord Webhook voi co che fallback"""
    target_url = webhook_url or getattr(settings, "DISCORD_WEBHOOK_URL", None)
    
    if not settings.DISCORD_ENABLED or not target_url or "your_webhook_here" in target_url:
        logger.info("[MOCK DISCORD ALERT] %s", message[:100])
        return True

    payload = {"content": message}
    return await _post_with_retry(target_url, payload)

async def send_discord_embed(
    embed_dict: Dict[str, Any],
    content: Optional[str] = None,
    webhook_url: Optional[str] = None,
    retry_count: int = 3
) -> bool:
    """
    Gui Rich Embed lenh/ban tin toi Discord Webhook chi dinh
    Kem co che retry toi da 3 lan khi gap loi mang hoac rate limit.
    """
    target_url = webhook_url or getattr(settings, "DISCORD_WEBHOOK_URL", None)

    if not settings.DISCORD_ENABLED or not target_url or "your_webhook_here" in target_url:
        logger.info("[MOCK DISCORD EMBED] Title: %s", embed_dict.get("title"))
        return True

    payload: Dict[str, Any] = {"embeds": [embed_dict]}
    if content:
        payload["content"] = content

    return await _post_with_retry(target_url, payload, max_retries=retry_count)

async def _post_with_retry(url: str, payload: Dict[str, Any], max_retries: int = 3) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=12.0) as resp:
                    if resp.status in [200, 204]:
                        logger.info("Gui Discord thanh cong (Lan thu %d).", attempt)
                        return True
                    elif resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", 2.0))
                        logger.warning("Discord rate limit 429. Cho %.1f giay truoc khi thu lai...", retry_after)
                        await asyncio.sleep(retry_after)
                    else:
                        text = await resp.text()
                        logger.error("Loi Discord Webhook (Status %s): %s", resp.status, text)
        except Exception as e:
            logger.warning("Loi ket noi Discord lan %d/%d: %s", attempt, max_retries, str(e))
            if attempt < max_retries:
                await asyncio.sleep(attempt * 1.5)

    return False
