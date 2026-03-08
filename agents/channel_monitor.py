"""
① 채널 모니터 에이전트
10분 주기로 채널 DB의 활성 채널을 스크래핑하여
새 영상을 영상 큐 DB에 등록합니다.
AI 사용: ❌ (순수 스크래핑)
"""
import logging
import asyncio

from db.channels import get_active_channels
from db.video_queue import video_exists, register_video, get_subtitle_unchecked_videos, update_subtitle_status
from services.youtube import get_latest_videos, parse_upload_date
from services.transcript import check_subtitle_available

logger = logging.getLogger(__name__)


async def run() -> dict:
    """
    채널 모니터 에이전트 메인 루프

    Returns:
        실행 결과 요약 dict
    """
    logger.info("═══ 채널 모니터 에이전트 시작 ═══")

    channels = await get_active_channels()
    logger.info(f"활성 채널 {len(channels)}개 조회")

    new_count = 0
    skip_count = 0
    error_count = 0

    for idx, channel in enumerate(channels):
        try:
            logger.info(
                f"[{idx + 1}/{len(channels)}] 채널 스크래핑: "
                f"{channel['name']} (키워드: {channel['keyword']})"
            )

            videos = await get_latest_videos(
                channel["url"], keyword=channel["keyword"]
            )

            if not videos:
                logger.info(f"  → 매칭 영상 없음")
                continue

            # ⚠️ 주의: youtube-transcript-api는 너무 빠른 병렬 요청 시 429 에러 발생 가능
            # 따라서 Semaphore를 1로 두어 자막 확인 시 일정 간격을 두도록 함
            sem = asyncio.Semaphore(1)

            async def process_video(video: dict) -> dict:
                async with sem:
                    video_id = video.get("video_id", "")
                    if not video_id:
                        return {"status": "invalid"}

                    # 중복 체크
                    if await video_exists(video_id):
                        return {"status": "skipped"}

                    # 자막 존재 여부 빠른 체크 (youtube-transcript-api 네트워크 I/O)
                    subtitle_status = await check_subtitle_available(video_id)
                    await asyncio.sleep(1.5)  # 429 Too Many Requests 방지용 딜레이

                    # 업로드 날짜 변환
                    upload_dt = parse_upload_date(video.get("upload_date", ""))

                    # 영상 큐 DB에 등록
                    result = await register_video({
                        "title": video["title"],
                        "video_id": video_id,
                        "channel_name": channel["name"],
                        "upload_date": upload_dt.isoformat(),
                        "video_length": video.get("video_length", "Unknown"),
                        "url": video["url"],
                        "subtitle_status": subtitle_status,
                    })

                    if result:
                        return {"status": "registered", "title": video["title"], "subtitle": subtitle_status}
                    else:
                        return {"status": "error"}

            tasks = [process_video(v) for v in videos]
            results = await asyncio.gather(*tasks)

            for res in results:
                if res["status"] == "skipped":
                    skip_count += 1
                elif res["status"] == "registered":
                    new_count += 1
                    logger.info(f"  ✓ 신규 등록: {res['title']} (자막: {res['subtitle']})")
                elif res["status"] == "error":
                    error_count += 1

            # 채널 간 API 부하 분산
            if idx < len(channels) - 1:
                await asyncio.sleep(2)

        except Exception as e:
            error_count += 1
            logger.error(f"  ✗ 채널 처리 오류: {e}")
            if idx < len(channels) - 1:
                await asyncio.sleep(2)

    # 자막 미확인 영상 재확인
    recheck_count = await _recheck_subtitle_status()

    summary = {
        "channels_checked": len(channels),
        "new_videos": new_count,
        "skipped_duplicates": skip_count,
        "subtitle_rechecked": recheck_count,
        "errors": error_count,
    }
    logger.info(f"═══ 채널 모니터 완료: {summary} ═══")
    return summary


async def _recheck_subtitle_status() -> int:
    """자막상태=미확인인 영상들을 재확인합니다."""
    unchecked = await get_subtitle_unchecked_videos()
    if not unchecked:
        return 0

    logger.info(f"자막 재확인 대상: {len(unchecked)}건")
    updated = 0

    for video in unchecked:
        video_id = video.get("video_id", "")
        if not video_id:
            continue

        new_status = await check_subtitle_available(video_id)
        if new_status != "미확인":
            await update_subtitle_status(video["page_id"], new_status)
            updated += 1
            logger.info(f"  자막상태 업데이트: {video['title']} → {new_status}")

    return updated
