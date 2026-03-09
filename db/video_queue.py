"""
영상 큐 DB CRUD
SQLite 데이터베이스에서 영상 등록, 중복 체크, 상태 업데이트 등을 처리합니다.
"""
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.future import select
from sqlalchemy import or_, and_, update

from db.database import get_session_maker, VideoQueue

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 변환 헬퍼
# ──────────────────────────────────────────────
def _to_dict(vq: VideoQueue) -> Dict[str, Any]:
    return {
        "page_id": vq.page_id,
        "title": vq.title,
        "video_id": vq.video_id,
        "channel_name": vq.channel_name,
        "upload_date": vq.upload_date,
        "video_length": vq.video_length,
        "url": vq.url,
        "subtitle_status": vq.subtitle_status,
        "analysis_needed": vq.analysis_needed,
        "analysis_done": vq.analysis_done,
        "summary": vq.summary,
    }


# ──────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────
async def get_videos_by_status(
    analysis_needed: Optional[str] = None,
    subtitle_status: Optional[str] = None,
    analysis_done: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """조건에 맞는 영상 큐 목록을 조회합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(VideoQueue)
        if analysis_needed is not None:
            stmt = stmt.where(VideoQueue.analysis_needed == analysis_needed)
        if subtitle_status is not None:
            stmt = stmt.where(VideoQueue.subtitle_status == subtitle_status)
        if analysis_done is not None:
            stmt = stmt.where(VideoQueue.analysis_done == analysis_done)
            
        result = await session.execute(stmt)
        return [_to_dict(v) for v in result.scalars().all()]


async def get_all_videos() -> List[Dict[str, Any]]:
    """모든 영상 큐 항목을 조회합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        result = await session.execute(select(VideoQueue))
        return [_to_dict(v) for v in result.scalars().all()]


async def video_exists(video_id: str) -> bool:
    """영상 ID로 중복 여부를 확인합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(VideoQueue).where(VideoQueue.video_id == video_id)
        result = await session.execute(stmt)
        return result.scalars().first() is not None


async def get_subtitle_recheck_targets() -> List[Dict[str, Any]]:
    """자막상태가 '미확인'이거나, 분석필요가 '필요'인데 자막이 'N'인 영상을 조회합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(VideoQueue).where(
            or_(
                VideoQueue.subtitle_status == "미확인",
                and_(
                    VideoQueue.analysis_needed == "필요",
                    VideoQueue.subtitle_status == "N"
                )
            )
        )
        result = await session.execute(stmt)
        return [_to_dict(v) for v in result.scalars().all()]


async def get_pending_filter_videos() -> List[Dict[str, Any]]:
    """분석필요가 '미정'인 영상을 조회합니다."""
    return await get_videos_by_status(analysis_needed="미정")


async def get_ready_for_report_videos() -> List[Dict[str, Any]]:
    """분석필요=필요 & 자막상태=Y & 분석완료=False인 영상을 조회합니다."""
    return await get_videos_by_status(
        analysis_needed="필요", 
        subtitle_status="Y", 
        analysis_done=False
    )


# ──────────────────────────────────────────────
# 생성
# ──────────────────────────────────────────────
async def register_video(video_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """영상 큐 DB에 새 영상을 등록합니다."""
    session_maker = get_session_maker()
    
    # page_id는 Notion 시절 잔재이지만, 로컬 DB에서는 단순히 vq_{video_id} 형태로 할당해 고유성을 줍니다.
    fake_page_id = f"vq_{video_data.get('video_id', '')}"
    
    async with session_maker() as session:
        new_video = VideoQueue(
            page_id=fake_page_id,
            title=video_data.get("title", ""),
            video_id=video_data.get("video_id", ""),
            channel_name=video_data.get("channel_name", "기타"),
            upload_date=video_data.get("upload_date", ""),
            video_length=video_data.get("video_length", "Unknown"),
            url=video_data.get("url", ""),
            subtitle_status=video_data.get("subtitle_status", "미확인"),
            analysis_needed="미정",
            analysis_done=False,
            summary=""
        )
        session.add(new_video)
        await session.commit()
        await session.refresh(new_video)
        return _to_dict(new_video)


# ──────────────────────────────────────────────
# 업데이트
# ──────────────────────────────────────────────
async def update_subtitle_status(page_id: str, status: str) -> bool:
    """자막상태를 업데이트합니다. (Y / N / 미확인)"""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = update(VideoQueue).where(VideoQueue.page_id == page_id).values(subtitle_status=status)
        await session.execute(stmt)
        await session.commit()
    return True


async def update_analysis_needed(page_id: str, status: str) -> bool:
    """분석필요를 업데이트합니다. (미정 / 필요 / 불필요)"""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = update(VideoQueue).where(VideoQueue.page_id == page_id).values(analysis_needed=status)
        await session.execute(stmt)
        await session.commit()
    return True


async def mark_analysis_done(page_id: str) -> bool:
    """분석완료를 True로 변경합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = update(VideoQueue).where(VideoQueue.page_id == page_id).values(analysis_done=True)
        await session.execute(stmt)
        await session.commit()
    return True


async def update_summary(page_id: str, summary: str) -> bool:
    """영상 요약을 업데이트합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = update(VideoQueue).where(VideoQueue.page_id == page_id).values(summary=summary[:2000])
        await session.execute(stmt)
        await session.commit()
    return True
