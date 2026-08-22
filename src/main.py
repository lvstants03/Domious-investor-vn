import sys
import io

# Thiết lập encoding UTF-8 mặc định cho stdout/stderr trên Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uvicorn
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.config import settings
from src.api.routes import router as api_router
from src.api.ws import router as ws_router

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logger = logging.getLogger("dominus-investor")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Khởi động dịch vụ DOMINUS Investor...")
    
    # Tu dong khoi tao database neu chua ton tai
    from src.database.connection import init_db
    await init_db()
    
    # Khoi dong bot scheduler khi chay
    from src.bot.scheduler import bot_scheduler
    from src.notifications.discord_bot import discord_bot
    
    # Khoi dong Discord Bot Client tuong tac
    await discord_bot.start()
    
    # Khoi dong TCBS Socket Manager
    from src.tcbs.socket_manager import socket_manager
    await socket_manager.start_all()
    
    # Khoi dong tien trinh seed du lieu Whale Tracker tu dong o background
    from src.data_pipeline.big_order_tracker import big_order_tracker
    import asyncio
    asyncio.create_task(big_order_tracker.seed_from_market_api())
    
    bot_scheduler.start()
    yield
    logger.info("Đang tắt dịch vụ DOMINUS Investor...")
    
    from src.tcbs.socket_manager import socket_manager
    await socket_manager.stop_all()
    
    bot_scheduler.stop()
    await discord_bot.stop()

app = FastAPI(
    title="DOMINUS Investor Service",
    description="Microservice phân tích thị trường & bot giao dịch tự động tích hợp TCBS iFlash Open API.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(api_router)
app.include_router(ws_router)

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8082,
        reload=True
    )



