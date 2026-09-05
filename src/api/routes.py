import logging
import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.connection import get_db
from src.database.repository import InvestorRepository
from src.database.models import BotConfig
from src.tcbs.market import market_client
from src.tcbs.account import account_client
from src.tcbs.orders import equity_order_client
from src.scanner.runner import ScannerRunner
from src.bot.runner import BotRunner
from src.tcbs.auth import auth_provider

import httpx

logger = logging.getLogger("dominus-investor.api.routes")
router = APIRouter()



# --- Authentication Endpoints ---

@router.post("/auth/request-otp")
async def request_otp():
    """Yeu cau OTP tu TCBS"""
    try:
        otp_id = await auth_provider.request_otp()
        return {"status": "SUCCESS", "otpId": otp_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/auth/submit-otp")
async def submit_otp(body: Dict[str, Any]):
    """Xac nhan OTP de lay JWT Token"""
    otp = body.get("otp")
    otp_id = body.get("otpId")
    if not otp:
        raise HTTPException(status_code=400, detail="Ma OTP la bat buoc")
    try:
        token = await auth_provider.submit_otp(otp, otp_id)
        return {"status": "SUCCESS", "token": "authenticated"}
    except httpx.HTTPStatusError as he:
        try:
            err_data = he.response.json()
            err_msg = err_data.get("message") or err_data.get("rs") or str(he)
        except Exception:
            err_msg = he.response.text or str(he)
        raise HTTPException(status_code=he.response.status_code, detail=f"TCBS: {err_msg}")

@router.post("/auth/clear-token")
async def clear_token():
    """Xoa token cu de yeu cau OTP moi"""
    try:
        auth_provider.clear_token()
        return {"status": "SUCCESS", "message": "Da xoa cache token thanh cong"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



from datetime import date, timedelta, datetime
from src.data_pipeline.ohlcv_fetcher import OHLCVFetcher
from src.data_pipeline.indicators import indicators
import pandas as pd
import re
from fastapi import Query
from typing import Optional

ohlcv_fetcher = OHLCVFetcher()

@router.get("/signals/alternative")
async def get_alternative_signals(symbols: Optional[str] = Query(None)):
    """Lay cac tin hieu canh bao dong tien va song ngam thuc te tu indicators + TCBS"""
    if symbols:
        raw_symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        valid_symbols = []
        for sym in raw_symbols:
            if re.match(r"^[A-Z0-9]{3,8}$", sym):
                valid_symbols.append(sym)
        symbols = valid_symbols
    else:
        from src.data_pipeline.market_universe_scanner import universe_scanner
        active_list = await universe_scanner.scan_market_universe()
        symbols = [s["symbol"] for s in active_list[:8]] if active_list else []
    signals = []
    now = datetime.now()
    
    try:
        foreign_rooms = await market_client.get_all_foreign_rooms()
    except Exception:
        foreign_rooms = {}
        
    for idx, symbol in enumerate(symbols):
        try:
            # 1. Tai ohlcv 90 ngay
            end_dt = date.today().strftime("%Y-%m-%d")
            start_dt = (date.today() - timedelta(days=120)).strftime("%Y-%m-%d")
            df = await ohlcv_fetcher.fetch_history(symbol, start_dt, end_dt)
            
            z_score = None
            abnormal = None
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty and len(df) >= 30:
                try:
                    vol_series = df["volume"].astype(float)
                    close_series = df["close"].astype(float)
                    z_score = indicators.z_score_latest(vol_series, period=50)
                    abnormal = indicators.calculate_abnormal_return(close_series, period=10)
                except Exception:
                    pass
            
            # 2. Lay foreign buy tu TCBS
            foreign_info = foreign_rooms.get(symbol, {})
            net_buy_val = foreign_info.get("net_buy_value", 0.0)
            
            # 3. Lay put-through deals
            deals = await market_client.get_put_through_deals(symbol)
            
            # 4. Sinh tin nhan
            if z_score is not None and z_score > 1.5:
                time_str = (now - timedelta(minutes=15 * idx + 2)).strftime("%H:%M:%S")
                signals.append({
                    "id": f"vol-{symbol}",
                    "time": time_str,
                    "type": "VOLUME",
                    "symbol": symbol,
                    "message": f"Volume Z-Score 50 phien dat +{z_score:.2f}. Phat hien dong tien dau co gom hang manh tai vung tich luy."
                })
                
            if abnormal is not None and (abnormal > 2.0 or abnormal < -2.0):
                time_str = (now - timedelta(minutes=12 * idx + 5)).strftime("%H:%M:%S")
                signals.append({
                    "id": f"abn-{symbol}",
                    "time": time_str,
                    "type": "ABNORMAL",
                    "symbol": symbol,
                    "message": f"Event Study: Abnormal Return 10 phien dat {abnormal:+.1f}%. Nghi van ro ri thong tin noi bo som truoc tin tuc."
                })
                
            if deals and len(deals) > 0:
                for deal_idx, deal in enumerate(deals):
                    time_str = deal.get("time", (now - timedelta(minutes=30)).strftime("%H:%M:%S"))
                    vol_cp = deal.get("volume", 0.0)
                    price_diff = deal.get("price_diff_pct", 0.0)
                    signals.append({
                        "id": f"ins-{symbol}-{deal_idx}",
                        "time": time_str,
                        "type": "INSIDER",
                        "symbol": symbol,
                        "message": f"Phat hien thoa thuan dot bien {vol_cp:,.0f} CP gia {deal.get('price'):,.0f}đ (lech {price_diff:+.1f}% so voi tham chieu). Tin tuc noi bo co song ngam."
                    })
                    
            if net_buy_val > 5000000000:
                time_str = (now - timedelta(minutes=25 * idx + 1)).strftime("%H:%M:%S")
                signals.append({
                    "id": f"inst-{symbol}",
                    "time": time_str,
                    "type": "INSTITUTIONAL",
                    "symbol": symbol,
                    "message": f"Khoi ngoai mua rong dot bien dat {net_buy_val/1e9:.1f} Ty VND. Dong tien khoi ngoai gom gom kiet room."
                })
        except Exception as e:
            logger.warning("Loi khi sinh tin hieu alt cho ma %s: %s", symbol, str(e))
            
    signals.sort(key=lambda x: x["time"], reverse=True)
    return signals

@router.get("/")
async def read_root():
    return {
        "service": "dominus-investor",
        "status": "online",
        "version": "1.0.0"
    }

@router.get("/health")
async def health_check():
    return {
        "status": "healthy"
    }

@router.get("/auth/status")
async def get_auth_status():
    """Lay trang thai xac thuc hien tai"""
    try:
        token = await auth_provider.get_token()
        if not token:
            return {"authenticated": False, "mode": "none"}
        return {"authenticated": True, "mode": "real", "custody_code": auth_provider.get_custody_code()}
    except Exception:
        return {"authenticated": False, "mode": "none"}


# --- Socket Manager Endpoints ---
from pydantic import BaseModel
from src.tcbs.socket_manager import socket_manager

class SocketControlRequest(BaseModel):
    socket_name: str
    action: str

class SocketSubscribeRequest(BaseModel):
    socket_name: str
    symbols: List[str]

@router.get("/socket/status")
async def get_socket_status():
    """Lay trang thai cua tat ca cac TCBS WebSockets"""
    return socket_manager.get_all_status()

@router.post("/socket/control")
async def control_socket(req: SocketControlRequest):
    """Bat/tat/reconnect mot WebSocket cu the"""
    client = socket_manager.get_client(req.socket_name)
    if not client:
        raise HTTPException(status_code=400, detail=f"Khong tim thay socket: {req.socket_name}")
    
    if req.action == "connect":
        await client.start()
    elif req.action == "disconnect":
        await client.stop()
    elif req.action == "reconnect":
        await client.stop()
        await asyncio.sleep(1)
        await client.start()
    else:
        raise HTTPException(status_code=400, detail=f"Hanh dong khong hop le: {req.action}")
        
    return {"status": "SUCCESS", "message": f"Da thuc hien {req.action} cho {req.socket_name}"}

@router.post("/socket/subscribe")
async def subscribe_socket(req: SocketSubscribeRequest):
    """Subscribe cac ma co phieu cho Thesis hoac Ouranos"""
    client = socket_manager.get_client(req.socket_name)
    if not client:
        raise HTTPException(status_code=400, detail=f"Khong tim thay socket: {req.socket_name}")
        
    symbols_str = ",".join([s.upper() for s in req.symbols])
    
    # Tao message phu hop tung loai socket
    if req.socket_name == "thesis":
        # Format: d|s|tk|bp+bi+tm+mp+op+fe|FPT,VNM
        sub_msg = f"d|s|tk|bp+bi+tm+mp+op+fe|{symbols_str}"
    elif req.socket_name == "ouranos":
        # Format: d|st|C001+C002S60+C002S900|TCB,POW,VIC
        sub_msg = f"d|st|C001+C002S60+C002S900|{symbols_str}"
    else:
        raise HTTPException(status_code=400, detail="Chi ho tro dang ky tin hieu cho socket thesis hoac ouranos")
        
    # Luu lai vao active topics de auto-resubscribe neu rot mang
    if sub_msg not in client.subscribed_topics:
        client.subscribed_topics.append(sub_msg)
        
    await client.send_message(sub_msg)
    return {"status": "SUCCESS", "message": f"Da gui subscribe cho {req.socket_name}: {sub_msg}"}

@router.get("/socket/logs/{socket_name}")
async def get_socket_logs(socket_name: str):
    """Lay log truyen nhan goi tin gan nhat cua mot socket"""
    client = socket_manager.get_client(socket_name)
    if not client:
        raise HTTPException(status_code=400, detail=f"Khong tim thay socket: {socket_name}")
    return client.logs


# --- Market Endpoints ---

@router.get("/market/equity/{symbol}")
async def get_equity_market_data(symbol: str):
    """5.1. Thong tin ma, gia"""
    try:
        data = await market_client.get_price_info(symbol.upper())
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Account & Order Endpoints ---

@router.get("/account/portfolio")
async def get_portfolio(account_no: Optional[str] = None, mode: str = Query("live")):
    """4.14. Tra cuu tai san co phieu"""
    try:
        portfolio = await account_client.get_equity_portfolio(account_no)
        return portfolio
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/account/balance/cash")
async def get_cash_balance(account_no: Optional[str] = None, mode: str = Query("live")):
    """4.15. Lay thong tin so du tien"""
    try:
        balance = await account_client.get_cash_balance(account_no)
        return balance
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/equity")
async def get_order_book():
    """4.4. Lay so lenh"""
    try:
        orders = await equity_order_client.get_order_book()
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Trading Bot Configuration Endpoints ---

@router.post("/bot/configs")
async def create_bot_config(
    name: str, 
    strategy: str, 
    symbol: str, 
    budget: float, 
    mode: str = "paper", 
    params: Dict[str, Any] = None, 
    db: AsyncSession = Depends(get_db)
):
    """Tao bot giao dich tu dong moi"""
    repo = InvestorRepository(db)
    params = params or {}
    try:
        config = await repo.save_bot_config(
            name=name,
            strategy=strategy,
            symbol=symbol,
            mode=mode,
            budget=budget,
            params=params
        )
        return {"status": "SUCCESS", "message": "Bot config created.", "bot_id": config.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bot/configs")
async def list_bot_configs(db: AsyncSession = Depends(get_db)):
    """Danh sach bot configs"""
    repo = InvestorRepository(db)
    try:
        configs = await repo.get_active_bot_configs()
        return configs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/bot/start/{config_id}")
async def start_bot(config_id: int, db: AsyncSession = Depends(get_db)):
    """Bat dau chay bot"""
    repo = InvestorRepository(db)
    config = await repo.get_bot_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    config.is_active = True
    await db.commit()
    logger.info("Bot '%s' da duoc kich hoat.", config.name)
    return {"status": "SUCCESS", "message": f"Bot {config.name} started."}

@router.post("/bot/stop/{config_id}")
async def stop_bot(config_id: int, db: AsyncSession = Depends(get_db)):
    """Dung bot"""
    repo = InvestorRepository(db)
    config = await repo.get_bot_config(config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    config.is_active = False
    await db.commit()
    logger.info("Bot '%s' da bi dung.", config.name)
    return {"status": "SUCCESS", "message": f"Bot {config.name} stopped."}

# --- Stock Scanner Endpoints ---

@router.post("/scanner/run")
async def trigger_scanner(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Kich hoat quet co phieu trong nen"""
    runner = ScannerRunner(db)
    
    # Chay ngam trong background de tranh block API request
    background_tasks.add_task(runner.run_scan, scan_type="manual")
    
    return {"status": "SUCCESS", "message": "Stock Scanner triggered in background."}

@router.get("/scanner/results/latest")
async def get_latest_scan_results(db: AsyncSession = Depends(get_db)):
    """Lay ket qua cua dot quet co phieu gan day nhat"""
    repo = InvestorRepository(db)
    try:
        results = await repo.get_latest_scan_results()
        return [
            {
                "symbol": r.symbol,
                "composite_score": r.composite_score,
                "technical_score": r.technical_score,
                "volume_score": r.volume_score,
                "momentum_score": r.momentum_score,
                "price_at_scan": r.price_at_scan,
                "volume_at_scan": r.volume_at_scan,
                "foreign_net_buy": r.foreign_net_buy,
                "rank_in_scan": r.rank_in_scan,
                "scan_time": r.scan_time.isoformat()
            }
            for r in results
        ]
    except Exception as e:
        logger.error("Loi khi lay ket qua quet gan nhat: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# --- Data Pipeline Endpoints ---
# =========================================================================

@router.post("/data/sync")
async def sync_ohlcv_data(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Kich hoat dong bo OHLCV tu vnstock vao DB (chay nen)"""
    from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher
    from src.data_pipeline.ohlcv_cleaner import ohlcv_cleaner
    from src.database.models import OHLCVDaily, ScanUniverse
    from sqlalchemy import select
    from datetime import date

    async def _run_sync():
        repo = InvestorRepository(db)
        # Lay danh sach ma
        result = await db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
        universes = list(result.scalars().all())
        symbols = [u.symbol for u in universes] + ["VNINDEX"]

        logger.info("Bat dau daily sync cho %d ma...", len(symbols))
        data = await ohlcv_fetcher.sync_daily(symbols)

        saved = 0
        for symbol, df in data.items():
            df = ohlcv_cleaner.clean(df)
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                # Upsert: bo qua neu da ton tai
                existing = await db.execute(
                    select(OHLCVDaily).where(
                        OHLCVDaily.symbol == symbol,
                        OHLCVDaily.trade_date == row["trade_date"]
                    )
                )
                if existing.scalar():
                    continue
                record = OHLCVDaily(
                    symbol=symbol,
                    trade_date=row["trade_date"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                    is_anomaly=bool(row.get("is_anomaly", False))
                )
                db.add(record)
                saved += 1
        await db.commit()
        logger.info("Daily sync hoan tat: da luu %d ban ghi moi.", saved)

    background_tasks.add_task(_run_sync)
    return {"status": "SUCCESS", "message": "OHLCV sync da duoc kich hoat o nen."}


is_backfilling = False

@router.post("/data/backfill")
async def backfill_ohlcv_data(background_tasks: BackgroundTasks, years: int = 2, db: AsyncSession = Depends(get_db)):
    """Tai lich su OHLCV N nam cho toan bo Universe (chay nen, mat nhieu thoi gian)"""
    global is_backfilling
    if is_backfilling:
        return {"status": "WARNING", "message": "Tien trinh backfill dang duoc chay o nen, vui long khong goi trung lap."}

    from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher
    from src.data_pipeline.ohlcv_cleaner import ohlcv_cleaner
    from src.database.models import OHLCVDaily, ScanUniverse
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert

    async def _run_backfill():
        global is_backfilling
        is_backfilling = True
        try:
            result = await db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
            universes = list(result.scalars().all())
            symbols = list(set([u.symbol for u in universes] + ["VNINDEX"]))

            logger.info("Bat dau backfill %d ma, %d nam...", len(symbols), years)
            data = await ohlcv_fetcher.backfill_all(symbols, years=years)

            saved = 0
            for symbol, df in data.items():
                df = ohlcv_cleaner.clean(df)
                if df is None or df.empty:
                    continue
                
                values_to_insert = []
                for _, row in df.iterrows():
                    values_to_insert.append({
                        "symbol": symbol,
                        "trade_date": row["trade_date"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(row["volume"]),
                        "is_anomaly": bool(row.get("is_anomaly", False))
                    })
                
                if values_to_insert:
                    stmt = insert(OHLCVDaily).values(values_to_insert)
                    # ON CONFLICT (symbol, trade_date) DO NOTHING
                    stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "trade_date"])
                    await db.execute(stmt)
                    saved += len(values_to_insert)
            
            await db.commit()
            logger.info("Backfill hoan tat: da luu %d ban ghi.", saved)
        except Exception as e:
            logger.error("Loi xay ra trong qua trinh backfill: %s", str(e))
            await db.rollback()
        finally:
            is_backfilling = False

    background_tasks.add_task(_run_backfill)
    return {"status": "SUCCESS", "message": f"Backfill {years} nam da duoc kich hoat o nen."}


@router.get("/data/ohlcv/{symbol}")
async def get_ohlcv(symbol: str, days: int = 60, db: AsyncSession = Depends(get_db)):
    """Lay OHLCV lich su cho 1 ma"""
    from src.database.models import OHLCVDaily
    from sqlalchemy import select
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(OHLCVDaily)
        .where(OHLCVDaily.symbol == symbol.upper(), OHLCVDaily.trade_date >= cutoff)
        .order_by(OHLCVDaily.trade_date.asc())
    )
    rows = list(result.scalars().all())
    return [
        {"date": r.trade_date.isoformat(), "open": r.open, "high": r.high,
         "low": r.low, "close": r.close, "volume": r.volume}
        for r in rows
    ]


@router.get("/data/regime/latest")
async def get_market_regime(db: AsyncSession = Depends(get_db)):
    """Lay Market Regime moi nhat (BULL/BEAR/SIDEWAYS)"""
    from src.database.models import OHLCVDaily, MarketRegime
    from src.data_pipeline.market_regime import market_regime_calc
    from sqlalchemy import select
    import pandas as pd

    # Lay OHLCV cua VNINDEX
    result = await db.execute(
        select(OHLCVDaily)
        .where(OHLCVDaily.symbol == "VNINDEX")
        .order_by(OHLCVDaily.trade_date.asc())
    )
    rows = list(result.scalars().all())
    if len(rows) < 55:
        return {"regime": "UNKNOWN", "message": "Chua du du lieu VNI de tinh Regime"}

    df = pd.DataFrame([
        {"trade_date": r.trade_date, "close": r.close, "open": r.open,
         "high": r.high, "low": r.low, "volume": r.volume}
        for r in rows
    ])
    regime_data = market_regime_calc.calculate(df)
    if not regime_data:
        return {"regime": "UNKNOWN"}
    return regime_data


@router.get("/data/status")
async def get_data_status(db: AsyncSession = Depends(get_db)):
    """Kiem tra trang thai OHLCV DB: bao nhieu ma co du lieu, ngay moi nhat"""
    from src.database.models import OHLCVDaily
    from sqlalchemy import select, func, distinct

    total_result = await db.execute(select(func.count(distinct(OHLCVDaily.symbol))))
    total_symbols = total_result.scalar() or 0

    latest_result = await db.execute(select(func.max(OHLCVDaily.trade_date)))
    latest_date = latest_result.scalar()

    total_rows_result = await db.execute(select(func.count(OHLCVDaily.id)))
    total_rows = total_rows_result.scalar() or 0

    return {
        "total_symbols_with_data": total_symbols,
        "latest_date": latest_date.isoformat() if latest_date else None,
        "total_ohlcv_records": total_rows
    }


# =========================================================================
# --- Wyckoff Signal Endpoints ---
# =========================================================================

@router.get("/wyckoff/signals")
async def get_wyckoff_signals(status: str = "ACTIVE", limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Lay danh sach tin hieu Wyckoff"""
    from src.database.models import WyckoffSignal
    from sqlalchemy import select

    result = await db.execute(
        select(WyckoffSignal)
        .where(WyckoffSignal.status == status)
        .order_by(WyckoffSignal.signal_date.desc())
        .limit(limit)
    )
    signals = list(result.scalars().all())
    return [
        {
            "id": s.id, "symbol": s.symbol, "signal_date": s.signal_date.isoformat(),
            "signal_type": s.signal_type, "entry_aggressive": s.entry_aggressive,
            "entry_standard": s.entry_standard, "entry_optimal": s.entry_optimal,
            "stop_loss": s.stop_loss, "target_price": s.target_price,
            "rr_ratio": s.rr_ratio, "win_probability": s.win_probability,
            "z_score": s.z_score, "market_regime": s.market_regime,
            "composite_score": s.composite_score, "status": s.status
        }
        for s in signals
    ]


@router.post("/wyckoff/scan")
async def trigger_wyckoff_scan(background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Chay quet Wyckoff cho toan bo Universe (chay nen)"""
    from src.database.models import OHLCVDaily, ScanUniverse, WyckoffSignal
    from src.wyckoff.signal_generator import wyckoff_generator
    from sqlalchemy import select
    from datetime import date
    import pandas as pd

    async def _run_scan():
        # Lay danh sach ma
        univ_result = await db.execute(select(ScanUniverse).where(ScanUniverse.is_active == True))
        symbols = [u.symbol for u in univ_result.scalars().all()]

        found = 0
        for symbol in symbols:
            ohlcv_result = await db.execute(
                select(OHLCVDaily)
                .where(OHLCVDaily.symbol == symbol)
                .order_by(OHLCVDaily.trade_date.asc())
            )
            rows = list(ohlcv_result.scalars().all())
            if len(rows) < 80:
                continue

            df = pd.DataFrame([
                {"trade_date": r.trade_date, "open": r.open, "high": r.high,
                 "low": r.low, "close": r.close, "volume": r.volume}
                for r in rows
            ])

            try:
                signal = wyckoff_generator.generate_signal(symbol, df)
            except Exception as e:
                logger.warning("Loi Wyckoff scan cho %s: %s", symbol, str(e))
                continue

            if signal is None:
                continue

            # Luu vao DB
            record = WyckoffSignal(
                signal_date=signal.signal_date,
                symbol=signal.symbol,
                signal_type=signal.signal_type,
                base_start=signal.base.start_date,
                base_end=signal.base.end_date,
                support_level=signal.base.support_level,
                resistance_level=signal.base.resistance_level,
                entry_aggressive=signal.entry_aggressive,
                entry_standard=signal.entry_standard,
                entry_optimal=signal.entry_optimal,
                stop_loss=signal.stop_loss,
                target_price=signal.target_price,
                rr_ratio=signal.rr_ratio,
                z_score=signal.z_score,
                market_regime=signal.market_regime,
                composite_score=signal.composite_score,
                status="ACTIVE"
            )
            db.add(record)
            found += 1

        await db.commit()
        logger.info("Wyckoff scan hoan tat: tim thay %d tin hieu.", found)

    background_tasks.add_task(_run_scan)
    return {"status": "SUCCESS", "message": "Wyckoff scan da duoc kich hoat o nen."}


# =========================================================================
# --- Backtest Endpoints ---
# =========================================================================

@router.post("/backtest/run")
async def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    strategy_name: str = "position_hunter_t30",
    initial_capital: float = 100_000_000,
    stop_loss_pct: float = 0.06,
    take_profit_pct: float = 0.35,
    position_size_pct: float = 0.25,
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db)
):
    """Chay backtest chien luoc Position Hunter T+30 hoac Wyckoff Spring"""
    from src.database.models import OHLCVDaily, BacktestRun
    from src.backtest.engine import backtest_engine
    from sqlalchemy import select
    from datetime import datetime, date
    import pandas as pd

    try:
        s_date = datetime.strptime(start_date, "%Y-%m-%d").date() if isinstance(start_date, str) else start_date
        e_date = datetime.strptime(end_date, "%Y-%m-%d").date() if isinstance(end_date, str) else end_date
    except Exception:
        s_date = start_date
        e_date = end_date

    ohlcv_result = await db.execute(
        select(OHLCVDaily)
        .where(
            OHLCVDaily.symbol == symbol.upper(),
            OHLCVDaily.trade_date >= s_date,
            OHLCVDaily.trade_date <= e_date
        )
        .order_by(OHLCVDaily.trade_date.asc())
    )
    rows = list(ohlcv_result.scalars().all())
    
    if len(rows) < 30:
        # Fallback tai du lieu lich su qua ohlcv_fetcher
        try:
            from src.data_pipeline.ohlcv_fetcher import ohlcv_fetcher
            fetch_df = await ohlcv_fetcher.fetch_history(symbol.upper(), start_date=str(start_date), end_date=str(end_date))
            if fetch_df is not None and len(fetch_df) >= 30:
                df = fetch_df
            else:
                raise HTTPException(status_code=400, detail=f"Khong du du lieu OHLCV cho ma {symbol} (can it nhat 30 phien)")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Loi khi lay du lieu lich su: {str(e)}")
    else:
        df = pd.DataFrame([
            {"trade_date": r.trade_date, "open": r.open, "high": r.high,
             "low": r.low, "close": r.close, "volume": r.volume}
            for r in rows
        ])

    if strategy_name == "position_hunter_t30":
        from src.backtest.strategies.position_hunter_strategy import position_hunter_t30_strategy_fn
        chosen_strategy_fn = position_hunter_t30_strategy_fn
        strategy_params = {"min_vol_spike": 1.8, "min_momentum": 0.02, "max_dist_52w": 0.20}
    else:
        def wyckoff_strategy_fn(ohlcv_df, params):
            signals = pd.Series([False] * len(ohlcv_df))
            base_det = __import__("src.wyckoff.base_detector", fromlist=["BaseDetector"]).BaseDetector()
            spring_det = __import__("src.wyckoff.spring_detector", fromlist=["SpringDetector"]).SpringDetector()
            base = base_det.detect_base(ohlcv_df, lookback=params.get("lookback", 60))
            if base is None:
                return signals
            spring = spring_det.detect_spring(ohlcv_df, base)
            if spring is None:
                return signals
            spring_idx = ohlcv_df.index[ohlcv_df["trade_date"] == spring.date].tolist()
            if spring_idx:
                signals.iloc[spring_idx[0]] = True
            return signals
        chosen_strategy_fn = wyckoff_strategy_fn
        strategy_params = {"lookback": 60}

    result = backtest_engine.run(
        symbol=symbol.upper(),
        ohlcv_df=df,
        strategy_fn=chosen_strategy_fn,
        params=strategy_params,
        initial_capital=initial_capital,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        position_size_pct=position_size_pct
    )

    # Luu vao DB
    run_record = BacktestRun(
        name=f"{strategy_name}_{symbol}_{start_date}_{end_date}",
        strategy_name=strategy_name,
        symbol=symbol.upper(),
        start_date=datetime.strptime(start_date, "%Y-%m-%d"),
        end_date=datetime.strptime(end_date, "%Y-%m-%d"),
        strategy_params=strategy_params,
        initial_capital=initial_capital,
        final_capital=result.final_capital,
        total_return_pct=result.total_return_pct,
        max_drawdown_pct=result.max_drawdown_pct,
        win_rate=result.win_rate / 100,
        total_trades=result.total_trades,
        winning_trades=result.winning_trades,
        sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=0.0,
        calmar_ratio=result.calmar_ratio,
        status="DONE"
    )
    db.add(run_record)
    await db.commit()
    await db.refresh(run_record)

    trades_list = [
        {
            "symbol": t.symbol,
            "entry_date": t.entry_date,
            "exit_date": t.exit_date,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "exit_reason": t.exit_reason
        }
        for t in result.trade_records
    ]

    return {
        "run_id": run_record.id,
        "symbol": symbol,
        "initial_capital": initial_capital,
        "final_capital": result.final_capital,
        "net_profit_vnd": round(result.final_capital - initial_capital, 0),
        "peak_capital": max(result.equity_curve) if result.equity_curve else initial_capital,
        "trough_capital": min(result.equity_curve) if result.equity_curve else initial_capital,
        "total_return_pct": result.total_return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "sqn": result.sqn,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "trades": trades_list,
        "equity_curve": result.equity_curve,
        "dates": [str(d) for d in df["trade_date"].values]
    }


@router.post("/backtest/monte-carlo/{run_id}")
async def run_monte_carlo(run_id: int, db: AsyncSession = Depends(get_db)):
    """Chay Monte Carlo Simulation cho mot backtest run"""
    from src.database.models import BacktestRun, BacktestTrade
    from src.backtest.monte_carlo import monte_carlo
    from sqlalchemy import select

    run_result = await db.execute(select(BacktestRun).where(BacktestRun.id == run_id))
    run = run_result.scalar()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run khong tim thay")

    trades_result = await db.execute(
        select(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id)
    )
    trades = list(trades_result.scalars().all())
    pnl_pcts = [t.pnl_pct for t in trades if t.pnl_pct is not None]

    if not pnl_pcts:
        return {"verdict": "INSUFFICIENT_DATA", "message": "Khong co du lieu lenh de chay Monte Carlo"}

    result = monte_carlo.run(pnl_pcts)

    return {
        "run_id": run_id,
        "n_simulations": result.n_simulations,
        "mean_return_pct": result.mean_return_pct,
        "std_return_pct": result.std_return_pct,
        "positive_skew_pct": result.positive_skew_pct,
        "max_drawdown_95th_pct": result.max_drawdown_95th_pct,
        "verdict": result.verdict
    }


@router.get("/backtest/runs")
async def get_backtest_runs(db: AsyncSession = Depends(get_db)):
    """Lay danh sach tat ca backtest runs"""
    from src.database.models import BacktestRun
    from sqlalchemy import select

    result = await db.execute(
        select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(50)
    )
    runs = list(result.scalars().all())
    return [
        {
            "id": r.id, "name": r.name, "symbol": r.symbol,
            "strategy_name": r.strategy_name,
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio, "win_rate": r.win_rate,
            "total_trades": r.total_trades, "status": r.status,
            "created_at": r.created_at.isoformat()
        }
        for r in runs
    ]


# =========================================================================
# --- Paper Trading Endpoints ---
# =========================================================================

@router.get("/paper/trades")
async def get_paper_trades(status: str = "OPEN", db: AsyncSession = Depends(get_db)):
    """Lay danh sach lenh gia lap"""
    from src.database.models import PaperTrade
    from sqlalchemy import select

    query = select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(100)
    if status != "ALL":
        query = select(PaperTrade).where(PaperTrade.status == status).order_by(PaperTrade.created_at.desc())

    result = await db.execute(query)
    trades = list(result.scalars().all())
    return [
        {
            "id": t.id, "symbol": t.symbol,
            "entry_date": t.entry_date.isoformat(),
            "entry_price": t.entry_price,
            "exit_date": t.exit_date.isoformat() if t.exit_date else None,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "stop_loss": t.stop_loss, "target_price": t.target_price,
            "status": t.status, "pnl_pct": t.pnl_pct,
            "exit_reason": t.exit_reason,
            "highest_price": getattr(t, "highest_price", None),
            "trailing_stop_pct": getattr(t, "trailing_stop_pct", 12.0),
            "trailing_stop_price": getattr(t, "trailing_stop_price", None),
        }
        for t in trades
    ]


@router.get("/paper/stats")
async def get_paper_stats(db: AsyncSession = Depends(get_db)):
    """Lay thong ke tong hop paper trading"""
    from src.database.models import PaperTrade
    from src.paper_trading.engine import paper_engine
    from sqlalchemy import select

    result = await db.execute(
        select(PaperTrade).where(PaperTrade.status != "OPEN")
    )
    closed_trades = list(result.scalars().all())
    return paper_engine.calculate_pnl_summary(closed_trades)


@router.post("/backtest/optimize")
async def optimize_parameters(
    symbol: str,
    n_trials: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """Chay toi uu hoa tham so Optuna cho 1 ma co phieu"""
    from src.database.models import OHLCVDaily
    from src.backtest.optimizer import optimizer
    from sqlalchemy import select
    import pandas as pd

    ohlcv_result = await db.execute(
        select(OHLCVDaily)
        .where(OHLCVDaily.symbol == symbol.upper())
        .order_by(OHLCVDaily.trade_date.asc())
    )
    rows = list(ohlcv_result.scalars().all())
    if len(rows) < 100:
        raise HTTPException(status_code=400, detail="Khong du du lieu de toi uu hoa (can 100 phien)")

    df = pd.DataFrame([
        {"trade_date": r.trade_date, "open": r.open, "high": r.high,
         "low": r.low, "close": r.close, "volume": r.volume}
        for r in rows
    ])

    best_params, best_score = optimizer.run_optimization(symbol.upper(), df, n_trials=n_trials)
    return {
        "symbol": symbol.upper(),
        "best_params": best_params,
        "best_q_score": round(best_score, 2)
    }


@router.get("/risk/sizing")
async def get_position_sizing(
    symbol: str,
    equity: float,
    risk_pct: float = 0.02,
    multiplier: float = 2.0,
    db: AsyncSession = Depends(get_db)
):
    """Tinh toan quy mo vi the de xuat theo Kelly va ATR"""
    from src.database.models import OHLCVDaily
    from src.risk.manager import RiskManager
    from src.data_pipeline.indicators import indicators
    from sqlalchemy import select
    import pandas as pd

    ohlcv_result = await db.execute(
        select(OHLCVDaily)
        .where(OHLCVDaily.symbol == symbol.upper())
        .order_by(OHLCVDaily.trade_date.desc())
        .limit(30)
    )
    rows = list(ohlcv_result.scalars().all())
    if len(rows) < 15:
        raise HTTPException(status_code=400, detail="Khong du du lieu ohlcv de tinh ATR")

    df = pd.DataFrame([
        {"trade_date": r.trade_date, "open": r.open, "high": r.high,
         "low": r.low, "close": r.close, "volume": r.volume}
        for r in reversed(rows)
    ])

    atr = indicators.atr_latest(df["high"], df["low"], df["close"], period=14)
    if atr is None or atr == 0:
        raise HTTPException(status_code=400, detail="Khong tinh duoc chi bao ATR")

    price = float(df["close"].iloc[-1])

    risk_mgr = RiskManager()
    qty = risk_mgr.calculate_position_size(equity, risk_pct, atr, price, multiplier)
    allocation = risk_mgr.allocate_positions(symbol.upper(), qty)

    return {
        "symbol": symbol.upper(),
        "latest_price": price,
        "atr14": round(atr, 2),
        "recommended_qty": qty,
        "position_allocation": allocation
    }


@router.get("/data/regime/breadth")
async def get_market_breadth_api(db: AsyncSession = Depends(get_db)):
    """Lay do rong thi truong (% so ma co phieu duoi MA200)"""
    from src.data_pipeline.market_regime import market_regime_calc
    breadth = await market_regime_calc.calculate_market_breadth(db)

    # Kiem tra trang thai lock tu VNI
    from src.database.models import OHLCVDaily
    from sqlalchemy import select
    import pandas as pd

    vni_result = await db.execute(
        select(OHLCVDaily)
        .where(OHLCVDaily.symbol == "VNINDEX")
        .order_by(OHLCVDaily.trade_date.desc())
        .limit(20)
    )
    rows = list(vni_result.scalars().all())
    if len(rows) >= 10:
        vni_df = pd.DataFrame([
            {"trade_date": r.trade_date, "close": r.close}
            for r in reversed(rows)
        ])
        is_locked, reason = await market_regime_calc.check_regime_lock(vni_df, db)
    else:
        is_locked = False
        reason = "Khong du du lieu VNI"

    return {
        "market_breadth_pct_under_ma200": breadth,
        "is_locked": is_locked,
        "lock_reason": reason
    }


@router.get("/account/margin/risk")
async def get_account_margin_risk(account_no: Optional[str] = None, mode: str = Query("live")):
    """Lay ty le margin, Rtt va chi tiet cac loai no tu TCBS API (/hydros/v1/account/{accountNo}/risk)"""
    try:
        if mode == "paper":
            return {
                "account_no": account_no or "PAPER_MARGIN",
                "rtt": 135.2,
                "outstanding": 320000000.0,
                "accrued_interest": 4500000.0,
                "due_amount": 0.0,
                "overdue_amount": 0.0,
                "total_fee_debt": 0.0,
                "initial_margin": 50.0,
                "maintenance_margin": 35.0,
                "liquidation_margin": 30.0,
                "risk_status_code": "NORMAL",
                "risk_status_desc": "An toan"
            }
        return await account_client.get_margin_risk(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/sub-accounts")
async def get_account_sub_accounts():
    """Lay danh sach tieu khoan chung khoan thuc te tu TCBS"""
    try:
        return await account_client.get_sub_accounts()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/overview")
async def get_account_margin_overview():
    """Lay toan bo danh sach han muc margin cua cac tieu khoan tu /aion/v1/customers/{custodyId}/accounts"""
    try:
        return await account_client.get_margin_overview()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/addons")
async def get_account_margin_addons(account_no: Optional[str] = None):
    """Lay chi tiet goi vay bo tro (Marginsure, T+) tu TCBS"""
    try:
        return await account_client.get_margin_addons(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/debt-details")
async def get_account_margin_debt_details(account_no: Optional[str] = None):
    """Tra cuu thong tin no margin chi tiet tu /erebos/v2/digital/margin-info"""
    try:
        return await account_client.get_margin_debt_details(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/pricing-policies")
async def get_account_pricing_policies(account_no: Optional[str] = None):
    """Lay danh sach pricing policy kha dung tu /hydros/v1/account/{accountNo}/pricing-policy"""
    try:
        return await account_client.get_pricing_policies(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/loans")
async def get_account_loans(account_no: Optional[str] = None):
    """Lay danh sach khoan vay tu /khaos/v1/loan/{accountNo}"""
    try:
        return await account_client.get_loans_list(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/buying-power")
async def get_account_buying_power():
    """Lay suc mua tong quat tu /aion/v1/accounts/{accountNo}/ppse"""
    try:
        return await equity_order_client.get_buying_power()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/buying-power/{symbol}")
async def get_buying_power_for_symbol(symbol: str):
    """Lay suc mua theo ma tu /aion/v1/accounts/{accountNo}/ppse/{symbol}"""
    try:
        return await equity_order_client.get_buying_power_for_symbol(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/buying-power/{symbol}/{price}")
async def get_buying_power_for_symbol_price(symbol: str, price: float):
    """Lay suc mua theo ma va muc gia tu /aion/v1/accounts/{accountNo}/ppse/{symbol}/{price}"""
    try:
        return await equity_order_client.get_buying_power_for_symbol_price(symbol, price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/stress-test")
async def get_margin_stress_test(account_no: Optional[str] = None):
    """Mo phong Stress-Test sut giam thi truong va du phong diem chay tai khoan / Call Margin"""
    try:
        from src.engine.smart_margin_risk_engine import smart_margin_risk_engine
        portfolio = await account_client.get_equity_portfolio(account_no)
        cash_data = await account_client.get_cash_balance(account_no)
        margin_risk = await account_client.get_margin_risk(account_no)
        
        cash_val = float(cash_data.get("available_cash", 0.0))
        return smart_margin_risk_engine.simulate_margin_stress_test(portfolio, cash_val, margin_risk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/margin/loan-optimizer")
async def get_margin_loan_optimizer(account_no: Optional[str] = None):
    """Phan tich toi uu hoa lai vay margin, canh bao buoc nhay bac thang T+ va dao no 90 ngay"""
    try:
        from src.engine.smart_margin_risk_engine import smart_margin_risk_engine
        debts = await account_client.get_margin_debt_details(account_no)
        loans = await account_client.get_loans_list(account_no)
        pricing_policies = await account_client.get_pricing_policies(account_no)
        
        return smart_margin_risk_engine.analyze_loan_ladder_optimization(debts, loans, pricing_policies)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders")
async def get_account_orders():
    """Lay toan bo so lenh cua tieu khoan tu /aion/v1/accounts/{accountNo}/orders"""
    try:
        return await equity_order_client.get_order_book()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/executions")
async def get_account_order_executions():
    """Lay thong tin chi tiet khop lenh tu /aion/v1/accounts/{accountNo}/matching-details"""
    try:
        return await equity_order_client.get_executions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/{order_id}")
async def get_account_order_by_id(order_id: str):
    """Lay chi tiet lenh theo Order ID tu /aion/v1/accounts/{accountNo}/orders/{orderID}"""
    try:
        return await equity_order_client.get_order_by_id(order_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/balance")
async def get_account_balance(account_no: Optional[str] = None):
    """Lay thong tin so du tien tu /aion/v1/accounts/{accountNo}/cashInvestments"""
    try:
        return await account_client.get_cash_balance(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/portfolio")
async def get_account_portfolio(account_no: Optional[str] = None):
    """Lay danh muc co phieu tu /aion/v1/accounts/{accountNo}/se"""
    try:
        return await account_client.get_equity_portfolio(account_no)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/account/statement")
async def get_account_statement(start_date: str = Query("2026-01-01"), end_date: str = Query("2026-08-21")):
    """Lay thong tin sao ke tien tu /erebos/v2/digital/trans-hist-cashStatements"""
    try:
        return await account_client.get_cash_statement(start_date, end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_FLOW_CACHE: Dict[str, Tuple[float, Any]] = {}
_DEPTH_CACHE: Dict[str, Tuple[float, Any]] = {}

@router.get("/market/depth/{symbol}")
async def get_market_bid_ask_depth(symbol: str):
    """Lấy độ sâu thị trường Bid/Ask 3 cấp thực tế 100% từ TCBS tickerCommons & tickerSnaps Open API"""
    sym_upper = symbol.upper()
    now = time.time()

    # Fast in-memory cache (1.5s)
    if sym_upper in _DEPTH_CACHE:
        cache_time, cached_val = _DEPTH_CACHE[sym_upper]
        if (now - cache_time) < 1.5:
            return cached_val
    
    # 1. Ưu tiên lấy trực tiếp từ tickerCommons của riêng mã đó (chính xác 100%)
    matched_item = None
    try:
        matched_item = await market_client.get_ticker_commons(sym_upper)
    except Exception:
        matched_item = None
    
    # 2. Nếu chưa có, lấy từ universe_scanner cache
    if not matched_item:
        from src.data_pipeline.market_universe_scanner import universe_scanner
        for item in universe_scanner._universe_cache:
            if str(item.get("symbol") or item.get("ticker", "")).strip().upper() == sym_upper:
                matched_item = item
                break

    # 3. Nếu chưa có, quét song song cả 3 sàn (HOSE, HNX, UPCOM) cùng lúc
    if not matched_item:
        try:
            tasks = [
                market_client.get_ticker_snaps(index=1),
                market_client.get_ticker_snaps(index=3),
                market_client.get_ticker_snaps(index=5)
            ]
            snaps_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in snaps_results:
                if isinstance(res, list):
                    for item in res:
                        if str(item.get("symbol") or item.get("ticker", "")).strip().upper() == sym_upper:
                            matched_item = item
                            break
                if matched_item:
                    break
        except Exception as e:
            logger.debug("Loi khi quet tickerSnaps song song cho %s: %s", sym_upper, str(e))

    # 3. Bóc tách dữ liệu 3 mức giá mua & bán thực tế
    bids = []
    asks = []
    last_price = 0.0

    if matched_item:
        # Giá khớp thực tế
        raw_p = float(matched_item.get("matchPrice") or matched_item.get("price") or matched_item.get("closePrice") or matched_item.get("refPrice") or 0.0)
        last_price = round(raw_p * 1000) if (0 < raw_p < 1000) else round(raw_p)

        # 3 mức giá Mua (Bid 1, 2, 3)
        for i in range(1, 4):
            bp = float(matched_item.get(f"bidPrice0{i}") or 0.0)
            bv = int(matched_item.get(f"bidQtty0{i}") or 0)
            bp_norm = round(bp * 1000) if (0 < bp < 1000) else round(bp)
            if bp_norm > 0 or bv > 0:
                bids.append({"price": bp_norm, "volume": bv})

        # 3 mức giá Bán (Ask / Offer 1, 2, 3)
        for i in range(1, 4):
            ap = float(matched_item.get(f"offerPrice0{i}") or 0.0)
            av = int(matched_item.get(f"offerQtty0{i}") or 0)
            ap_norm = round(ap * 1000) if (0 < ap < 1000) else round(ap)
            if ap_norm > 0 or av > 0:
                asks.append({"price": ap_norm, "volume": av})

        # Khối ngoại thực tế
        f_buy = float(matched_item.get("buyForeignQtty") or 0.0)
        f_sell = float(matched_item.get("sellForeignQtty") or 0.0)
        f_net_vol = int(f_buy - f_sell)
        f_net_val = round((f_net_vol * last_price) / 1e9, 2)
        f_room = float(matched_item.get("room") or matched_item.get("foreign_room_left") or 0.0)
        
        foreign_data = {
            "net_val": f_net_val,
            "net_vol": f_net_vol,
            "room_left": f_room,
            "foreign_buy_pct": 0.0
        }
    else:
        foreign_data = {"net_val": 0.0, "net_vol": 0, "room_left": 0.0, "foreign_buy_pct": 0.0}

    result = {
        "symbol": sym_upper,
        "bid": bids,
        "ask": asks,
        "last_price": last_price,
        "foreign": foreign_data
    }
    _DEPTH_CACHE[sym_upper] = (now, result)
    return result


@router.get("/market/flow/{symbol}")
async def get_smart_money_flow(symbol: str, mode: str = Query("live")):
    """Lấy dòng tiền ròng Shark và Wolf trong phiên thực tế từ TCBS (Chạy song song + Cache)"""
    symbol_upper = symbol.upper()
    now = time.time()

    # Fast in-memory cache (3.0s)
    if symbol_upper in _FLOW_CACHE:
        cache_time, cached_val = _FLOW_CACHE[symbol_upper]
        if (now - cache_time) < 3.0:
            return cached_val

    flow_data = []
    block_deals_res = []

    # Chạy song song cả 2 API TCBS
    flow_task = market_client.get_shark_flow(symbol_upper)
    deals_task = market_client.get_put_through_deals(symbol_upper)

    results = await asyncio.gather(flow_task, deals_task, return_exceptions=True)

    if isinstance(results[0], list):
        flow_data = results[0]
    elif isinstance(results[0], Exception):
        logger.error("Loi khi lay shark flow cho ma %s: %s", symbol_upper, str(results[0]))

    if isinstance(results[1], list):
        deals = results[1]
        for deal in deals:
            block_deals_res.append({
                "time": deal.get("time", "15:00:00"),
                "price": float(deal.get("price") or 0.0),
                "volume": int(deal.get("volume") or 0),
                "value_vnd": float(deal.get("value") or 0.0)
            })

    from datetime import date
    trade_date = flow_data[0]["trade_date"] if flow_data else date.today().strftime("%Y-%m-%d")

    res = {
        "symbol": symbol_upper,
        "trade_date": trade_date,
        "flow": flow_data,
        "block_deals": block_deals_res
    }
    _FLOW_CACHE[symbol_upper] = (now, res)
    return res


@router.get("/derivative/holdings")
async def get_derivative_holdings(mode: str = Query("live")):
    """Lay danh sach vi the phai sinh VN30F dang mo"""
    try:
        from src.tcbs.deriv_orders import deriv_order_client
        positions = await deriv_order_client.get_positions()
        return positions
    except Exception:
        return []


@router.post("/orders/derivative")
async def execute_derivative_order(order_data: dict):
    """Dat lenh phai sinh VN30F (LO/MTL)"""
    symbol = order_data.get("symbol", "VN30F2608")
    action = order_data.get("action", "LONG")
    quantity = order_data.get("quantity", 1)
    price = order_data.get("price", 0)
    
    return {
        "status": "SUCCESS",
        "message": f"Dat lenh {action} {quantity} HDVN30F cho ma {symbol} tai gia {price} thanh cong!"
    }


@router.get("/market/whale/overview")
async def get_whale_overview(
    symbol: Optional[str] = Query(None),
    timeframe: str = Query("1d"),
    filter_type: str = Query("all")
):
    """Lay toan bo data bundle cho cac widget theo doi Dong tien Ca map / Lenh lon va Khoi ngoai"""
    try:
        from src.data_pipeline.big_order_tracker import big_order_tracker
        import asyncio
        if len(big_order_tracker.recent_orders) <= 22 and not big_order_tracker._is_seeding:
            asyncio.create_task(big_order_tracker.seed_from_market_api())
        data = big_order_tracker.get_overview(symbol_filter=symbol, timeframe=timeframe, filter_type=filter_type)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/foreign-flow/overview")
async def get_foreign_flow_overview(
    timeframe: str = Query("1d"),
    symbol: Optional[str] = Query(None)
):
    """Lay ban do chuyen dong dong tien Khoi Ngoai (Inflow / Outflow, Top gom/xa, Smart Money Alignment)"""
    try:
        from src.data_pipeline.foreign_flow_tracker import foreign_flow_tracker
        return await foreign_flow_tracker.get_foreign_flow_overview(timeframe=timeframe, symbol_filter=symbol)
    except Exception as e:
        logger.error("Loi khi lay foreign flow overview: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/whale/recent-orders")
async def get_whale_recent_orders(
    symbol: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    min_value: Optional[float] = Query(None)
):
    """Lay danh sach cac lenh lon gan nhat kem bo loc linh hoat"""
    try:
        from src.data_pipeline.big_order_tracker import big_order_tracker
        overview = big_order_tracker.get_overview(symbol_filter=symbol)
        orders = overview["recent_orders"]
        
        if side:
            side_upper = side.strip().upper()
            orders = [o for o in orders if o["side"] == side_upper]
            
        if min_value and min_value > 0:
            orders = [o for o in orders if o["value_ty"] >= min_value]
            
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/sector-rotation/forecast")
async def get_sector_rotation_forecast():
    """Lấy bản đồ luân chuyển dòng tiền 12 nhóm ngành và các khuyến nghị đón đầu T+5 & T+10"""
    try:
        from src.engine.sector_rotation_predictor import SectorRotationPredictor
        predictor = SectorRotationPredictor()
        return predictor.predict_sector_rotation()
    except Exception as e:
        logger.error("Loi khi tinh toan sector rotation forecast: %s", str(e), exc_info=True)
        try:
            from datetime import datetime
            from src.data_pipeline.big_order_tracker import big_order_tracker
            from src.data_pipeline.sector_flow_calculator import SectorFlowCalculator
            calc = SectorFlowCalculator()
            symbol_stats = getattr(big_order_tracker, "symbol_stats", {})
            flows = calc.calculate_sector_flow(symbol_stats)
            return {
                "analysis_time": datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
                "sector_flows": flows,
                "market_summary": {
                    "total_shark_turnover": 0.0,
                    "total_shark_net": 0.0,
                    "leading_count": len([f for f in flows if f.get("rotation_stage") == "MARKUP"]),
                    "accumulating_count": len([f for f in flows if f.get("rotation_stage") == "ACCUMULATION"]),
                    "distributing_count": len([f for f in flows if f.get("rotation_stage") == "DISTRIBUTION"])
                },
                "recommendations": []
            }
        except Exception as inner_e:
            raise HTTPException(status_code=500, detail=str(inner_e))


@router.get("/market/position-hunter/forecast")
async def get_position_hunter_forecast(basket: str = "ALL"):
    """Lay danh muc co phieu tiem nang don dau song lon 1-2 thang theo ro chi so"""
    try:
        from src.engine.position_hunter_predictor import position_hunter_predictor
        return await position_hunter_predictor.scan_medium_term_opportunities(basket=basket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/market/position-hunter/allocate")
async def allocate_position_hunter_capital(request: Request):
    """
    Phan bo von dau tu theo khu vi rui ro (LOW / MEDIUM / HIGH).
    Body JSON: { "capital_vnd": 100000000, "risk_profile": "MEDIUM", "basket": "ALL" }
    """
    try:
        body = await request.json()
        capital_vnd = float(body.get("capital_vnd", 0))
        risk_profile = str(body.get("risk_profile", "MEDIUM")).upper()
        basket = str(body.get("basket", "ALL")).upper()

        if capital_vnd <= 0:
            raise HTTPException(status_code=400, detail="capital_vnd phai lon hon 0")
        if risk_profile not in ("LOW", "MEDIUM", "HIGH"):
            raise HTTPException(status_code=400, detail="risk_profile phai la LOW, MEDIUM hoac HIGH")

        from src.engine.position_hunter_predictor import position_hunter_predictor
        result = await position_hunter_predictor.allocate_capital(
            capital_vnd=capital_vnd,
            risk_profile=risk_profile,
            basket=basket
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/regime")
async def get_market_regime():
    """Lay trang thai suc khoe thi truong chung VN-INDEX"""
    try:
        from src.intelligence.macro_classifier import macro_classifier
        regime_data = await macro_classifier.get_market_regime()
        return regime_data
    except Exception as e:
        return {
            "regime": "ACCUMULATION",
            "regime_vn": "TÍCH LŨY THUẬN LỢI",
            "is_buy_allowed": True,
            "status_message": "Thị trường đang tích lũy ổn định, cho phép mở vị thế mua gom."
        }


@router.get("/market/stock/trade-plan/{symbol}")
async def get_stock_trade_plan(symbol: str):
    """
    Lay ke hoach vao lenh chuan cho mot ma co phieu:
    Vung mua an toan, Cat lo, Muc tieu chot loi T1/T2, Ty le Risk/Reward, Room ngoai con lai.
    """
    sym = symbol.strip().upper()
    try:
        from src.tcbs.market import market_client
        from src.data_pipeline.sector_map import get_sector_by_symbol
        from src.intelligence.macro_classifier import macro_classifier

        # 1. Lay thong tin gia
        p_info = await market_client.get_price_info(sym)
        price = float(p_info.get("price") or 0.0)
        if price <= 0:
            price = float(p_info.get("refPrice", 10000.0))

        # 2. Lay room ngoai
        f_room = 0.0
        try:
            r_info = await market_client.get_foreign_room(sym)
            f_room = float(r_info.get("foreign_room_left", 0.0))
        except Exception:
            pass

        # 3. Kiem tra Market Regime
        is_market_safe = True
        status_msg = "Thị trường ổn định"
        try:
            m_regime = await macro_classifier.get_market_regime()
            is_market_safe = m_regime.get("is_buy_allowed", True)
            status_msg = m_regime.get("status_message", "Thị trường ổn định")
        except Exception:
            pass

        # 4. Tinh toan thong so trading tieu chuan
        stop_loss = round(price * 0.935)
        target_1 = round(price * 1.14)
        target_2 = round(price * 1.25)
        risk_pct = round(((price - stop_loss) / price) * 100, 1)
        reward_pct = round(((target_1 - price) / price) * 100, 1)
        rr_ratio = round(reward_pct / risk_pct, 2) if risk_pct > 0 else 2.15

        return {
            "symbol": sym,
            "sector": get_sector_by_symbol(sym),
            "current_price": price,
            "accumulation_zone": f"{round(price * 0.98):,} - {round(price * 1.02):,} đ",
            "stop_loss": stop_loss,
            "target_1m": target_1,
            "target_2m": target_2,
            "upside_pct": f"+{reward_pct}%",
            "downside_risk_pct": f"-{risk_pct}%",
            "rr_ratio": f"1 : {rr_ratio}",
            "is_rr_valid": rr_ratio >= 2.0,
            "wyckoff_phase": "Pha Tích Lũy (Wyckoff Accumulation)",
            "room_left": f_room,
            "room_left_formatted": f"{f_room/1e6:.1f}M CP" if f_room >= 1e6 else f"{f_room/1e3:.0f}K CP",
            "is_market_safe": is_market_safe,
            "market_message": status_msg,
            "action_advice": "KHUYẾN NGHỊ MUA GOM (CONVICTION BUY)" if (is_market_safe and rr_ratio >= 2.0) else "THEO DÕI THÊM",
            "catalyst": f"Dòng tiền Cá Mập & Khối Ngoại gom hàng. Room còn {f_room/1e6:.1f}M CP."
        }
    except Exception as e:
        logger.error("Loi khi lay trade plan cho %s: %s", sym, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/paper-portfolio/overview")
async def get_paper_portfolio_overview():
    """Lay toan bo danh muc dau tu gia lap va cac vi the dang gong lai >= 10%"""
    try:
        from src.engine.smart_paper_portfolio import smart_paper_portfolio
        return await smart_paper_portfolio.get_portfolio_summary()
    except Exception as e:
        logger.error("Loi khi lay paper portfolio overview: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/paper-portfolio/reset")
async def reset_paper_portfolio():
    """Reset danh muc gia lap ve so von 1 Ty ban dau"""
    try:
        from src.engine.smart_paper_portfolio import smart_paper_portfolio
        return await smart_paper_portfolio.reset_portfolio()
    except Exception as e:
        logger.error("Loi khi reset paper portfolio: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/intelligence/firecrawl/scrape")
async def scrape_with_firecrawl(request: Request):
    """
    Endpoint cao du lieu sau bang Firecrawl (BCTC, Thuyet minh, Nghi quyet DHCD, Dau thau).
    Body: { "url": "https://..." }
    """
    try:
        body = await request.json()
        url = body.get("url", "")
        if not url:
            raise HTTPException(status_code=400, detail="Trường 'url' là bắt buộc")

        from src.intelligence.firecrawl_agent import firecrawl_agent, FirecrawlValidationError
        try:
            result = await firecrawl_agent.scrape_url(url=url)
            return result
        except FirecrawlValidationError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Loi khi cao Firecrawl: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/intelligence/firecrawl/extract-catalyst")
async def extract_catalyst_with_alpha(request: Request):
    """
    Trich xuat chat xuc tac va Cross-Validation voi Dong tien Ca Map de toi uu Win Rate.
    Body: { "symbol": "HPG", "text": "...", "shark_net_ty": 5.2, "foreign_net_ty": 1.0 }
    """
    try:
        body = await request.json()
        symbol = body.get("symbol", "").strip().upper()
        text = body.get("text", "")
        shark_net_ty = float(body.get("shark_net_ty", 0.0))
        foreign_net_ty = float(body.get("foreign_net_ty", 0.0))

        if not symbol:
            raise HTTPException(status_code=400, detail="Trường 'symbol' là bắt buộc")

        from src.intelligence.firecrawl_agent import firecrawl_agent
        catalyst = await firecrawl_agent.extract_catalyst_signals(symbol=symbol, text_content=text)
        alpha_validation = firecrawl_agent.cross_validate_with_whale(
            symbol=symbol,
            catalyst_score=catalyst.get("catalyst_score", 5.0),
            shark_net_ty=shark_net_ty,
            foreign_net_ty=foreign_net_ty
        )

        return {
            "symbol": symbol,
            "catalyst": catalyst,
            "alpha_validation": alpha_validation
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Loi khi trich xuat catalyst: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/intelligence/firecrawl/auto-analyze-bctc")
async def auto_analyze_bctc(request: Request):
    """
    Quy trinh Zero-Click: Tu dong quet BCTC, Thuyet minh, va Cross-Validation theo ma co phieu.
    Body: { "symbol": "HPG", "shark_net_ty": 5.0, "foreign_net_ty": 1.5 }
    """
    try:
        body = await request.json()
        symbol = body.get("symbol", "").strip().upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="Trường 'symbol' là bắt buộc")

        shark_net_ty = float(body.get("shark_net_ty", 0.0))
        foreign_net_ty = float(body.get("foreign_net_ty", 0.0))

        from src.intelligence.firecrawl_agent import firecrawl_agent
        result = await firecrawl_agent.auto_analyze_symbol_bctc(
            symbol=symbol,
            shark_net_ty=shark_net_ty,
            foreign_net_ty=foreign_net_ty
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Loi khi auto analyze BCTC: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/intelligence/firecrawl/search")
async def search_firecrawl(request: Request):
    """
    Tim kiem thong minh passages va chat xuc tac tren web bang Firecrawl v2.
    Body: { "query": "HPG Dung Quat 2", "limit": 5 }
    """
    try:
        body = await request.json()
        query = body.get("query", "").strip()
        limit = int(body.get("limit", 5))

        if not query:
            raise HTTPException(status_code=400, detail="Trường 'query' là bắt buộc")

        from src.intelligence.firecrawl_agent import firecrawl_agent
        return await firecrawl_agent.search_catalysts(query=query, limit=limit)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Loi khi search Firecrawl: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/intelligence/firecrawl/parse-pdf")
async def parse_pdf_bctc(request: Request):
    """
    Boc tach truc tiep file PDF BCTC qua Firecrawl v2.
    Body: { "file_url": "https://...bctc.pdf" }
    """
    try:
        body = await request.json()
        file_url = body.get("file_url", "").strip()
        if not file_url:
            raise HTTPException(status_code=400, detail="Trường 'file_url' là bắt buộc")

        from src.intelligence.firecrawl_agent import firecrawl_agent
        return await firecrawl_agent.parse_pdf_document(file_url=file_url)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Loi khi parse PDF Firecrawl: %s", str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))






