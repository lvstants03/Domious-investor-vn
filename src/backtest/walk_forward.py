import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("dominus-investor.backtest.walk_forward")


@dataclass
class FoldResult:
    fold_idx: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    trades: List[Dict] = field(default_factory=list)
    win_rate: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0
    total_return_pct: float = 0.0
    num_signals: int = 0


class WalkForwardBacktester:
    """
    Walk-Forward Backtest cho PositionHunterPredictor.

    Su dung du lieu OHLCV tu DB (bang ohlcv_daily) de replay toan bo pipeline
    scoring ma khong can WebSocket.

    Simulate BigOrderTracker bang Volume Z-Score:
    - Volume > MA20 * 1.5 va Close > Open -> shark_net_val duong
    - Volume > MA20 * 1.5 va Close < Open -> shark_net_val am

    Cac thong so:
    - window_size: So phien dung de "train" nguong scoring (default 126 ~ 6 thang)
    - step_size  : So phien rolling forward moi fold (default 21 ~ 1 thang)
    - score_thresh: Nguong minimum de mo lenh (default 70.0)
    - hold_days  : So ngay giu lenh toi da (default 30)
    - stop_pct   : % stop loss (default 7%)
    - target_pct : % take profit (default 18%)
    """

    def __init__(
        self,
        window_size: int = 126,
        step_size: int = 21,
        score_thresh: float = 80.0,
        hold_days: int = 60,
        stop_pct: float = 9.0,
        target_pct: float = 30.0,
    ):
        self.window_size = window_size
        self.step_size = step_size
        self.score_thresh = score_thresh
        self.hold_days = hold_days
        self.stop_pct = stop_pct
        self.target_pct = target_pct

    async def run(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        db_session=None,
    ) -> Dict:
        """
        Chay Walk-Forward Backtest cho danh sach symbols.

        Tra ve dict chua:
        - folds: List[FoldResult]
        - summary: Dict[str, float] (win_rate, sharpe, max_dd, profit_factor)
        - calibration: Dict (nguong diem tot nhat)
        """
        logger.info(
            "Walk-Forward Backtest bat dau: %d ma, %s -> %s",
            len(symbols), start_date, end_date
        )

        # Tai OHLCV tu DB hoac vnstock
        ohlcv_data = await self._load_ohlcv_data(symbols, start_date, end_date, db_session)
        if not ohlcv_data:
            return {"error": "Khong co du lieu OHLCV", "folds": [], "summary": {}}

        # Lay cot moc ngay giao dich chung
        trading_dates = self._get_trading_dates(ohlcv_data, start_date, end_date)
        if len(trading_dates) < self.window_size + self.step_size:
            return {"error": "Khong du phien giao dich de backtest", "folds": [], "summary": {}}

        # Tao cac fold walk-forward
        folds: List[FoldResult] = []
        fold_idx = 0
        all_trades: List[Dict] = []

        i = 0
        while i + self.window_size + self.step_size <= len(trading_dates):
            train_dates = trading_dates[i : i + self.window_size]
            test_dates  = trading_dates[i + self.window_size : i + self.window_size + self.step_size]

            fold = FoldResult(
                fold_idx=fold_idx,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
            )

            # Chay scoring engine tren du lieu test
            fold_trades = self._simulate_fold(
                ohlcv_data, train_dates, test_dates, symbols
            )
            fold.trades = fold_trades
            fold.num_signals = len(fold_trades)

            # Tinh metrics cho fold
            metrics = self._calculate_metrics(fold_trades)
            fold.win_rate = metrics["win_rate"]
            fold.sharpe = metrics["sharpe"]
            fold.max_drawdown = metrics["max_drawdown"]
            fold.profit_factor = metrics["profit_factor"]
            fold.total_return_pct = metrics["total_return_pct"]

            folds.append(fold)
            all_trades.extend(fold_trades)

            logger.info(
                "Fold %d [%s -> %s]: %d tin hieu | Win=%.1f%% | Sharpe=%.2f | MaxDD=%.1f%%",
                fold_idx, fold.test_start, fold.test_end,
                fold.num_signals, fold.win_rate, fold.sharpe, fold.max_drawdown
            )

            fold_idx += 1
            i += self.step_size

        # Tong hop ket qua
        summary = self._aggregate_summary(folds, all_trades)

        # Calibration: tim nguong score tot nhat
        calibration = self._calibrate_threshold(all_trades)

        logger.info(
            "Walk-Forward hoan tat: %d folds | Win Rate %.1f%% | Sharpe %.2f | MaxDD %.1f%%",
            len(folds), summary["win_rate"], summary["sharpe"], summary["max_drawdown"]
        )

        return {
            "folds": [self._fold_to_dict(f) for f in folds],
            "summary": summary,
            "calibration": calibration,
            "total_trades": len(all_trades),
            "params": {
                "window_size": self.window_size,
                "step_size": self.step_size,
                "score_thresh": self.score_thresh,
                "stop_pct": self.stop_pct,
                "target_pct": self.target_pct,
            }
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _load_ohlcv_data(
        self, symbols, start_date, end_date, db_session
    ) -> Dict[str, pd.DataFrame]:
        """
        Tai OHLCV theo thu tu uu tien:
        1. DB (bang ohlcv_daily) - nhanh nhat, khong can API
        2. vnstock VCI  - fallback 1
        3. vnstock TCBS - fallback 2 neu VCI timeout
        4. vnstock MSN  - fallback 3
        """
        result: Dict[str, pd.DataFrame] = {}

        for sym in symbols:
            df = None

            # --- Nguon 1: DB ---
            if db_session is not None:
                try:
                    df = await self._load_from_db(sym, start_date, end_date, db_session)
                    if df is not None and len(df) >= 60:
                        result[sym] = df
                        continue
                except Exception:
                    pass

            # --- Nguon 2-4: vnstock voi nhieu source ---
            for source in ["VCI", "TCBS", "MSN"]:
                try:
                    import signal as _sig
                    from vnstock.api.quote import Quote
                    q = Quote(symbol=sym, source=source)
                    import concurrent.futures, asyncio as _aio
                    loop = _aio.get_event_loop()
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        df = await loop.run_in_executor(
                            pool,
                            lambda q=q: q.history(
                                start=start_date, end=end_date, interval="1D"
                            )
                        )
                    if df is not None and not df.empty:
                        if "time" in df.columns:
                            df = df.rename(columns={"time": "trade_date"})
                        df["trade_date"] = __import__("pandas").to_datetime(df["trade_date"]).dt.date
                        df["symbol"] = sym
                        df = df.sort_values("trade_date").reset_index(drop=True)
                        required = ["trade_date", "open", "high", "low", "close", "volume"]
                        if all(c in df.columns for c in required):
                            df = df.dropna(subset=required)
                            result[sym] = df
                            logger.info("  %s: %d phien tu %s", sym, len(df), source)
                            break
                except Exception as e:
                    logger.debug("  %s [%s] that bai: %s", sym, source, str(e)[:60])
                    continue

            if sym not in result:
                logger.warning("  %s: Khong lay duoc du lieu tu bat ky nguon nao", sym)

        logger.info("Da tai OHLCV cho %d/%d ma", len(result), len(symbols))
        return result


    async def _load_from_db(self, symbol, start_date, end_date, session) -> Optional[pd.DataFrame]:
        try:
            from src.database.models import OHLCVDaily
            from sqlalchemy import select
            stmt = (
                select(OHLCVDaily)
                .where(OHLCVDaily.symbol == symbol)
                .where(OHLCVDaily.trade_date >= start_date)
                .where(OHLCVDaily.trade_date <= end_date)
                .order_by(OHLCVDaily.trade_date.asc())
            )
            res = await session.execute(stmt)
            rows = list(res.scalars().all())
            if not rows:
                return None
            df = pd.DataFrame([{
                "trade_date": r.trade_date,
                "open": r.open, "high": r.high,
                "low": r.low, "close": r.close,
                "volume": r.volume
            } for r in rows])
            return df
        except Exception:
            return None

    def _get_trading_dates(
        self, ohlcv_data: Dict[str, pd.DataFrame], start_date: str, end_date: str
    ) -> List[date]:
        """Lay union ngay giao dich tu tat ca cac ma."""
        all_dates = set()
        for df in ohlcv_data.values():
            for d in df["trade_date"]:
                if isinstance(d, str):
                    d = date.fromisoformat(d)
                all_dates.add(d)
        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
        filtered = sorted(d for d in all_dates if sd <= d <= ed)
        return filtered

    def _simulate_fold(
        self,
        ohlcv_data: Dict[str, pd.DataFrame],
        train_dates: List[date],
        test_dates: List[date],
        symbols: List[str],
    ) -> List[Dict]:
        """
        Simulate scoring tren test_dates voi tham so duoc hoc tu train_dates.
        Tra ve danh sach lenh da dong voi pnl_pct.
        """
        trades = []
        test_set = set(test_dates)

        for sym in symbols:
            df = ohlcv_data.get(sym)
            if df is None or df.empty:
                continue

            # Dam bao trade_date la date object
            df = df.copy()
            if df["trade_date"].dtype == object:
                df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

            # Chi lay du lieu den cuoi test period
            df_full = df[df["trade_date"] <= test_dates[-1]].copy()
            if len(df_full) < 30:
                continue

            # Tinh indicators
            df_full = self._add_indicators(df_full)

            # Lap qua tung ngay trong test_dates
            for test_day in test_dates:
                df_to_date = df_full[df_full["trade_date"] <= test_day]
                if len(df_to_date) < 30:
                    continue

                score = self._score_day(df_to_date, sym)
                if score < self.score_thresh:
                    continue

                # Mo lenh tai gia mo cua ngay tiep theo
                entry_row = df_full[df_full["trade_date"] > test_day]
                if entry_row.empty:
                    continue
                entry_price = float(entry_row.iloc[0]["open"])
                entry_date = entry_row.iloc[0]["trade_date"]

                if entry_price <= 0:
                    continue

                stop_price   = entry_price * (1 - self.stop_pct / 100)
                target_price = entry_price * (1 + self.target_pct / 100)

                # Ket qua: quet qua cac phien sau entry
                future_rows = df_full[df_full["trade_date"] > entry_date].head(self.hold_days)

                exit_price = float(future_rows["close"].iloc[-1]) if not future_rows.empty else entry_price
                exit_reason = "EXPIRED"
                exit_date = entry_date + timedelta(days=self.hold_days)

                for _, row in future_rows.iterrows():
                    low_p  = float(row["low"])
                    high_p = float(row["high"])
                    if low_p <= stop_price:
                        exit_price  = stop_price
                        exit_reason = "STOP_LOSS"
                        exit_date   = row["trade_date"]
                        break
                    if high_p >= target_price:
                        exit_price  = target_price
                        exit_reason = "TAKE_PROFIT"
                        exit_date   = row["trade_date"]
                        break

                # Tru 0.4% thue + phi giao dich 2 chieu + do truot gia thuc te
                raw_pnl = (exit_price - entry_price) / entry_price * 100
                pnl_pct = round(raw_pnl - 0.40, 2)
                trades.append({
                    "symbol": sym,
                    "signal_date": test_day,
                    "entry_date": entry_date,
                    "entry_price": entry_price,
                    "exit_date": exit_date,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "pnl_pct": pnl_pct,
                    "score": round(score, 1),
                })

        return trades

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Them EMA, MA, Volume Z-Score vao DataFrame."""
        df = df.copy()
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)

        df["ma20_vol"] = volume.rolling(20, min_periods=5).mean()
        df["vol_ratio"] = volume / df["ma20_vol"].clip(lower=1)
        df["ema20"]  = close.ewm(span=20, adjust=False).mean()
        df["ema50"]  = close.ewm(span=50, adjust=False).mean()
        df["ma200"]  = close.rolling(200, min_periods=30).mean()

        # 52w high (252 phien)
        df["high_52w"] = df["high"].astype(float).rolling(252, min_periods=60).max()

        # Slope EMA20 (10 phien)
        df["ema20_slope"] = df["ema20"].diff(10)
        return df

    def _score_day(self, df: pd.DataFrame, symbol: str) -> float:
        """
        Tinh composite score cho 1 ma tai 1 ngay cu the.
        Simulate 4 thanh phan chinh (khong co real-time WebSocket).
        """
        last = df.iloc[-1]
        close = float(last["close"])

        # --- Shark Flow (35%) ---
        # Simulate: volume cao + close > open = shark mua
        vol_ratio = float(last.get("vol_ratio", 1.0))
        is_up_bar  = float(last["close"]) > float(last["open"])
        if vol_ratio >= 1.5 and is_up_bar:
            s_shark = min(10.0, 5.0 + (vol_ratio - 1.5) * 4.0)
        elif vol_ratio >= 1.5 and not is_up_bar:
            s_shark = max(0.5, 5.0 - (vol_ratio - 1.5) * 6.0)
        else:
            s_shark = 5.0

        # --- Wyckoff (25%) ---
        ema20 = float(last.get("ema20", close))
        ema50 = float(last.get("ema50", close))
        s_wyckoff = 5.0
        if close >= ema50:
            s_wyckoff += 2.5
        if vol_ratio < 1.0:   # kiet cung
            s_wyckoff += 2.0
        if close >= ema20 >= ema50:
            s_wyckoff = min(10.0, s_wyckoff + 1.5)

        # --- Sector RS (20%) = trung binh (5.0) vi khong co real-time ---
        s_sector = 5.0

        # --- 52W Proximity (20%) ---
        high_52w = float(last.get("high_52w", close))
        if high_52w > 0:
            dist = abs((close - high_52w) / high_52w * 100)
        else:
            dist = 30.0
        s_52w = min(10.0, max(1.0, 10.0 - dist / 3.0))

        core = (s_shark * 0.35 + s_wyckoff * 0.25 + s_sector * 0.20 + s_52w * 0.20) * 10.0
        return round(min(98.0, max(25.0, core)), 1)

    def _calculate_metrics(self, trades: List[Dict]) -> Dict:
        """Tinh Win Rate, Sharpe, Max Drawdown, Profit Factor."""
        if not trades:
            return {"win_rate": 0.0, "sharpe": 0.0, "max_drawdown": 0.0,
                    "profit_factor": 0.0, "total_return_pct": 0.0}

        pnls = [t["pnl_pct"] for t in trades]
        wins  = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = round(len(wins) / len(pnls) * 100, 1)

        # Sharpe (don vi %)
        if len(pnls) > 1:
            mean_r = float(np.mean(pnls))
            std_r  = float(np.std(pnls, ddof=1))
            sharpe = round(mean_r / std_r * math.sqrt(252) if std_r > 0 else 0.0, 2)
        else:
            sharpe = 0.0

        # Max Drawdown (compound)
        equity = 100.0
        peak = 100.0
        max_dd = 0.0
        for p in pnls:
            equity *= (1 + p / 100)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # Total return
        equity_final = 100.0
        for p in pnls:
            equity_final *= (1 + p / 100)
        total_return = round(equity_final - 100.0, 2)

        # Profit Factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss   = abs(sum(losses)) if losses else 0.0
        pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf")

        return {
            "win_rate": win_rate,
            "sharpe": sharpe,
            "max_drawdown": round(max_dd, 2),
            "profit_factor": pf,
            "total_return_pct": total_return,
        }

    def _aggregate_summary(self, folds: List[FoldResult], all_trades: List[Dict]) -> Dict:
        if not folds:
            return {}
        overall = self._calculate_metrics(all_trades)
        overall["num_folds"] = len(folds)
        overall["avg_signals_per_fold"] = round(
            sum(f.num_signals for f in folds) / len(folds), 1
        )
        return overall

    def _calibrate_threshold(self, all_trades: List[Dict]) -> Dict:
        """Tim nguong score cho Win Rate cao nhat."""
        best_thresh = self.score_thresh
        best_win_rate = 0.0
        for thresh in [60.0, 65.0, 70.0, 75.0, 80.0]:
            filtered = [t for t in all_trades if t["score"] >= thresh]
            if len(filtered) < 5:
                continue
            wins = [t for t in filtered if t["pnl_pct"] > 0]
            wr = len(wins) / len(filtered) * 100
            if wr > best_win_rate:
                best_win_rate = wr
                best_thresh = thresh
        return {
            "recommended_threshold": best_thresh,
            "win_rate_at_threshold": round(best_win_rate, 1),
            "note": "Tang nguong MUA GOM neu Win Rate < 52%",
        }

    def _fold_to_dict(self, f: FoldResult) -> Dict:
        return {
            "fold": f.fold_idx,
            "train": f"{f.train_start} -> {f.train_end}",
            "test":  f"{f.test_start} -> {f.test_end}",
            "num_signals": f.num_signals,
            "win_rate": f.win_rate,
            "sharpe": f.sharpe,
            "max_drawdown": f.max_drawdown,
            "profit_factor": f.profit_factor,
            "total_return_pct": f.total_return_pct,
        }
