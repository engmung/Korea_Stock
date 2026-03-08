"""
② 필터링 에이전트
1시간 주기 (07~20시), 영상 큐 DB에서 "분석필요=미정"인 영상을 대상으로
AI가 제목만으로 분석 가치를 일괄 판단합니다.
AI 사용: ✅ (Gemini Structured Output)
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List
from pydantic import BaseModel, Field

from config.settings import get_settings
from db.video_queue import get_pending_filter_videos, update_analysis_needed
from services.llm import get_llm_service

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


# ──────────────────────────────────────────────
# Pydantic 스키마 (Gemini Structured Output용)
# ──────────────────────────────────────────────
class VideoDecision(BaseModel):
    """개별 영상에 대한 필터링 결과"""
    video_id: str = Field(description="영상 ID")
    result: str = Field(description="필요 또는 불필요")
    reason: str = Field(description="판단 근거 한 줄")


class FilterBatchResult(BaseModel):
    """전체 배치 필터링 결과"""
    decisions: List[VideoDecision] = Field(description="각 영상에 대한 판단 결과 리스트")


# ──────────────────────────────────────────────
# 프롬프트 (배치 처리용)
# ──────────────────────────────────────────────
FILTER_BATCH_SYSTEM_PROMPT = """\
당신은 한국 주식 투자 방송 콘텐츠 필터링 전문가입니다.
주어진 영상 목록의 제목만 보고, 각 영상이 "전문가의 개별 종목 분석" 콘텐츠인지 판단해주세요.

## 판단 기준

### "필요" (분석 가치 있음)
- 전문가가 개별 종목에 대해 매수/매도/관심 의견을 제시하는 콘텐츠
- 종목 추천, 종목 분석, 포트폴리오 제안 관련 콘텐츠
- 시장 전망 + 구체적 종목명이 언급되는 콘텐츠

### "불필요" (분석 가치 없음)
- 시청자 전화 상담 (개인 포트폴리오 상담)
- 경제/정치 일반 뉴스, 매크로 단순 전달
- 숏츠, 하이라이트 영상, 광고성 콘텐츠

위 "불필요" 기준에 명확히 해당하지 않으면 가급적 "필요"로 분류하여 분석 기회를 남겨주세요. 모든 영상에 대해 빠짐없이 판단해주세요.
"""


async def run() -> dict:
    """
    필터링 에이전트 메인 루프

    Returns:
        실행 결과 요약 dict
    """
    # 시간대 체크 (07~20시에만 동작)
    s = get_settings()
    now = datetime.now(KST)
    if not (s.scheduler.filter_active_hour_start <= now.hour < s.scheduler.filter_active_hour_end):
        logger.info(f"필터링 에이전트: 비활성 시간대 ({now.hour}시). 스킵.")
        return {"status": "skipped", "reason": "inactive_hours"}

    logger.info("═══ 필터링 에이전트 시작 ═══")

    videos = await get_pending_filter_videos()
    logger.info(f"필터링 대상: {len(videos)}건")

    if not videos:
        return {"status": "done", "total": 0, "needed": 0, "not_needed": 0}

    # 10분(600초) 이하 영상은 LLM 없이 바로 "불필요" 처리
    short_videos = []
    llm_candidates = []

    for video in videos:
        duration = _parse_video_length(video.get("video_length", ""))
        if 0 < duration <= 600:
            short_videos.append(video)
        else:
            llm_candidates.append(video)

    not_needed = 0
    needed = 0

    # 짧은 영상 일괄 처리
    for video in short_videos:
        await update_analysis_needed(video["page_id"], "불필요")
        not_needed += 1
        logger.info(f"  → 10분 이하, 불필요: {video['title']} ({video['video_length']})")

    # LLM 배치 처리
    if llm_candidates:
        llm = get_llm_service()

        # 영상 목록을 텍스트로 구성
        video_list_text = "\n".join(
            f"- ID: {v['video_id']} | 제목: {v['title']} | 채널: {v.get('channel_name', '')} | 길이: {v.get('video_length', 'Unknown')}"
            for v in llm_candidates
        )

        user_prompt = f"""다음 {len(llm_candidates)}개 영상의 제목을 보고 각각 "필요" 또는 "불필요"를 판단해주세요.

## 영상 목록
{video_list_text}
"""

        try:
            result: FilterBatchResult = await llm.generate_structured(
                FILTER_BATCH_SYSTEM_PROMPT,
                user_prompt,
                FilterBatchResult,
            )

            # 결과를 video_id 기준으로 매핑
            decision_map = {d.video_id: d for d in result.decisions}

            for video in llm_candidates:
                decision = decision_map.get(video["video_id"])
                if decision and decision.result == "필요":
                    await update_analysis_needed(video["page_id"], "필요")
                    needed += 1
                    logger.info(f"  ✓ 분석 필요: {video['title']} ({decision.reason})")
                else:
                    reason = decision.reason if decision else "LLM 응답 누락"
                    await update_analysis_needed(video["page_id"], "불필요")
                    not_needed += 1
                    logger.info(f"  ✗ 분석 불필요: {video['title']} ({reason})")

        except Exception as e:
            logger.error(f"  ✗ LLM 배치 필터링 오류: {e}")
            # 실패 시 모두 미정 유지
            return {
                "status": "error",
                "total": len(videos),
                "needed": needed,
                "not_needed": not_needed,
                "error": str(e),
            }

    summary = {
        "status": "done",
        "total": len(videos),
        "needed": needed,
        "not_needed": not_needed,
    }
    logger.info(f"═══ 필터링 완료: {summary} ═══")
    return summary


def _parse_video_length(length_str: str) -> int:
    """'MM:SS' 또는 'H:MM:SS' → 초"""
    try:
        parts = length_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0
    except (ValueError, AttributeError):
        return 0
