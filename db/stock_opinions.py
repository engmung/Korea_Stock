"""
종목의견 DB CRUD
SQLite 데이터베이스에서 종목별 의견 레코드 생성, 정규화 상태 관리를 처리합니다.
"""
import logging
import uuid
from typing import Dict, List, Any, Optional
from sqlalchemy.future import select
from sqlalchemy import update

from db.database import get_session_maker, StockOpinion

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 변환 헬퍼
# ──────────────────────────────────────────────
def _to_dict(so: StockOpinion) -> Dict[str, Any]:
    return {
        "page_id": so.page_id,
        "original_name": so.original_name,
        "normalized_name": so.normalized_name,
        "normalization_status": so.normalization_status,
        "opinion_type": so.opinion_type,
        "recommendation_date": so.upload_date,
        "recommender": so.recommender,
        "reason_summary": so.reason_summary,
        "video_id": so.video_id,
    }


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len] if len(text) > max_len else text


# ──────────────────────────────────────────────
# 생성
# ──────────────────────────────────────────────
async def create_stock_opinion(opinion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    종목의견 DB에 새 레코드를 생성합니다.

    Args:
        opinion: 종목 의견 정보
            - name: 원본 종목명
            - opinion_type: 추천 | 주의
            - recommender: 추천인 (전문가명 또는 프로그램명)
            - reason_summary: 근거 요약
            - upload_date: 추천일자 (영상 업로드 날짜)
            - video_id: 원본 영상 ID
    """
    session_maker = get_session_maker()
    fake_page_id = f"so_{uuid.uuid4().hex[:8]}_{opinion.get('video_id', '')}"
    
    async with session_maker() as session:
        new_opinion = StockOpinion(
            page_id=fake_page_id,
            original_name=opinion.get("name", ""),
            normalized_name="",
            normalization_status="미처리",
            opinion_type=opinion.get("opinion_type", "추천"),
            recommender=opinion.get("recommender", ""),
            reason_summary=_truncate(opinion.get("reason_summary", ""), 2000),
            upload_date=opinion.get("upload_date", ""),
            video_id=opinion.get("video_id", "")
        )
        session.add(new_opinion)
        await session.commit()
        await session.refresh(new_opinion)
        
        logger.info(f"종목의견 생성: {opinion.get('name', '')} ({opinion.get('opinion_type', '')})")
        return _to_dict(new_opinion)


async def create_stock_opinions_batch(
    opinions: List[Dict[str, Any]],
) -> int:
    """여러 종목의견을 일괄 생성합니다. 생성 성공 수를 반환합니다."""
    # Notion API와 달리 로컬 DB는 빠르므로 하나씩 넣어도 무방
    success_count = 0
    for opinion in opinions:
        result = await create_stock_opinion(opinion)
        if result:
            success_count += 1
    logger.info(f"종목의견 배치 생성: {success_count}/{len(opinions)} 성공")
    return success_count


# ──────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────
async def get_unprocessed_opinions() -> List[Dict[str, Any]]:
    """정규화_상태=미처리인 종목의견을 조회합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(StockOpinion).where(StockOpinion.normalization_status == "미처리")
        result = await session.execute(stmt)
        return [_to_dict(so) for so in result.scalars().all()]


async def get_normalized_names() -> List[str]:
    """정규화 완료된 종목명 목록을 반환합니다."""
    session_maker = get_session_maker()
    names = set()
    async with session_maker() as session:
        stmt = select(StockOpinion.normalized_name).where(
            StockOpinion.normalization_status == "완료"
        )
        result = await session.execute(stmt)
        for name in result.scalars().all():
            if name:
                names.add(name)
    return sorted(list(names))


async def get_all_opinions() -> List[Dict[str, Any]]:
    """모든 종목의견을 조회합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        # 최신 업로드일자 기준으로 정렬
        stmt = select(StockOpinion).order_by(StockOpinion.upload_date.desc())
        result = await session.execute(stmt)
        return [_to_dict(so) for so in result.scalars().all()]


# ──────────────────────────────────────────────
# 업데이트 (정규화)
# ──────────────────────────────────────────────
async def update_normalization(
    page_id: str,
    normalized_name: str,
    status: str,  # "완료" | "수동확인필요"
) -> bool:
    """종목의견의 정규화 상태를 업데이트합니다."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = update(StockOpinion).where(StockOpinion.page_id == page_id).values(
            normalized_name=normalized_name,
            normalization_status=status
        )
        await session.execute(stmt)
        await session.commit()
    return True
