from datetime import datetime, date
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Date, JSON, ForeignKey, BigInteger, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class BotConfig(Base):
    __tablename__ = "bot_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="paper")  # 'paper' or 'live'
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    position_size_pct: Mapped[float] = mapped_column(Float, default=10.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=5.0)
    take_profit_pct: Mapped[float] = mapped_column(Float, default=10.0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=15.0)
    strategy_params: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    trades: Mapped[List["Trade"]] = relationship("Trade", back_populates="bot_config", cascade="all, delete-orphan")
    positions: Mapped[List["Position"]] = relationship("Position", back_populates="bot_config", cascade="all, delete-orphan")
    signals: Mapped[List["StrategySignal"]] = relationship("StrategySignal", back_populates="bot_config", cascade="all, delete-orphan")

class Trade(Base):
    __tablename__ = "trades"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bot_configs.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # 'BUY' or 'SELL'
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    order_id_tcbs: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING, FILLED, CANCELLED, FAILED
    mode: Mapped[str] = mapped_column(String(20), default="paper")  # 'paper' or 'live'
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    bot_config: Mapped[Optional["BotConfig"]] = relationship("BotConfig", back_populates="trades")

class Position(Base):
    __tablename__ = "positions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bot_configs.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(20), default="paper")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    bot_config: Mapped[Optional["BotConfig"]] = relationship("BotConfig", back_populates="positions")

class StrategySignal(Base):
    __tablename__ = "strategy_signals"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_config_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bot_configs.id"), nullable=True)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    signal: Mapped[str] = mapped_column(String(10), nullable=False)  # 'BUY', 'SELL', 'HOLD'
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    indicator_values: Mapped[dict] = mapped_column(JSON, default=dict)
    price_at_signal: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    bot_config: Mapped[Optional["BotConfig"]] = relationship("BotConfig", back_populates="signals")

class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    strategy_params: Mapped[dict] = mapped_column(JSON, default=dict)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False)
    final_capital: Mapped[float] = mapped_column(Float, nullable=False)
    total_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    sharpe_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    sortino_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    calmar_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")  # RUNNING, DONE, FAILED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False)
    signal_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    indicator_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    entry_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exit_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    supply_demand: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    interval: Mapped[str] = mapped_column(String(10), default="1d")  # '1m', '5m', '15m', '1d'

class MarketSnapshotDeriv(Base):
    __tablename__ = "market_snapshots_deriv"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    open_interest: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    basis: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    interval: Mapped[str] = mapped_column(String(10), default="1d")

class MarginSnapshot(Base):
    __tablename__ = "margin_snapshots"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    margin_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    call_margin_value: Mapped[float] = mapped_column(Float, default=0.0)
    loan_balance: Mapped[float] = mapped_column(Float, default=0.0)
    collateral_value: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="NORMAL")  # NORMAL, WARNING, CALL, FORCE_SELL

class ScanUniverse(Base):
    __tablename__ = "scan_universes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), default="HOSE")
    market_cap: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_daily_volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    blacklist_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScanResult(Base):
    __tablename__ = "scan_results"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    scan_type: Mapped[str] = mapped_column(String(20), default="intraday")  # pre_market, intraday, eod
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    composite_score: Mapped[float] = mapped_column(Float, nullable=False)
    technical_score: Mapped[float] = mapped_column(Float, default=0.0)
    volume_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    price_at_scan: Mapped[float] = mapped_column(Float, nullable=False)
    volume_at_scan: Mapped[int] = mapped_column(Integer, nullable=False)
    foreign_net_buy: Mapped[float] = mapped_column(Float, default=0.0)
    rank_in_scan: Mapped[int] = mapped_column(Integer, nullable=False)
    action_taken: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # paper, live, ignored
    order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


class OHLCVDaily(Base):
    __tablename__ = "ohlcv_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("symbol", "trade_date", name="uq_ohlcv_symbol_date"),)


class MarketRegime(Base):
    __tablename__ = "market_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    regime_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    vnindex_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)  # BULL, BEAR, SIDEWAYS
    ema20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend_slope: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WyckoffSignal(Base):
    __tablename__ = "wyckoff_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SPRING, RETEST
    base_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    base_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    support_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resistance_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_aggressive: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_standard: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    entry_optimal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rr_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    win_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    z_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_regime: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    composite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE, HIT_TARGET, HIT_STOPLOSS, EXPIRED
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wyckoff_signals.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN, CLOSED_WIN, CLOSED_LOSS, CLOSED_EXPIRED
    pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Trailing Stop (quan ly boi TrailingStopManager backend)
    highest_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trailing_stop_pct: Mapped[float] = mapped_column(Float, default=10.0)
    trailing_stop_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WhaleOrderLog(Base):
    """Bảng lưu vết các lệnh Cá Mập / Lệnh Khủng (>= 200 triệu VNĐ) trên toàn sàn"""
    __tablename__ = "whale_order_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    time_str: Mapped[str] = mapped_column(String(10), nullable=False)  # HH:MM:SS
    side: Mapped[str] = mapped_column(String(5), nullable=False)        # BUY, SELL
    price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)
    value_vnd: Mapped[float] = mapped_column(Float, nullable=False)     # >= 200,000,000
    tier: Mapped[str] = mapped_column(String(20), default="SHARK")      # SHARK, MEGA
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SmartMoneyForecastDaily(Base):
    """Bảng lưu tổng hợp dòng tiền Shark/Wolf và kết quả dự báo T+5, T+10 theo từng phiên"""
    __tablename__ = "smart_money_forecast_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    shark_net_val: Mapped[float] = mapped_column(Float, default=0.0)
    wolf_net_val: Mapped[float] = mapped_column(Float, default=0.0)
    wyckoff_phase: Mapped[str] = mapped_column(String(50), nullable=False)  # Phase A, B, C, D
    intent_5d: Mapped[str] = mapped_column(String(50), nullable=False)      # GOM HANG, PHAN PHOI
    forecast_10d_target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    confidence_pct: Mapped[float] = mapped_column(Float, default=75.0)
    risk_level: Mapped[str] = mapped_column(String(20), default="TRUNG BINH")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("trade_date", "symbol", name="uq_smart_money_date_symbol"),)


class SectorFlowSnapshot(Base):
    """Bảng đo lường xung lực và dòng tiền luân chuyển giữa các nhóm ngành trên thị trường"""
    __tablename__ = "sector_flow_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    total_buy_val: Mapped[float] = mapped_column(Float, default=0.0)
    total_sell_val: Mapped[float] = mapped_column(Float, default=0.0)
    net_val: Mapped[float] = mapped_column(Float, default=0.0)
    flow_intensity_pct: Mapped[float] = mapped_column(Float, default=0.0)
    lead_symbols: Mapped[dict] = mapped_column(JSON, default=list)  # Top ma dan song trong nganh
    rotation_stage: Mapped[str] = mapped_column(String(30), default="ACCUMULATION") # ACCUMULATION, MARKUP, DISTRIBUTION, REACCUMULATION
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("trade_date", "sector_name", name="uq_sector_flow_date_name"),)


class StockFundamentalSnapshot(Base):
    """Bảng lưu trữ chỉ số cơ bản, định giá và ngành nghề của toàn bộ cổ phiếu trên 3 sàn từ TCBS"""
    __tablename__ = "stock_fundamental_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), default="HOSE")  # HOSE, HNX, UPCOM
    sector_name: Mapped[str] = mapped_column(String(100), default="Khác")
    market_cap: Mapped[float] = mapped_column(Float, default=0.0)  # Vốn hóa (VND)
    pe: Mapped[float] = mapped_column(Float, default=0.0)
    pb: Mapped[float] = mapped_column(Float, default=0.0)
    roe: Mapped[float] = mapped_column(Float, default=0.0)
    eps: Mapped[float] = mapped_column(Float, default=0.0)
    foreign_room_left: Mapped[float] = mapped_column(Float, default=0.0)
    last_price: Mapped[float] = mapped_column(Float, default=0.0)
    avg_volume_10d: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PositionHunterForecastLog(Base):
    """Bảng lưu trữ lịch sử các cơ hội gom hàng chân sóng 1 - 2 tháng (T+30 Position Hunter)"""
    __tablename__ = "position_hunter_forecast_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    forecast_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    sector_name: Mapped[str] = mapped_column(String(100), nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    accumulation_zone: Mapped[str] = mapped_column(String(50), nullable=False)
    target_1m: Mapped[float] = mapped_column(Float, nullable=False)
    target_2m: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    upside_pct: Mapped[str] = mapped_column(String(20), nullable=False)
    rr_ratio: Mapped[str] = mapped_column(String(20), default="1 : 3.8")
    triple_score: Mapped[int] = mapped_column(Integer, default=80)
    wyckoff_phase: Mapped[str] = mapped_column(String(50), default="Pha B (Tích Lũy)")
    shark_flow_status: Mapped[str] = mapped_column(String(50), default="Gom ròng")
    foreign_flow_status: Mapped[str] = mapped_column(String(50), default="Gom ròng")
    catalyst_summary: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("forecast_date", "symbol", name="uq_hunter_forecast_date_symbol"),)


class SignalLog(Base):
    """Bang luu tru moi tin hieu tu PositionHunter de do luong track record"""
    __tablename__ = "signals_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    regime: Mapped[str] = mapped_column(String(30), nullable=False)
    price_entry: Mapped[float] = mapped_column(Float, nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    shark_flow: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    news_boost: Mapped[float] = mapped_column(Float, default=0.0)
    action_badge: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    signaled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    track_records: Mapped[List["TrackRecord"]] = relationship("TrackRecord", back_populates="signal", cascade="all, delete-orphan")


class TrackRecord(Base):
    """Bang danh gia hieu qua sinh loi T+3 va T+5 cua tung tin hieu"""
    __tablename__ = "track_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals_log.id"), nullable=False, index=True)
    price_t3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_t5: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_t3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_t5: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_hit_t3: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_hit_t5: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped["SignalLog"] = relationship("SignalLog", back_populates="track_records")


class NewsItem(Base):
    """Bang luu tru tin tuc cao tu cac nguon RSS va danh gia boi Gemini"""
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sentiment: Mapped[int] = mapped_column(Integer, default=0)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    sectors_affected: Mapped[list] = mapped_column(JSON, default=list)
    symbols_affected: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_injected: Mapped[bool] = mapped_column(Boolean, default=False)

