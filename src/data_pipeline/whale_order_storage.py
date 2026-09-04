import asyncio
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import select
from src.database.connection import get_db_session
from src.database.models import WhaleOrderLog

logger = logging.getLogger("dominus-investor.data_pipeline.whale_order_storage")
VN_TZ = timezone(timedelta(hours=7))

class WhaleOrderStorage:
    """
    Quan ly luu tru ben vung va khoi phuc du lieu lenh Ca Map & Khoi Ngoai vao PostgreSQL.
    Su dung co che Batch Queue de toi uu hoa tai nguyen va I/O tren Render.
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running = False

    def enqueue(self, order: Dict[str, Any]) -> bool:
        """
        Validate va dua mot ban ghi lenh vao hang doi luu tru DB.
        Khong gay block luong xu ly chinh.
        """
        try:
            # 1. Validation co ban
            sym = str(order.get("symbol") or "").strip().upper()
            if not sym or len(sym) < 3 or len(sym) > 5 or not sym.isalpha():
                return False

            price = float(order.get("price") or 0.0)
            qty = int(order.get("qty") or order.get("volume") or 0)
            val = float(order.get("value") or order.get("value_vnd") or 0.0)
            side = str(order.get("side") or "BUY").strip().upper()
            side = "BUY" if side in ["BUY", "B", "MUA"] else "SELL"

            if price <= 0 or qty <= 0:
                return False

            if val <= 0:
                val = price * qty

            tier = str(order.get("tier") or ("FOREIGN" if order.get("is_foreign") else "SHARK")).strip().upper()

            time_str = str(order.get("time") or order.get("time_str") or datetime.now(VN_TZ).strftime("%H:%M:%S"))
            trade_date_val = order.get("trade_date")
            if not isinstance(trade_date_val, date):
                trade_date_val = datetime.now(VN_TZ).date()

            validated_record = {
                "symbol": sym,
                "trade_date": trade_date_val,
                "time_str": time_str,
                "side": side,
                "price": price,
                "volume": qty,
                "value_vnd": val,
                "tier": tier,
                "created_at": datetime.utcnow()
            }

            if self._queue.full():
                # Neu queue day, bo qua lenh cu nhat
                try:
                    self._queue.get_nowait()
                except Exception:
                    pass

            self._queue.put_nowait(validated_record)
            return True
        except Exception as e:
            logger.debug("Loi khi enqueue whale order: %s", str(e))
            return False

    async def start_worker(self):
        """Khoi chay worker ngam gom cum batch insert vao database"""
        if self._is_running:
            return
        self._is_running = True
        self._worker_task = asyncio.create_task(self._batch_flush_loop())
        logger.info("Whale order storage batch worker khoi dong thanh cong.")

    async def stop_worker(self):
        """Dung worker va flush toan bo lenh con lai trong queue"""
        self._is_running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await self._flush_all_remaining()

    async def _batch_flush_loop(self):
        """Vong lap doc tu queue va ghi vao CSDL dinh ky moi 3 giay hoac khi du 30 lenh"""
        while self._is_running:
            batch: List[Dict[str, Any]] = []
            try:
                # Cho lay it nhat 1 item voi timeout 3 giay
                try:
                    first_item = await asyncio.wait_for(self._queue.get(), timeout=3.0)
                    batch.append(first_item)
                except asyncio.TimeoutError:
                    pass

                # Hut toan bo items con lai trong queue toi da 50 ban ghi moi dot
                while not self._queue.empty() and len(batch) < 50:
                    batch.append(self._queue.get_nowait())

                if batch:
                    await self._insert_batch(batch)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Loi trong vong lap batch flush: %s", str(e))
                await asyncio.sleep(2.0)

    async def _flush_all_remaining(self):
        """Ghi toan bo nhung lenh con sot lai trong queue truoc khi tat app"""
        batch = []
        while not self._queue.empty():
            batch.append(self._queue.get_nowait())
        if batch:
            await self._insert_batch(batch)

    async def _insert_batch(self, batch: List[Dict[str, Any]]):
        """Thuc hien bulk insert vao bang whale_order_logs su dung SQLAlchemy session an toan"""
        if not batch:
            return
        try:
            async with get_db_session() as session:
                models = [WhaleOrderLog(**item) for item in batch]
                session.add_all(models)
                await session.commit()
                logger.debug("Da ghi thanh cong %d lenh ca map / khoi ngoai vao database.", len(batch))
        except Exception as e:
            logger.error("Loi khi bulk insert whale_order_logs: %s", str(e))

    async def warmup_from_db(self, target_date: Optional[date] = None) -> int:
        """
        Doc toan bo lenh cua ngay hom nay tu bang whale_order_logs nạp vao RAM
        giup phuc hoi tuc thi giao dien dashboard sau khi Render deploy lai.
        """
        if target_date is None:
            target_date = datetime.now(VN_TZ).date()

        try:
            from src.data_pipeline.big_order_tracker import big_order_tracker
            async with get_db_session() as session:
                stmt = (
                    select(WhaleOrderLog)
                    .where(WhaleOrderLog.trade_date == target_date)
                    .order_by(WhaleOrderLog.created_at.asc())
                )
                result = await session.execute(stmt)
                records = result.scalars().all()

                if not records:
                    logger.info("Chua co lenh ca map / khoi ngoai nao trong CSDL cho ngay %s.", target_date)
                    return 0

                logger.info("Tim thay %d lenh trong CSDL ngay %s. Dang nap phuc hoi vao bo nho RAM...", len(records), target_date)
                loaded_count = big_order_tracker.populate_from_db_records(records)
                logger.info("Phuc hoi thanh cong %d lenh vao BigOrderTracker.", loaded_count)
                return loaded_count
        except Exception as e:
            logger.error("Loi khi warmup whale orders tu CSDL: %s", str(e))
            return 0

whale_order_storage = WhaleOrderStorage()
