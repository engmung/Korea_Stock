"""
④ 정규화 에이전트
배치 실행: "정규화_상태=미처리"가 NORMALIZE_BATCH_SIZE개 이상 쌓이거나,
마지막 실행 후 NORMALIZE_INTERVAL_MINUTES분 경과 시 동작.
기존 정규화 완료 목록과 비교하여 종목명을 통일합니다.
AI 사용: ✅
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config.settings import get_settings
from config.prompts import NORMALIZE_SYSTEM_PROMPT, NORMALIZE_USER_PROMPT_TEMPLATE
from db.stock_opinions import get_unprocessed_opinions, get_normalized_names, update_normalization
from services.llm import get_llm_service

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

# 마지막 실행 시간 추적
_last_run_time: datetime | None = None


async def run() -> dict:
    """
    정규화 에이전트 메인 루프.
    트리거 조건을 내부에서 체크합니다.

    Returns:
        실행 결과 요약 dict
    """
    global _last_run_time
    s = get_settings()

    # 미처리 레코드 확인
    unprocessed = await get_unprocessed_opinions()
    count = len(unprocessed)

    # 트리거 조건 체크
    now = datetime.now(KST)
    time_trigger = False
    if _last_run_time is not None:
        elapsed = (now - _last_run_time).total_seconds() / 60
        time_trigger = elapsed >= s.scheduler.normalize_interval_minutes
    else:
        # 첫 실행
        time_trigger = count > 0

    batch_trigger = count >= s.scheduler.normalize_batch_size

    if not batch_trigger and not time_trigger:
        logger.info(
            f"정규화 에이전트: 트리거 미충족 "
            f"(미처리 {count}개, 배치 기준 {s.scheduler.normalize_batch_size}개)"
        )
        return {"status": "skipped", "unprocessed": count}

    if count == 0:
        logger.info("정규화 에이전트: 미처리 레코드 없음")
        _last_run_time = now
        return {"status": "done", "total": 0}

    logger.info(f"═══ 정규화 에이전트 시작 (미처리 {count}건) ═══")
    _last_run_time = now

    # 기존 정규화 완료 목록 가져오기
    existing_names = await get_normalized_names()
    logger.info(f"기존 정규화 완료 종목: {len(existing_names)}개")

    # 원본 종목명 추출 (중복 제거로 LLM 프롬프트 효율화)
    target_names = list(set([op["original_name"] for op in unprocessed if op["original_name"]]))

    if not target_names:
        return {"status": "done", "total": 0}

    # LLM으로 정규화
    llm = get_llm_service()

    user_prompt = NORMALIZE_USER_PROMPT_TEMPLATE.format(
        existing_names="\n".join(f"- {n}" for n in existing_names) if existing_names else "(없음 — 첫 실행)",
        target_names="\n".join(f"- {n}" for n in target_names),
    )

    result = await llm.generate_json(NORMALIZE_SYSTEM_PROMPT, user_prompt)
    results_list = result.get("results", [])

    # 결과 매핑 (원본명 → 정규화 결과)
    result_map = {}
    for r in results_list:
        orig = r.get("original_name", "")
        if orig:
            result_map[orig] = r

    # DB 업데이트
    completed = 0
    manual_check = 0

    for opinion in unprocessed:
        orig_name = opinion["original_name"]
        r = result_map.get(orig_name)

        if r:
            normalized = r.get("normalized_name", orig_name)
            status = r.get("status", "완료")

            if status not in ("완료", "수동확인필요"):
                status = "완료"

            await update_normalization(opinion["page_id"], normalized, status)

            if status == "완료":
                completed += 1
            else:
                manual_check += 1

            logger.info(f"  {orig_name} → {normalized} ({status})")
        else:
            # LLM 응답에 없는 경우 → 원본 그대로, 완료 처리
            await update_normalization(opinion["page_id"], orig_name, "완료")
            completed += 1
            logger.info(f"  {orig_name} → {orig_name} (신규, 자동 완료)")

    summary = {
        "status": "done",
        "total": count,
        "completed": completed,
        "manual_check": manual_check,
    }
    logger.info(f"═══ 정규화 완료: {summary} ═══")
    return summary
