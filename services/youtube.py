"""
YouTube 스크래핑 서비스
기존 youtube_scraper_utils.py + youtube_api_utils.py를 통합·정리합니다.
채널 페이지 스크래핑 → 최신 영상 목록 추출에 초점을 맞춥니다.
"""
import re
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

import httpx
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# ──────────────────────────────────────────────
# 공용 HTTP 헤더
# ──────────────────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ──────────────────────────────────────────────
# 메인 API: 채널에서 최신 영상 목록 가져오기
# ──────────────────────────────────────────────
async def get_latest_videos(
    channel_url: str,
    keyword: Optional[str] = None,
    max_retries: int = 3,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    채널 URL을 스크래핑하여 영상 목록을 가져옵니다.
    keyword가 주어지면 제목에 키워드가 포함된 영상만 반환합니다.

    Returns:
        영상 정보 리스트 [{title, url, video_id, upload_date, video_length,
                          duration_seconds, is_upcoming, is_live}, ...]
    """
    all_videos = []
    base_url = channel_url.rstrip("/")

    # URL에 이미 /videos나 /streams가 포함된 경우 해당 탭만 크롤링
    if any(p in base_url for p in ["/videos", "/streams"]):
        videos = await _scrape_channel_page(base_url, keyword, max_retries, timeout)
        if videos:
            all_videos.extend(videos)
    else:
        # 두 탭 모두 크롤링하여 합침
        for path_suffix in ["/videos", "/streams"]:
            target_url = f"{base_url}{path_suffix}"
            videos = await _scrape_channel_page(target_url, keyword, max_retries, timeout)
            if videos:
                all_videos.extend(videos)

    # 중복 제거 (video_id 기준) 및 필터링 (라이브 제외, 15분 미만 제외, 3일 이상 제외)
    unique_videos = {}
    now = datetime.now(KST)
    
    for v in all_videos:
        # 1. 라이브/예정 제외
        if v.get("is_live") or v.get("is_upcoming"):
            continue
            
        # 2. 15분(900초) 미만 제외
        duration = v.get("duration_seconds", 0)
        if duration < 900:
            continue
            
        # 3. 24시간 이전 영상 제외
        upload_dt = parse_upload_date(v.get("upload_date", ""))
        if (now - upload_dt).total_seconds() > 24 * 3600:
            continue
            
        unique_videos[v["video_id"]] = v
        
    # 정렬: 최신순 (스크래핑 순서를 유지, 라이브가 빠지므로 일반 정렬 불필요)
    sorted_videos = list(unique_videos.values())
    
    return sorted_videos


async def find_best_video(
    channel_url: str,
    keyword: str,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    채널에서 키워드에 맞는 최적의 영상 하나를 반환합니다.
    우선순위: 라이브 중 > 일반(5분 이상) > 라이브 예정
    """
    videos = await get_latest_videos(channel_url, keyword, max_retries)
    if not videos:
        return None

    live = [v for v in videos if v.get("is_live")]
    upcoming = [v for v in videos if v.get("is_upcoming")]
    normal = [v for v in videos if not v.get("is_live") and not v.get("is_upcoming")]

    # 일반 영상 중 5분(300초) 이상만
    normal_filtered = [v for v in normal if v.get("duration_seconds", 0) >= 300]

    if live:
        return live[0]
    if normal_filtered:
        return normal_filtered[0]
    if upcoming:
        return upcoming[0]

    logger.warning("적합한 영상 없음 (모두 5분 이하 또는 비어있음)")
    return None


# ──────────────────────────────────────────────
# 내부: 페이지 스크래핑
# ──────────────────────────────────────────────
async def _scrape_channel_page(
    url: str,
    keyword: Optional[str],
    max_retries: int,
    timeout: float,
) -> List[Dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url, headers=_HEADERS, follow_redirects=True, timeout=timeout
                )
                resp.raise_for_status()

            data = _extract_initial_data(resp.text)
            if not data:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return []

            videos = _find_videos(data, keyword)
            if videos:
                return videos

            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

        except httpx.TimeoutException:
            logger.warning(f"타임아웃: {url} (시도 {attempt + 1})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"스크래핑 오류: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)

    return []


# ──────────────────────────────────────────────
# 내부: ytInitialData 추출
# ──────────────────────────────────────────────
def _extract_initial_data(html: str) -> dict:
    patterns = [
        re.compile(r'var\s+ytInitialData\s*=\s*(\{.+?\});</script>', re.DOTALL),
        re.compile(r'window\["ytInitialData"\]\s*=\s*(\{.+?\});', re.DOTALL),
        re.compile(r'ytInitialData\s*=\s*(\{.+?\});', re.DOTALL),
    ]
    for pat in patterns:
        m = pat.search(html)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    return {}


# ──────────────────────────────────────────────
# 내부: 비디오 목록 추출
# ──────────────────────────────────────────────
def _find_videos(data: dict, keyword: Optional[str]) -> List[Dict[str, Any]]:
    videos: list = []

    # 비디오 렌더러들을 재귀적으로 수집
    renderers = _collect_video_renderers(data)

    for renderer in renderers:
        title = _extract_title(renderer)
        if keyword and keyword.lower() not in title.lower():
            continue

        video_id = renderer.get("videoId", "")
        if not video_id:
            continue

        is_upcoming, is_live = _check_live_status(renderer)
        video_length, duration_seconds = _extract_duration(renderer)
        upload_time = ""
        if "publishedTimeText" in renderer:
            upload_time = renderer["publishedTimeText"].get("simpleText", "")

        videos.append({
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "video_id": video_id,
            "upload_date": upload_time,
            "is_upcoming": is_upcoming,
            "is_live": is_live,
            "video_length": video_length,
            "duration_seconds": duration_seconds,
        })

    # 정렬: 라이브 > 일반 > 예정
    videos.sort(key=lambda v: (-1 if v["is_live"] else (1 if v["is_upcoming"] else 0)))
    return videos


def _collect_video_renderers(obj: Any, depth: int = 0) -> List[dict]:
    """JSON 트리에서 videoRenderer / gridVideoRenderer를 재귀적으로 수집"""
    if depth > 15 or not isinstance(obj, (dict, list)):
        return []

    results = []
    if isinstance(obj, dict):
        for key in ("videoRenderer", "gridVideoRenderer"):
            if key in obj:
                results.append(obj[key])
        for v in obj.values():
            results.extend(_collect_video_renderers(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_collect_video_renderers(item, depth + 1))
    return results


def _extract_title(renderer: dict) -> str:
    title = ""
    if "title" in renderer:
        if "runs" in renderer["title"]:
            for run in renderer["title"]["runs"]:
                title += run.get("text", "")
        elif "simpleText" in renderer["title"]:
            title = renderer["title"]["simpleText"]
    return title


def _check_live_status(renderer: dict) -> tuple:
    is_upcoming = False
    is_live = False

    for overlay in renderer.get("thumbnailOverlays", []):
        status = overlay.get("thumbnailOverlayTimeStatusRenderer", {})
        style = status.get("style", "")
        if style == "UPCOMING":
            is_upcoming = True
        elif style == "LIVE":
            is_live = True

    for badge in renderer.get("badges", []):
        meta = badge.get("metadataBadgeRenderer", {})
        if meta.get("style") == "BADGE_STYLE_TYPE_LIVE_NOW":
            is_live = True

    return is_upcoming, is_live


def _extract_duration(renderer: dict) -> tuple:
    video_length = "Unknown"
    duration_seconds = 0
    if "lengthText" in renderer:
        if "simpleText" in renderer["lengthText"]:
            video_length = renderer["lengthText"]["simpleText"]
            duration_seconds = _parse_duration_text(video_length)
    return video_length, duration_seconds


def _parse_duration_text(text: str) -> int:
    """'10:30' → 630초"""
    try:
        parts = text.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(parts[0])
    except (ValueError, IndexError):
        return 0


# ──────────────────────────────────────────────
# 업로드 날짜 파싱 (상대 시간 → KST datetime)
# ──────────────────────────────────────────────
def parse_upload_date(upload_time_text: str) -> datetime:
    """'3일 전', '5시간 전' 등을 KST datetime으로 변환합니다."""
    now = datetime.now(KST)
    if not upload_time_text:
        return now

    # "스트리밍 시간:" 접두어 제거
    text = upload_time_text.replace("스트리밍 시간:", "").strip()

    num_match = re.search(r"(\d+)", text)
    if not num_match:
        # 직접 날짜 형식 시도
        return _try_parse_absolute_date(text) or now

    value = int(num_match.group(1))

    time_units = {
        ("분 전", "minutes ago"): timedelta(minutes=value),
        ("시간 전", "hours ago"): timedelta(hours=value),
        ("일 전", "days ago"): timedelta(days=value),
        ("주 전", "weeks ago"): timedelta(weeks=value),
        ("개월 전", "months ago"): timedelta(days=value * 30),
        ("년 전", "years ago"): timedelta(days=value * 365),
    }

    for keywords, delta in time_units.items():
        if any(kw in text for kw in keywords):
            return now - delta

    return _try_parse_absolute_date(text) or now


def _try_parse_absolute_date(text: str) -> Optional[datetime]:
    # 한국어: 2024년 3월 13일
    m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if m:
        y, mo, d = map(int, m.groups())
        return datetime(y, mo, d, tzinfo=KST)

    # 영어: Mar 13, 2024
    m = re.search(r"([A-Za-z]{3})\s*(\d{1,2}),?\s*(\d{4})", text)
    if m:
        month_map = {
            "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
            "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
        }
        mo = month_map.get(m.group(1), 1)
        return datetime(int(m.group(3)), mo, int(m.group(2)), tzinfo=KST)

    return None
