import time
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict
from src.data_pipeline.sector_map import get_sector_by_symbol

logger = logging.getLogger("dominus-investor.data_pipeline.foreign_order_detector")

CLUSTER_WINDOW_SECONDS = 120.0       # Cua so 120 giay de gom lenh nho lien tiep
CLUSTER_MIN_VALUE_VND = 300_000_000   # Nguong 300 trieu VND de bao dong cum ca map gom tang hinh

class ForeignOrderDetector:
    """
    Module phat hien dong tien khoi ngoai tu Delta Snapshot
    va thuat toan gom cum lenh tang hinh (Iceberg / TWAP Clustering).
    """

    def __init__(self):
        # Snapshot truoc do: {symbol: {"buy_qtty": float, "sell_qtty": float, "time": float}}
        self._last_snaps: Dict[str, Dict[str, float]] = {}

        # Cum gom dang active: key la f"{symbol}_{side}" -> dict chua thong tin cum
        self._active_clusters: Dict[str, Dict[str, Any]] = {}

        # Danh sach cac cum da hoan tat / du nguong
        self.completed_clusters: List[Dict[str, Any]] = []

    def validate_snap_item(self, item: Dict[str, Any]) -> bool:
        """Kiem tra tinh hop le cua snapshot va loai bo giao dich thoa thuan"""
        if not isinstance(item, dict):
            return False

        # Loai bo giao dich thoa thuan (put-through)
        board = str(item.get("board") or item.get("boardCode") or "").upper()
        if "PT" in board or "THOA_THUAN" in board:
            return False

        sym = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
        if not sym or len(sym) > 5 or not sym.isalpha():
            return False

        raw_price = float(item.get("matchPrice") or item.get("price") or item.get("closePrice") or item.get("refPrice") or 0.0)
        if raw_price <= 0:
            return False

        return True

    def process_ticker_snap(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Xu ly mot record snapshot co phieu de phat hien delta khoi ngoai
        va cap nhat vao cum gom lenh (Iceberg Cluster).
        """
        if not self.validate_snap_item(item):
            return []

        sym = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
        raw_price = float(item.get("matchPrice") or item.get("price") or item.get("closePrice") or item.get("refPrice") or 0.0)
        price = round(raw_price * 1000) if (0 < raw_price < 1000) else round(raw_price)

        f_buy_qtty = float(item.get("buyForeignQtty") or 0.0)
        f_sell_qtty = float(item.get("sellForeignQtty") or 0.0)

        now = time.time()
        time_str = time.strftime("%H:%M:%S")

        detected_orders: List[Dict[str, Any]] = []

        if sym not in self._last_snaps:
            # Khoi tao moc dau tien
            self._last_snaps[sym] = {
                "buy_qtty": f_buy_qtty,
                "sell_qtty": f_sell_qtty,
                "time": now
            }
            return []

        prev = self._last_snaps[sym]
        delta_buy = f_buy_qtty - prev["buy_qtty"]
        delta_sell = f_sell_qtty - prev["sell_qtty"]

        # Cap nhat snapshot hien tai
        self._last_snaps[sym] = {
            "buy_qtty": f_buy_qtty,
            "sell_qtty": f_sell_qtty,
            "time": now
        }

        # 1. Phat hien lenh Ngoai Mua
        if delta_buy > 0:
            val_vnd = delta_buy * price
            order_info = {
                "time": time_str,
                "symbol": sym,
                "price": price,
                "qty": int(delta_buy),
                "value": val_vnd,
                "value_ty": round(val_vnd / 1e9, 3),
                "side": "BUY",
                "sector": get_sector_by_symbol(sym),
                "is_foreign": True
            }
            cluster = self._add_to_cluster(order_info, now)
            if cluster:
                detected_orders.append(cluster)

        # 2. Phat hien lenh Ngoai Ban
        if delta_sell > 0:
            val_vnd = delta_sell * price
            order_info = {
                "time": time_str,
                "symbol": sym,
                "price": price,
                "qty": int(delta_sell),
                "value": val_vnd,
                "value_ty": round(val_vnd / 1e9, 3),
                "side": "SELL",
                "sector": get_sector_by_symbol(sym),
                "is_foreign": True
            }
            cluster = self._add_to_cluster(order_info, now)
            if cluster:
                detected_orders.append(cluster)

        return detected_orders

    def _add_to_cluster(self, order: Dict[str, Any], current_time: float) -> Optional[Dict[str, Any]]:
        """
        Gom cac lenh nho lien tiep cua cung mot ma va cung chieu Mua/Ban
        trong cua so thoi gian 120 giay thanh 1 cum lenh tang hinh.
        """
        key = f"{order['symbol']}_{order['side']}"
        cluster = self._active_clusters.get(key)

        if not cluster or (current_time - cluster["last_order_time"]) > CLUSTER_WINDOW_SECONDS:
            # Tao cum gom moi
            cluster = {
                "cluster_id": f"CLUST_{order['symbol']}_{int(current_time)}",
                "symbol": order["symbol"],
                "side": order["side"],
                "sector": order["sector"],
                "start_time": order["time"],
                "last_order_time": current_time,
                "order_count": 1,
                "total_qty": order["qty"],
                "total_val": order["value"],
                "weighted_price_sum": order["price"] * order["qty"],
                "is_foreign_cluster": True,
                "is_foreign": True
            }
            self._active_clusters[key] = cluster
        else:
            # Nạp tiep vao cum hien tai
            cluster["order_count"] += 1
            cluster["total_qty"] += order["qty"]
            cluster["total_val"] += order["value"]
            cluster["weighted_price_sum"] += order["price"] * order["qty"]
            cluster["last_order_time"] = current_time

        # Tinh toan gia trung binh va gia tri ty
        avg_price = round(cluster["weighted_price_sum"] / cluster["total_qty"]) if cluster["total_qty"] > 0 else order["price"]
        val_ty = round(cluster["total_val"] / 1e9, 2)

        # Neu tong gia tri cum dat nguong >= 300 trieu VND, tra ve de hien thi
        if cluster["total_val"] >= CLUSTER_MIN_VALUE_VND:
            formatted_cluster = {
                "time": order["time"],
                "symbol": cluster["symbol"],
                "price": avg_price,
                "qty": cluster["total_qty"],
                "value": cluster["total_val"],
                "value_ty": val_ty,
                "side": cluster["side"],
                "sector": cluster["sector"],
                "is_foreign_cluster": True,
                "is_foreign": True,
                "order_count": cluster["order_count"],
                "cluster_note": f"Khoi ngoai gom tang hinh: {cluster['order_count']} lenh nho = {val_ty:.1f} Ty"
            }
            return formatted_cluster

        return None

foreign_order_detector = ForeignOrderDetector()

async def run_foreign_detector_loop():
    """Vong lap chay ngam quet Ticker Snaps dinh ky de phat hien Delta Khoi ngoai"""
    import asyncio
    from src.tcbs.market import market_client
    from src.data_pipeline.big_order_tracker import big_order_tracker

    logger.info("Khoi dong Foreign Order Detector background loop...")
    while True:
        try:
            for idx in [1, 3]:
                snaps = await market_client.get_ticker_snaps(index=idx)
                if snaps and isinstance(snaps, list):
                    for item in snaps:
                        clusters = foreign_order_detector.process_ticker_snap(item)
                        for clust in clusters:
                            big_order_tracker.add_foreign_cluster(clust)
        except Exception as e:
            logger.debug("Loi quet foreign detector snap: %s", str(e))
        await asyncio.sleep(4.0)

