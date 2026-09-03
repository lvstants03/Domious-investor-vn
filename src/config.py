from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    TCBS_API_KEY: str = "dummy_api_key"
    TCBS_BASE_URL: str = "https://openapi.tcbs.com.vn"
    TCBS_CUSTODY_CODE: str = "105C123456"

    
    DATABASE_URL: str = "postgresql+asyncpg://postgres:123@db:5432/markovlotteai"
    
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_CHANNEL_ID: Optional[str] = None
    DISCORD_ENABLED: bool = False
    
    TRADING_MODE: str = "paper"  # 'paper' or 'live'
    MAX_CONCURRENT_BOTS: int = 10
    DEFAULT_STOP_LOSS_PCT: float = 5.0
    DEFAULT_TAKE_PROFIT_PCT: float = 10.0
    DEFAULT_MAX_DRAWDOWN_PCT: float = 15.0
    
    JWT_REFRESH_BUFFER_MIN: int = 5
    LOG_LEVEL: str = "INFO"
    
    # Dominus Media Intelligence & Gemini
    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"
    
    # Discord Multi-Channel Webhooks
    DISCORD_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_MORNING: Optional[str] = None
    DISCORD_WEBHOOK_SHARK: Optional[str] = None
    DISCORD_WEBHOOK_CLOSE: Optional[str] = None
    DISCORD_WEBHOOK_WEEKLY: Optional[str] = None
    
    # News Crawler & Catalyst Parameters
    CRAWL_INTERVAL_TRADING_MIN: int = 15
    CRAWL_INTERVAL_OFFHOURS_MIN: int = 90
    TRADING_START: str = "08:30"
    TRADING_END: str = "16:00"
    NEWS_BOOST_MAX: float = 15.0
    NEWS_IMPACT_THRESHOLD: float = 6.0
    NEWS_URGENCY_HOURS: int = 2
    
    model_config = SettingsConfigDict(
        env_file=__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
