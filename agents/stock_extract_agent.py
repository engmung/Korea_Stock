"""
③ 종목 추출 에이전트
"분석필요=필요 & 자막상태=Y & 분석완료=False"인 영상 대상.
자막 → LLM 분석 → 종목의견 DB 직행 + 영상 요약을 영상 큐 DB에 저장.
AI 사용: ✅ (Gemini Structured Output)
"""
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from config.prompts import EXTRACT_SYSTEM_PROMPT
from db.video_queue import get_ready_for_report_videos, mark_analysis_done, update_summary
from db.stock_opinions import create_stock_opinions_batch
from services.llm import get_llm_service
from services.transcript import get_transcript

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Pydantic 스키마 (Gemini Structured Output용)
# ──────────────────────────────────────────────
class StockOpinion(BaseModel):
    """개별 종목 의견"""
    name: str = Field(description="종목명 (예: 삼성전자)")
    opinion_type: str = Field(description="추천, 주의 중 하나")
    recommender: str = Field(description="전문가명 또는 프로그램명")
    reason_summary: str = Field(description="근거 요약 1~2문장")


class ExtractionResult(BaseModel):
    """전체 추출 결과"""
    summary: str = Field(description="영상 전체 내용 요약 1~2줄")
    stocks: List[StockOpinion] = Field(description="추출된 종목 의견 리스트. 종목이 없으면 빈 리스트.")


async def run() -> dict:
    """
    종목 추출 에이전트 메인 루프

    Returns:
        실행 결과 요약 dict
    """
    logger.info("═══ 종목 추출 에이전트 시작 ═══")

    videos = await get_ready_for_report_videos()
    logger.info(f"추출 대상: {len(videos)}건")

    if not videos:
        return {"status": "done", "total": 0, "success": 0, "failed": 0}

    llm = get_llm_service()
    success = 0
    failed = 0

    for video in videos:
        try:
            logger.info(f"종목 추출 중: {video['title']}")

            # 1. 자막 전체 가져오기
            transcript = await get_transcript(video["video_id"])
            if not transcript:
                logger.warning(f"  → 자막 가져오기 실패: {video['title']}")
                failed += 1
                continue

            # 2. LLM으로 종목 추출 + 요약 (Structured Output)
            user_prompt = f"""## 영상 정보
- 제목: {video['title']}
- 채널: {video.get('channel_name', '')}

## 스크립트 내용
{transcript}

위 스크립트를 분석하여 종목 의견과 영상 요약을 추출해주세요."""

            result: ExtractionResult = await llm.generate_structured(
                EXTRACT_SYSTEM_PROMPT,
                user_prompt,
                ExtractionResult,
            )

            # 3. 영상 요약을 영상 큐 DB에 저장
            if result.summary:
                await update_summary(video["page_id"], result.summary)
                logger.info(f"  요약 저장: {result.summary[:50]}...")

            # 4. 종목의견 DB에 각 종목별 레코드 생성 (중복 제거 로직 추가)
            if result.stocks:
                unique_opinions = {}
                for stock in result.stocks:
                    if stock.name not in unique_opinions:
                        unique_opinions[stock.name] = {
                            "name": stock.name,
                            "opinion_type": stock.opinion_type,
                            "recommender": stock.recommender or video.get("channel_name", ""),
                            "reason_summary": stock.reason_summary,
                            "upload_date": video.get("upload_date", ""),
                            "video_id": video["video_id"],
                        }
                opinions = list(unique_opinions.values())
                created = await create_stock_opinions_batch(opinions)
                logger.info(f"  종목의견 {created}/{len(opinions)}개 생성")

            # 5. 영상 큐의 분석완료 = True
            await mark_analysis_done(video["page_id"])
            success += 1
            logger.info(f"  ✓ 추출 완료: {video['title']} (종목 {len(result.stocks)}개)")

        except Exception as e:
            logger.error(f"  ✗ 추출 오류: {video['title']} — {e}")
            failed += 1

    summary = {
        "status": "done",
        "total": len(videos),
        "success": success,
        "failed": failed,
    }
    logger.info(f"═══ 종목 추출 완료: {summary} ═══")
    return summary
