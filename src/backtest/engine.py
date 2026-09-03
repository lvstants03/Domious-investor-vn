import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
import pandas as pd
import numpy as np

logger = logging.getLogger("dominus-investor.backtest.engine")

# Phi giao dich thuc te
BUY_FEE_PCT = 0.0015     # 0.15%
SELL_FEE_PCT = 0.0015    # 0.15%
SELL_TAX_PCT = 0.001     # 0.1% thue ban

# Truot gia (Slippage) theo nhom von hoa
SLIPPAGE_LARGE_CAP = 0.001   # 0.1% cho von hoa lon
SLIPPAGE_MID_CAP = 0.003     # 0.3% cho midcap


@dataclass
class TradeRecord:
    symbol: str
    entry_date: str
    exit_date: Optional[str]
    entry_price: float
    exit_price: Optional[float]
    quantity: int
    pnl: Optional[float]
    pnl_pct: Optional[float]
    exit_reason: Optional[str]  # STOP_LOSS, TAKE_PROFIT_1, TAKE_PROFIT_2, TRAILING_MA20, VOLUME_CLIMAX_EXIT, EOD


@dataclass
class BacktestResult:
    symbol: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    winning_trades: int
    sharpe_ratio: float
    sqn: float                  # System Quality Number
    calmar_ratio: float
    trade_records: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


class BacktestEngine:
    """
    Vectorized Backtest Engine nang cap cho chien luoc Position Hunter T+30.
    
    Quy tac mo phong nang cap toan dien:
    - Tin hieu xuat hien ngay T -> Mua tai Open ngay T+1
    - Stop-loss dong theo ATR (1.8x ATR14) tranh ru bo
    - Chot loi 2 tang (Partial TP 50% tai TP1 +18%, 50% con lai theo Trailing MA20 / TP2 +35%)
    - Trailing Stop MA20 khi loi nhuan vuot +10%
    - Volume Climax Exit: Chot loi toan bo khi gap phien Vol > 3.2x kem nen do
    - Slippage ap dung khi tinh gia mua/ban thuc te
    - Phi giao dich va thue duoc tru ra khi dong vi the
    """

    def __init__(self, large_cap_symbols: Optional[List[str]] = None):
        self.large_cap = set(large_cap_symbols or [
            "VHM", "VIC", "VNM", "VCB", "BID", "CTG", "GAS", "SAB",
            "HPG", "FPT", "MBB", "TCB", "VPB", "ACB", "STB"
        ])

    def _get_slippage(self, symbol: str) -> float:
        return SLIPPAGE_LARGE_CAP if symbol in self.large_cap else SLIPPAGE_MID_CAP

    def _calc_sharpe(self, equity_curve: List[float], risk_free_rate: float = 0.05) -> float:
        """Tinh Sharpe Ratio hang nam tu equity curve."""
        if len(equity_curve) < 2:
            return 0.0
        returns = pd.Series(equity_curve).pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        annual_return = returns.mean() * 252
        annual_vol = returns.std() * (252 ** 0.5)
        return round((annual_return - risk_free_rate) / annual_vol, 3)

    def _calc_sqn(self, trade_pnl_pcts: List[float]) -> float:
        """
        System Quality Number (SQN) = (Mean_R / Std_R) * sqrt(N).
        """
        if len(trade_pnl_pcts) < 3:
            return 0.0
        arr = np.array(trade_pnl_pcts)
        mean_r = arr.mean()
        std_r = arr.std()
        if std_r == 0:
            return 0.0
        return round((mean_r / std_r) * (len(arr) ** 0.5), 3)

    def _calc_max_drawdown(self, equity_curve: List[float]) -> float:
        """Tinh Max Drawdown (%)."""
        if len(equity_curve) < 2:
            return 0.0
        eq = pd.Series(equity_curve)
        peak = eq.cummax()
        drawdown = (eq - peak) / peak
        return round(float(drawdown.min()) * 100, 2)

    def run(
        self,
        symbol: str,
        ohlcv_df: pd.DataFrame,
        strategy_fn: Callable,
        params: dict,
        initial_capital: float = 100_000_000,
        position_size_pct: float = 0.25,
        stop_loss_pct: float = 0.06,
        take_profit_pct: float = 0.35
    ) -> BacktestResult:
        """
        Chay backtest cho 1 ma co phieu voi ho tro ATR Stop Loss, 2-Stage TP & Volume Climax Exit.
        """
        if ohlcv_df is None or len(ohlcv_df) < 30:
            return BacktestResult(
                symbol=symbol, initial_capital=initial_capital, final_capital=initial_capital,
                total_return_pct=0.0, max_drawdown_pct=0.0, win_rate=0.0,
                total_trades=0, winning_trades=0, sharpe_ratio=0.0, sqn=0.0, calmar_ratio=0.0
            )

        df = ohlcv_df.sort_values("trade_date").reset_index(drop=True)
        slippage = self._get_slippage(symbol)

        # Tinh toan ATR(14), MA20 va SMA20 Volume
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        vols = df["volume"].values
        
        tr_list = [highs[0] - lows[0]]
        for j in range(1, len(df)):
            tr = max(highs[j] - lows[j], abs(highs[j] - closes[j - 1]), abs(lows[j] - closes[j - 1]))
            tr_list.append(tr)
        
        atr14 = pd.Series(tr_list).rolling(14, min_periods=5).mean().values
        ma20 = pd.Series(closes).rolling(20, min_periods=10).mean().values
        sma20_vol = pd.Series(vols).rolling(20, min_periods=10).mean().values

        # Sinh tin hieu
        try:
            signals = strategy_fn(df, params)
        except Exception as e:
            logger.error("Loi khi sinh tin hieu cho %s: %s", symbol, str(e))
            signals = pd.Series([False] * len(df))

        capital = initial_capital
        equity_curve = [capital]
        trades: List[TradeRecord] = []

        position = None  # Dict luu vi the

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_signal = signals.iloc[i - 1] if i - 1 < len(signals) else False
            close = float(row["close"])
            open_price = float(row["open"])
            curr_vol = float(row["volume"])
            trade_date = str(row["trade_date"])
            curr_ma20 = ma20[i] if not np.isnan(ma20[i]) else close
            curr_atr = atr14[i] if not np.isnan(atr14[i]) else (close * 0.03)
            curr_avg_vol = sma20_vol[i] if not np.isnan(sma20_vol[i]) else 1.0

            # Xu ly vi the dang mo
            if position is not None:
                unrealized_gain = (close - position["entry_price"]) / position["entry_price"]

                # 1. Volume Climax Exit: Chot loi toan bo khi gap phien phan phoi cao trao
                is_vol_climax = (curr_vol >= 3.2 * curr_avg_vol) and (close < open_price) and (unrealized_gain >= 0.08)
                if is_vol_climax:
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += (proceeds - fee)
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="VOLUME_CLIMAX_EXIT"
                    ))
                    position = None

                # 2. Trailing Stop MA20 neu vi the da lai >= +10%
                elif unrealized_gain >= 0.10 and curr_ma20 > position["stop_loss"]:
                    position["stop_loss"] = max(position["stop_loss"], curr_ma20 * 0.99)

                # 3. Chot loi Tang 1 (50% vi the khi dat TP1 +18%)
                if position is not None and not position["partial_tp_done"] and close >= position["tp1"]:
                    half_qty = int(position["quantity"] / 2 / 100) * 100
                    if half_qty > 0:
                        sell_price = close * (1 - slippage)
                        proceeds = sell_price * half_qty
                        fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                        pnl = proceeds - fee - (position["entry_price"] * half_qty)
                        pnl_pct = round(pnl / (position["entry_price"] * half_qty) * 100, 2)
                        capital += (proceeds - fee)
                        trades.append(TradeRecord(
                            symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                            entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                            quantity=half_qty, pnl=round(pnl, 0), pnl_pct=pnl_pct,
                            exit_reason="TAKE_PROFIT_1"
                        ))
                        position["quantity"] -= half_qty
                        position["partial_tp_done"] = True
                        position["stop_loss"] = max(position["stop_loss"], position["entry_price"])

                # 4. Kiem tra Stop-loss
                if position is not None and close <= position["stop_loss"]:
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += (proceeds - fee)
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="STOP_LOSS"
                    ))
                    position = None

                # 5. Kiem tra Chot loi Tang 2 hoac gay MA20 khi da qua TP1
                elif position is not None and position["partial_tp_done"] and (close >= position["tp2"] or close < curr_ma20 * 0.985):
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += (proceeds - fee)
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="TAKE_PROFIT_2" if close >= position["tp2"] else "TRAILING_MA20"
                    ))
                    position = None

                # 6. Kiem tra Full TP neu chua qua TP1 ma no vuot thang TP2
                elif position is not None and close >= position["tp2"]:
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += (proceeds - fee)
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="TAKE_PROFIT_FULL"
                    ))
                    position = None

            # Mo vi the moi khi co tin hieu
            if position is None and prev_signal:
                buy_price = open_price * (1 + slippage)
                position_value = capital * position_size_pct
                quantity = int(position_value / buy_price / 100) * 100
                if quantity <= 0:
                    equity_curve.append(capital)
                    continue
                fee = buy_price * quantity * BUY_FEE_PCT
                cost = buy_price * quantity + fee
                if cost > capital:
                    equity_curve.append(capital)
                    continue
                capital -= cost

                # Tinh Stop-loss dong theo 1.8x ATR (gioi han tu 4% den 8.5%)
                atr_dist = 1.8 * curr_atr
                min_sl = buy_price * 0.04
                max_sl = buy_price * 0.085
                effective_sl_dist = max(min_sl, min(max_sl, atr_dist))
                sl_price = buy_price - effective_sl_dist

                position = {
                    "entry_price": round(buy_price, 0),
                    "quantity": quantity,
                    "stop_loss": round(sl_price, 0),
                    "tp1": round(buy_price * 1.18, 0),
                    "tp2": round(buy_price * (1 + take_profit_pct), 0),
                    "partial_tp_done": False,
                    "entry_date": trade_date
                }

            equity_curve.append(capital + (close * position["quantity"] if position else 0))

        # Dong vi the cuoi phien backtest
        if position is not None:
            last_close = float(df.iloc[-1]["close"])
            sell_price = last_close * (1 - slippage)
            proceeds = sell_price * position["quantity"]
            fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
            pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
            pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
            capital += (proceeds - fee)
            trades.append(TradeRecord(
                symbol=symbol, entry_date=position["entry_date"], exit_date=str(df.iloc[-1]["trade_date"]),
                entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                exit_reason="EOD"
            ))

        # Tinh toan cac chi so danh gia
        total_return_pct = round((capital - initial_capital) / initial_capital * 100, 2)
        win_trades = [t for t in trades if (t.pnl or 0) > 0]
        win_rate = round(len(win_trades) / len(trades) * 100, 1) if trades else 0.0
        pnl_pcts = [t.pnl_pct for t in trades if t.pnl_pct is not None]
        max_dd = self._calc_max_drawdown(equity_curve)
        sharpe = self._calc_sharpe(equity_curve)
        sqn = self._calc_sqn(pnl_pcts)
        calmar = round(total_return_pct / abs(max_dd), 2) if max_dd != 0 else 0.0

        return BacktestResult(
            symbol=symbol,
            initial_capital=initial_capital,
            final_capital=round(capital, 0),
            total_return_pct=total_return_pct,
            max_drawdown_pct=max_dd,
            win_rate=win_rate,
            total_trades=len(trades),
            winning_trades=len(win_trades),
            sharpe_ratio=sharpe,
            sqn=sqn,
            calmar_ratio=calmar,
            trade_records=trades,
            equity_curve=equity_curve
        )


backtest_engine = BacktestEngine()
