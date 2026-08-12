import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.repository import InvestorRepository
from src.scanner.universe import get_scan_symbols
from src.scanner.data_fetcher import data_fetcher
from src.scanner.scorer import scorer
from src.notifications.discord_bot import discord_bot

logger = logging.getLogger("dominus-investor.scanner.runner")

class ScannerRunner:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = InvestorRepository(db)

    async def run_scan(self, scan_type: str = "intraday") -> int:
        """
        Thuc hien quet toan bo thi truong dua tren universe.
        
        Returns:
            So luong tin hieu duoc phat hien va gui di.
        """
        logger.info("Bat dau chu ky quet co phieu (%s)...", scan_type)
        
        try:
            # 1. Lay danh sach ma trong universe
            symbols = await get_scan_symbols(self.db)
            if not symbols:
                logger.warning("Danh sach ma scan trong. Huy scan.")
                return 0

            # 2. Fetch market data tu TCBS client
            all_data = await data_fetcher.fetch_all_market_data(symbols)
            if not all_data:
                logger.warning("Khong fetch duoc bat ky market data nao. Huy scan.")
                return 0

            # 3. Scorer danh gia va xep hang
            scored_list = scorer.score_all(all_data)
            
            # 4. Filter va alert
            alert_count = 0
            rank = 1
            
            for symbol, score, details in scored_list:
                # Lay gia va volume tai thoi diem scan
                data = all_data[symbol]
                price = data["price_info"].get("price", 0.0)
                vol = data["price_info"].get("volume", 0)
                foreign_buy = data["foreign_info"].get("net_buy_value", 0.0)

                # Liet ke ly do de thong bao
                reasons = []
                if details["volume_flow"] >= 70:
                    reasons.append(f"Dong tien manh (Volume: {vol:,} CP, Khoi ngoai: +{foreign_buy/1e9:.1f} Ty)")
                if details["technical"] >= 70:
                    reasons.append("Chi bao ky thuat (RSI, MACD) dang vao form tang gia")
                if details["momentum"] >= 70:
                    reasons.append("Da tang gia giu vung va huong len")

                # Luu vao DB
                action_taken = None
                await self.repo.save_scan_result(
                    symbol=symbol,
                    composite=score,
                    tech=details["technical"],
                    volume=details["volume_flow"],
                    momentum=details["momentum"],
                    risk=10.0,  # Gia tri mac dinh cho risk score
                    signals={"details": details},
                    price=price,
                    vol=vol,
                    foreign_buy=foreign_buy,
                    rank=rank
                )
                
                # Chi gui alert neu composite score >= 70
                if score >= 70:
                    alert_count += 1
                    logger.info("PHAT HIEN MA TIEM NANG: %s | Score: %s", symbol, score)
                    
                    # Gui qua Discord Bot voi Buttons tuong tac
                    await discord_bot.send_scan_alert(
                        symbol=symbol,
                        price=price,
                        score=score,
                        reasons=reasons
                    )
                
                rank += 1
                
            logger.info("Chu ky quet hoan tat. Tim thay %s ma dat chuan.", alert_count)
            return alert_count
            
        except Exception as e:
            logger.error("Loi khi thuc hien scan co phieu: %s", str(e), exc_info=True)
            return 0
pre_market_runner = None  # Placeholder
