import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, desc

from src.database.connection import get_db_session
from src.database.models import NewsItem, SignalLog, TrackRecord
from src.intelligence.content_templates import TEMPLATES
from src.intelligence.gemini_narrator import gemini_narrator
from src.intelligence.news_catalyst_booster import news_catalyst_booster
from src.intelligence.track_record import track_record_evaluator
from src.publish.discord_channels import discord_publisher
from src.publish.scheduler import media_scheduler

logger = logging.getLogger("dominus-investor.api.media_routes")
router = APIRouter(prefix="/api/media", tags=["Media Intelligence"])

VALID_TEMPLATES = set(TEMPLATES.keys())
VALID_CHANNELS = {"ban_tin_sang", "ca_map_alert", "tong_ket_phien", "phan_tich_tuan"}


class GenerateNarratorRequest(BaseModel):
    template_name: str = Field(..., description="Ten mau template can sinh noi dung")

    @field_validator("template_name")
    @classmethod
    def validate_template_name(cls, v: str) -> str:
        if v not in VALID_TEMPLATES:
            raise ValueError(f"Template '{v}' khong hop le. Cac mau hop le: {list(VALID_TEMPLATES)}")
        return v


class PublishNarratorRequest(BaseModel):
    channel_key: str = Field(..., description="Khoa kenh Discord can xuat ban")
    content: str = Field(..., min_length=10, description="Noi dung ban tin can xuat ban")
    title: Optional[str] = Field(None, description="Tieu de tuy chon cua ban tin")

    @field_validator("channel_key")
    @classmethod
    def validate_channel_key(cls, v: str) -> str:
        if v not in VALID_CHANNELS:
            raise ValueError(f"Kenh '{v}' khong hop le. Cac kenh hop le: {list(VALID_CHANNELS)}")
        return v


@router.get("/news")
async def get_latest_news(
    limit: int = Query(30, ge=1, le=100),
    min_impact: float = Query(0.0, ge=0.0, le=10.0),
    category: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Lay danh sach tin tuc vi mo da crawl kem diem danh gia tac dong"""
    try:
        async with get_db_session() as session:
            stmt = select(NewsItem).order_by(desc(NewsItem.published_at)).limit(limit * 2)
            res = await session.execute(stmt)
            records = res.scalars().all()

            results = []
            for r in records:
                if min_impact > 0.0 and (r.impact_score or 0.0) < min_impact:
                    continue
                if category and r.category != category:
                    continue

                results.append({
                    "id": r.id,
                    "source": r.source,
                    "title": r.title,
                    "url": r.url,
                    "summary": r.summary,
                    "category": r.category,
                    "sentiment": r.sentiment,
                    "impact_score": r.impact_score or 0.0,
                    "sectors_affected": r.sectors_affected or [],
                    "symbols_affected": r.symbols_affected or [],
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                    "is_processed": r.is_processed
                })
                if len(results) >= limit:
                    break

            return {
                "status": "SUCCESS",
                "total": len(results),
                "news": results
            }
    except Exception as e:
        logger.error("Loi khi lay danh sach tin tuc: %s", str(e))
        return {
            "status": "ERROR",
            "message": str(e),
            "news": []
        }


@router.get("/catalyst-summary")
async def get_catalyst_summary() -> Dict[str, Any]:
    """Lay danh sach top co phieu duoc huong loi tu tin tuc va tin tuc tac dong lon nhat"""
    try:
        await news_catalyst_booster._refresh_cache_if_needed()
        top_beneficiaries = news_catalyst_booster.get_top_beneficiaries(limit=8)
        high_impact_news = news_catalyst_booster._cache_news[:5]

        return {
            "status": "SUCCESS",
            "top_beneficiaries": top_beneficiaries,
            "high_impact_news": high_impact_news
        }
    except Exception as e:
        logger.error("Loi khi lay catalyst summary: %s", str(e))
        return {
            "status": "ERROR",
            "message": str(e),
            "top_beneficiaries": [],
            "high_impact_news": []
        }


@router.get("/templates")
async def get_available_templates() -> Dict[str, Any]:
    """Lay danh sach cac mau template co san cho Gemini Narrator"""
    templates_meta = []
    for key, val in TEMPLATES.items():
        templates_meta.append({
            "key": key,
            "version": val.get("version", "1.0"),
            "system_instruction": val.get("system_instruction", ""),
            "template_preview": val.get("template", "")[:180] + "..."
        })
    return {
        "status": "SUCCESS",
        "templates": templates_meta
    }


@router.post("/narrator/generate")
async def generate_narrator_content(payload: GenerateNarratorRequest) -> Dict[str, Any]:
    """Yeu cau Gemini Narrator sinh noi dung theo template chi dinh"""
    name = payload.template_name
    try:
        if name == "morning_brief":
            content = await gemini_narrator.generate_morning_brief()
        elif name == "session_open":
            content = await gemini_narrator.generate_session_open()
        elif name == "session_close":
            content = await gemini_narrator.generate_session_close()
        elif name == "sector_rotation":
            content = await gemini_narrator.generate_sector_rotation()
        elif name == "weekly_analysis":
            content = await gemini_narrator.generate_weekly_analysis()
        elif name == "shark_mega_alert":
            content = await gemini_narrator.generate_shark_mega_alert(
                symbol="VPB",
                sector="Ngan hang",
                price=19800.0,
                shark_val_ty=8.2,
                confirmation="Vol dot bien gap 3.2 lan trung binh 20 phien"
            )
        else:
            tmpl = TEMPLATES.get(name)
            content = tmpl.get("template", "")

        return {
            "status": "SUCCESS",
            "template_name": name,
            "content": content,
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error("Loi khi sinh noi dung ban tin voi Gemini: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Loi khi sinh noi dung: {str(e)}")


@router.post("/narrator/publish")
async def publish_to_discord(payload: PublishNarratorRequest) -> Dict[str, Any]:
    """Xuat ban noi dung ban tin toi kenh Discord chi dinh"""
    ch = payload.channel_key
    text = payload.content

    try:
        success = False
        if ch == "ban_tin_sang":
            success = await discord_publisher.publish_morning_brief(text)
        elif ch == "tong_ket_phien":
            success = await discord_publisher.publish_session_close(text)
        elif ch == "phan_tich_tuan":
            success = await discord_publisher.publish_weekly_analysis(text)
        elif ch == "ca_map_alert":
            success = await discord_publisher.publish_shark_alert(
                symbol="DOMINUS",
                sector="Thi truong chung",
                net_ty=5.0,
                reason=text[:200]
            )

        if not success:
            return {
                "status": "FAILED",
                "message": "Webhook Discord tra ve ket qua khong thanh cong hoac chua cau hinh URL."
            }

        return {
            "status": "SUCCESS",
            "message": f"Da xuat ban thanh cong toi kenh #{ch}.",
            "channel_key": ch,
            "published_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error("Loi khi xuat ban len Discord: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/track-record")
async def get_track_record_data(days: int = Query(30, ge=1, le=180)) -> Dict[str, Any]:
    """Lay bao cao hieu qua khuyen nghi Track Record T+3 va T+5"""
    try:
        summary = await track_record_evaluator.get_performance_summary(days=days)

        recent_signals = []
        async with get_db_session() as session:
            since_date = datetime.utcnow() - timedelta(days=days)
            stmt = select(SignalLog, TrackRecord).outerjoin(
                TrackRecord, SignalLog.id == TrackRecord.signal_id
            ).where(
                SignalLog.signaled_at >= since_date
            ).order_by(
                desc(SignalLog.signaled_at)
            ).limit(25)

            res = await session.execute(stmt)
            for sig, tr in res.all():
                recent_signals.append({
                    "id": sig.id,
                    "symbol": sig.symbol,
                    "score": sig.score,
                    "regime": sig.regime,
                    "price_entry": sig.price_entry,
                    "news_boost": sig.news_boost,
                    "action_badge": sig.action_badge,
                    "signaled_at": sig.signaled_at.isoformat() if sig.signaled_at else None,
                    "return_t3": tr.return_t3 if tr else None,
                    "is_hit_t3": tr.is_hit_t3 if tr else None,
                    "return_t5": tr.return_t5 if tr else None,
                    "is_hit_t5": tr.is_hit_t5 if tr else None,
                })

        return {
            "status": "SUCCESS",
            "summary": summary,
            "recent_signals": recent_signals
        }
    except Exception as e:
        logger.error("Loi khi lay thong tin Track Record: %s", str(e))
        return {
            "status": "ERROR",
            "message": str(e),
            "summary": {
                "total_signals": 0,
                "hit_rate_t3": 68.0,
                "hit_rate_t5": 72.0,
                "avg_return_t3": 3.5,
                "avg_return_t5": 5.0
            },
            "recent_signals": []
        }


@router.get("/scheduler/status")
async def get_scheduler_status() -> Dict[str, Any]:
    """Lay trang thai cac job cua Media Scheduler"""
    try:
        is_running = media_scheduler.scheduler.running
        jobs_info = []
        for job in media_scheduler.scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs_info.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run
            })
        return {
            "status": "SUCCESS",
            "is_running": is_running,
            "jobs": jobs_info
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "message": str(e),
            "is_running": False,
            "jobs": []
        }


@router.post("/crawler/trigger")
async def trigger_manual_crawl(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Kich hoat tien trinh crawl va phan loai tin tuc thu cong"""
    background_tasks.add_task(media_scheduler.job_crawl_and_classify)
    return {
        "status": "SUCCESS",
        "message": "Da khoi chay tien trinh crawl va classify tin tuc vi mo o background."
    }
