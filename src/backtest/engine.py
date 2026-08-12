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
    exit_reason: Optional[str]  # STOP_LOSS, TAKE_PROFIT, EOD


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
    Vectorized Backtest Engine cho chien luoc Wyckoff Spring.
    
    Quy tac mo phong:
    - Tin hieu xuat hien ngay T -> Mua tai Open ngay T+1
    - Stop-loss va Take-profit duoc kiem tra theo Close hang ngay
    - Slippage ap dung khi tinh gia mua/ban thuc te
    - Phi giao dich va thue duoc tru ra khi dong vi the
    """

    def __init__(self, large_cap_symbols: Optional[List[str]] = None):
        # Danh sach ma von hoa lon (slippage thap hon)
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
        SQN > 2.5 = tot, > 3.0 = rat tot.
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
        position_size_pct: float = 0.10,
        stop_loss_pct: float = 0.07,
        take_profit_pct: float = 0.15
    ) -> BacktestResult:
        """
        Chay backtest cho 1 ma co phieu.

        strategy_fn(df, params) -> pd.Series[bool]: signal Series (True = BUY tren thanh do)
        """
        if ohlcv_df is None or len(ohlcv_df) < 30:
            return BacktestResult(
                symbol=symbol, initial_capital=initial_capital, final_capital=initial_capital,
                total_return_pct=0.0, max_drawdown_pct=0.0, win_rate=0.0,
                total_trades=0, winning_trades=0, sharpe_ratio=0.0, sqn=0.0, calmar_ratio=0.0
            )

        df = ohlcv_df.sort_values("trade_date").reset_index(drop=True)
        slippage = self._get_slippage(symbol)

        # Sinh tin hieu
        try:
            signals = strategy_fn(df, params)
        except Exception as e:
            logger.error("Loi khi sinh tin hieu cho %s: %s", symbol, str(e))
            signals = pd.Series([False] * len(df))

        capital = initial_capital
        equity_curve = [capital]
        trades: List[TradeRecord] = []

        position = None  # {entry_price, quantity, stop_loss, take_profit, entry_date}

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev_signal = signals.iloc[i - 1] if i - 1 < len(signals) else False
            close = float(row["close"])
            open_price = float(row["open"])
            trade_date = str(row["trade_date"])

            # Dong vi the neu co
            if position is not None:
                # Kiem tra Stop-loss (dung Close de mo phong)
                if close <= position["stop_loss"]:
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += pnl
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="STOP_LOSS"
                    ))
                    position = None

                # Kiem tra Take-profit
                elif close >= position["take_profit"]:
                    sell_price = close * (1 - slippage)
                    proceeds = sell_price * position["quantity"]
                    fee = proceeds * (SELL_FEE_PCT + SELL_TAX_PCT)
                    pnl = proceeds - fee - (position["entry_price"] * position["quantity"])
                    pnl_pct = round(pnl / (position["entry_price"] * position["quantity"]) * 100, 2)
                    capital += pnl
                    trades.append(TradeRecord(
                        symbol=symbol, entry_date=position["entry_date"], exit_date=trade_date,
                        entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                        quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                        exit_reason="TAKE_PROFIT"
                    ))
                    position = None

            # Mo vi the moi neu co tin hieu va chua co vi the
            if position is None and prev_signal:
                buy_price = open_price * (1 + slippage)
                position_value = capital * position_size_pct
                quantity = int(position_value / buy_price / 100) * 100  # Lam tron xuong 100 co
                if quantity <= 0:
                    equity_curve.append(capital)
                    continue
                fee = buy_price * quantity * BUY_FEE_PCT
                cost = buy_price * quantity + fee
                if cost > capital:
                    equity_curve.append(capital)
                    continue
                capital -= cost
                position = {
                    "entry_price": round(buy_price, 0),
                    "quantity": quantity,
                    "stop_loss": buy_price * (1 - stop_loss_pct),
                    "take_profit": buy_price * (1 + take_profit_pct),
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
            capital += pnl
            trades.append(TradeRecord(
                symbol=symbol, entry_date=position["entry_date"], exit_date=str(df.iloc[-1]["trade_date"]),
                entry_price=position["entry_price"], exit_price=round(sell_price, 0),
                quantity=position["quantity"], pnl=round(pnl, 0), pnl_pct=pnl_pct,
                exit_reason="EOD"
            ))

        # Tinh cac metrics
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
