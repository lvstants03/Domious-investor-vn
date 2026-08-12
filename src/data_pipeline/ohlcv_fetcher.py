import asyncio
import logging
import os
from datetime import date, timedelta
from typing import List, Dict, Optional
import pandas as pd

# Fix Unicode encoding error tren Windows khi vnstock in banner tieng Viet
os.environ.setdefault("PYTHONUTF8", "1")

logger = logging.getLogger("dominus-investor.data_pipeline.ohlcv_fetcher")


class OHLCVFetcher:
    """Lay du lieu OHLCV lich su tu vnstock v4 (nguon VCI)."""

    RATE_LIMIT_DELAY = 0.5  # giay giua cac request de tranh bi block

    def fetch_history_sync(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        Lay OHLCV lich su cho 1 ma. Chay dong bo (dung cho batch processing).
        Dung vnstock v4 API: vnstock.api.quote.Quote(symbol, source='VCI')
        Tra ve DataFrame [symbol, trade_date, open, high, low, close, volume] hoac None neu loi.
        """
        try:
            # vnstock v4: su dung Quote API moi, source ho tro: KBS, VCI, MSN, FMP
            from vnstock.api.quote import Quote
            q = Quote(symbol=symbol, source="VCI")
            df = q.history(start=start_date, end=end_date, interval="1D")
            if df is None or df.empty:
                logger.warning("Khong co du lieu OHLCV cho ma %s tu %s den %s", symbol, start_date, end_date)
                return None
            # Chuan hoa ten cot: 'time' -> 'trade_date'
            if "time" in df.columns:
                df = df.rename(columns={"time": "trade_date"})
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df["symbol"] = symbol.upper()
            # Loai bo hang co du lieu thieu
            required_cols = ["trade_date", "open", "high", "low", "close", "volume"]
            df = df.dropna(subset=required_cols)
            return df[["symbol", "trade_date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.error("Loi khi lay OHLCV cho ma %s: %s", symbol, str(e))
            return None

    async def fetch_history(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """Async wrapper de chay fetch trong thread pool tranh block event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_history_sync, symbol, start_date, end_date)

    async def backfill_all(self, symbols: List[str], years: int = 2) -> Dict[str, pd.DataFrame]:
        """
        Tai lich su N nam cho toan bo Universe.
        Tra ve dict {symbol: DataFrame}.
        """
        end_date = date.today().strftime("%Y-%m-%d")
        start_date = (date.today() - timedelta(days=365 * years)).strftime("%Y-%m-%d")

        logger.info("Bat dau backfill %d ma tu %s den %s...", len(symbols), start_date, end_date)
        results = {}

        for i, symbol in enumerate(symbols):
            df = await self.fetch_history(symbol, start_date, end_date)
            if df is not None and not df.empty:
                results[symbol] = df
                logger.info("[%d/%d] Backfill %s: %d phien", i + 1, len(symbols), symbol, len(df))
            else:
                logger.warning("[%d/%d] Bỏ qua %s: khong co du lieu", i + 1, len(symbols), symbol)
            await asyncio.sleep(self.RATE_LIMIT_DELAY)

        logger.info("Backfill hoan tat: %d/%d ma thanh cong.", len(results), len(symbols))
        return results

    async def sync_daily(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Cap nhat phien moi nhat cho toan bo Universe (chay sau 16h30 moi ngay).
        Chi lay 5 phien gan nhat de dam bao khong bi gap.
        """
        end_date = date.today().strftime("%Y-%m-%d")
        start_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

        logger.info("Daily sync cho %d ma...", len(symbols))
        results = {}

        for symbol in symbols:
            df = await self.fetch_history(symbol, start_date, end_date)
            if df is not None and not df.empty:
                results[symbol] = df
            await asyncio.sleep(self.RATE_LIMIT_DELAY)

        logger.info("Daily sync hoan tat: %d ma.", len(results))
        return results


ohlcv_fetcher = OHLCVFetcher()
