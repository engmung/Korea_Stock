"""
투자 의사결정 지원 시스템 — FastAPI 서버 + 스케줄러
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config.settings import get_settings
from agents import channel_monitor, filter_agent, stock_extract_agent, normalize_agent
from db.channels import get_all_channels
from db.video_queue import get_all_videos
from db.stock_opinions import get_all_opinions, get_visualization_data
from db.database import init_db

# ──────────────────────────────────────────────
# 로깅 설정 (콘솔 + 파일)
# ──────────────────────────────────────────────
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"

# 콘솔 핸들러
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

# 파일 핸들러 (매일 자정 로테이션, 7일 보관)
file_handler = TimedRotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"),
    when="midnight",
    interval=1,
    backupCount=7,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 스케줄러
# ──────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


def setup_scheduler():
    """설정 기반으로 4개 에이전트를 스케줄러에 등록합니다."""
    s = get_settings()

    # ① 채널 모니터 — 10분 주기
    scheduler.add_job(
        channel_monitor.run,
        IntervalTrigger(minutes=s.scheduler.monitor_interval_minutes),
        id="channel_monitor",
        replace_existing=True,
    )

    # ② 필터링 에이전트 — 매시 정각, (시간대 체크는 에이전트 내부에서)
    scheduler.add_job(
        filter_agent.run,
        IntervalTrigger(minutes=s.scheduler.filter_interval_minutes),
        id="filter_agent",
        replace_existing=True,
    )

    # ③ 종목 추출 에이전트 — 5분 주기 (필터 완료 후 바로 실행되도록)
    scheduler.add_job(
        stock_extract_agent.run,
        IntervalTrigger(minutes=s.scheduler.report_interval_minutes),
        id="stock_extract_agent",
        replace_existing=True,
    )

    # ④ 정규화 에이전트 — 10분 주기 (트리거 조건은 내부 체크)
    scheduler.add_job(
        normalize_agent.run,
        IntervalTrigger(minutes=10),
        id="normalize_agent",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("스케줄러 시작 완료")
    logger.info(f"  채널 모니터: {s.scheduler.monitor_interval_minutes}분 주기")
    logger.info(f"  필터링: {s.scheduler.filter_interval_minutes}분 주기 ({s.scheduler.filter_active_hour_start}~{s.scheduler.filter_active_hour_end}시)")
    logger.info(f"  종목 추출: {s.scheduler.report_interval_minutes}분 주기")
    logger.info(f"  정규화: 10분 주기 (배치 {s.scheduler.normalize_batch_size}개 또는 {s.scheduler.normalize_interval_minutes}분)")


# ──────────────────────────────────────────────
# FastAPI 앱
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    await init_db(s.db.url)
    setup_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(title="투자 의사결정 지원 시스템", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# 조회 엔드포인트
# ──────────────────────────────────────────────
# 백엔드 API 루트는 /api 로 리다이렉트하거나 상태 표시
@app.get("/api/status")
async def root():
    s = get_settings()
    return {
        "message": "투자 의사결정 지원 시스템 API",
        "llm_provider": s.llm.provider,
        "llm_model": s.llm.model,
    }

@app.get("/api/visualization")
async def api_visualization(
    days: int = Query(3, description="최근 X일 데이터 조회"),
    interval_hours: int = Query(12, description="타임라인 뷰 용 시간대 버킷 (단위: 시간)")
):
    """3D 시각화용 통합 데이터 조회 API"""
    data = await get_visualization_data(days=days, interval_hours=interval_hours)
    return {"status": "success", "data": data}


@app.get("/channels")
async def list_channels():
    channels = await get_all_channels()
    return {"status": "success", "channels": channels, "total": len(channels)}


@app.get("/queue")
async def list_queue():
    videos = await get_all_videos()
    return {"status": "success", "videos": videos, "total": len(videos)}



@app.get("/opinions")
async def list_opinions():
    opinions = await get_all_opinions()
    return {"status": "success", "opinions": opinions, "total": len(opinions)}

# 프론트엔드 서빙 (루트 경로에서 정적 HTML 로드)
# 디렉토리가 없으면 에러가 나므로 생성해둡니다.
os.makedirs(os.path.join(os.path.dirname(__file__), "static"), exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")


@app.get("/config")
async def show_config():
    s = get_settings()
    return {
        "llm_provider": s.llm.provider,
        "llm_model": s.llm.model,
        "monitor_interval": s.scheduler.monitor_interval_minutes,
        "filter_interval": s.scheduler.filter_interval_minutes,
        "filter_hours": f"{s.scheduler.filter_active_hour_start}~{s.scheduler.filter_active_hour_end}",
        "report_interval": s.scheduler.report_interval_minutes,
        "normalize_batch_size": s.scheduler.normalize_batch_size,
        "normalize_interval": s.scheduler.normalize_interval_minutes,
    }


# ──────────────────────────────────────────────
# 수동 실행 엔드포인트
# ──────────────────────────────────────────────
@app.post("/run/monitor")
async def run_monitor(background_tasks: BackgroundTasks):
    background_tasks.add_task(channel_monitor.run)
    return {"status": "started", "agent": "channel_monitor"}


@app.post("/run/filter")
async def run_filter(background_tasks: BackgroundTasks):
    background_tasks.add_task(filter_agent.run)
    return {"status": "started", "agent": "filter_agent"}


@app.post("/run/extract")
async def run_extract(background_tasks: BackgroundTasks):
    background_tasks.add_task(stock_extract_agent.run)
    return {"status": "started", "agent": "stock_extract_agent"}


@app.post("/run/normalize")
async def run_normalize(background_tasks: BackgroundTasks):
    background_tasks.add_task(normalize_agent.run)
    return {"status": "started", "agent": "normalize_agent"}


# ──────────────────────────────────────────────
# 직접 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=True)