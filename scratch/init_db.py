import asyncio
import sys
import os

# Them thu muc cha vao sys.path de import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.connection import init_db
from src.config import settings

async def main():
    print(f"Khoi tao cac bang CSDL cho dominus-investor...")
    print(f"DATABASE_URL dang su dung: {settings.DATABASE_URL}")
    await init_db()
    print("Hoan thanh khoi tao CSDL.")

if __name__ == "__main__":
    asyncio.run(main())
