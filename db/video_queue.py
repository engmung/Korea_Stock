"""
영상 큐 DB CRUD
영상 등록, 중복 체크, 상태 업데이트 등을 처리합니다.
"""
import logging
from typing import Dict, List, Any, Optional

from config.settings import get_settings
from db.client import query_database, create_page, update_page

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 조회
# ──────────────────────────────────────────────
async def get_videos_by_status(
    analysis_needed: Optional[str] = None,
    subtitle_status: Optional[str] = None,
    analysis_done: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """조건에 맞는 영상 큐 목록을 조회합니다."""
    s = get_settings()
    conditions = []

    if analysis_needed is not None:
        conditions.append({
            "property": "분석필요",
            "select": {"equals": analysis_needed},
        })
    if subtitle_status is not None:
        conditions.append({
            "property": "자막상태",
            "select": {"equals": subtitle_status},
        })
    if analysis_done is not None:
        conditions.append({
            "property": "분석완료",
            "checkbox": {"equals": analysis_done},
        })

    filter_body = {"and": conditions} if conditions else None
    pages = await query_database(s.notion.video_queue_db_id, filter_body=filter_body)
    return [_parse_video_page(p) for p in pages]


async def get_all_videos() -> List[Dict[str, Any]]:
    """모든 영상 큐 항목을 조회합니다."""
    s = get_settings()
    pages = await query_database(s.notion.video_queue_db_id)
    return [_parse_video_page(p) for p in pages]


async def video_exists(video_id: str) -> bool:
    """영상 ID로 중복 여부를 확인합니다."""
    s = get_settings()
    filter_body = {
        "property": "영상ID",
        "rich_text": {"equals": video_id},
    }
    pages = await query_database(s.notion.video_queue_db_id, filter_body=filter_body)
    return len(pages) > 0


async def get_subtitle_recheck_targets() -> List[Dict[str, Any]]:
    """자막상태가 '미확인'이거나, 분석필요가 '필요'인데 자막이 'N'인 영상을 조회합니다."""
    s = get_settings()
    filter_body = {
        "or": [
            {"property": "자막상태", "select": {"equals": "미확인"}},
            {
                "and": [
                    {"property": "분석필요", "select": {"equals": "필요"}},
                    {"property": "자막상태", "select": {"equals": "N"}},
                ]
            }
        ]
    }
    pages = await query_database(s.notion.video_queue_db_id, filter_body=filter_body)
    return [_parse_video_page(p) for p in pages]


async def get_pending_filter_videos() -> List[Dict[str, Any]]:
    """분석필요가 '미정'인 영상을 조회합니다."""
    return await get_videos_by_status(analysis_needed="미정")


async def get_ready_for_report_videos() -> List[Dict[str, Any]]:
    """분석필요=필요 & 자막상태=Y & 분석완료=False인 영상을 조회합니다."""
    s = get_settings()
    filter_body = {
        "and": [
            {"property": "분석필요", "select": {"equals": "필요"}},
            {"property": "자막상태", "select": {"equals": "Y"}},
            {"property": "분석완료", "checkbox": {"equals": False}},
        ]
    }
    pages = await query_database(s.notion.video_queue_db_id, filter_body=filter_body)
    return [_parse_video_page(p) for p in pages]


# ──────────────────────────────────────────────
# 생성
# ──────────────────────────────────────────────
async def register_video(video_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """영상 큐 DB에 새 영상을 등록합니다."""
    s = get_settings()
    properties = {
        "제목": {
            "title": [{"text": {"content": video_data.get("title", "")}}]
        },
        "영상ID": {
            "rich_text": [{"text": {"content": video_data.get("video_id", "")}}]
        },
        "채널명": {
            "select": {"name": video_data.get("channel_name", "기타")}
        },
        "업로드시간": {
            "date": {"start": video_data.get("upload_date", "")}
        } if video_data.get("upload_date") else {"date": None},
        "영상길이": {
            "rich_text": [{"text": {"content": video_data.get("video_length", "Unknown")}}]
        },
        "원본링크": {
            "url": video_data.get("url", "")
        },
        "자막상태": {
            "select": {"name": video_data.get("subtitle_status", "미확인")}
        },
        "분석필요": {
            "select": {"name": "미정"}
        },
        "분석완료": {
            "checkbox": False
        },
    }

    return await create_page(s.notion.video_queue_db_id, properties)


# ──────────────────────────────────────────────
# 업데이트
# ──────────────────────────────────────────────
async def update_subtitle_status(page_id: str, status: str) -> bool:
    """자막상태를 업데이트합니다. (Y / N / 미확인)"""
    return await update_page(page_id, {
        "자막상태": {"select": {"name": status}}
    })


async def update_analysis_needed(page_id: str, status: str) -> bool:
    """분석필요를 업데이트합니다. (미정 / 필요 / 불필요)"""
    return await update_page(page_id, {
        "분석필요": {"select": {"name": status}}
    })


async def mark_analysis_done(page_id: str) -> bool:
    """분석완료를 True로 변경합니다."""
    return await update_page(page_id, {
        "분석완료": {"checkbox": True}
    })


async def update_summary(page_id: str, summary: str) -> bool:
    """영상 요약을 업데이트합니다."""
    return await update_page(page_id, {
        "영상요약": {"rich_text": [{"text": {"content": summary[:2000]}}]}
    })


# ──────────────────────────────────────────────
# 파싱 헬퍼
# ──────────────────────────────────────────────
def _parse_video_page(page: Dict[str, Any]) -> Dict[str, Any]:
    props = page.get("properties", {})
    return {
        "page_id": page.get("id"),
        "title": _get_title(props, "제목"),
        "video_id": _get_rich_text(props, "영상ID"),
        "channel_name": _get_select(props, "채널명"),
        "upload_date": _get_date(props, "업로드시간"),
        "video_length": _get_rich_text(props, "영상길이"),
        "url": _get_url(props, "원본링크"),
        "subtitle_status": _get_select(props, "자막상태"),
        "analysis_needed": _get_select(props, "분석필요"),
        "analysis_done": _get_checkbox(props, "분석완료"),
    }


def _get_title(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "title" in prop and prop["title"]:
        return prop["title"][0].get("plain_text", "")
    return ""


def _get_rich_text(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "rich_text" in prop and prop["rich_text"]:
        return prop["rich_text"][0].get("plain_text", "")
    return ""


def _get_select(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "select" in prop and prop["select"]:
        return prop["select"].get("name", "")
    return ""


def _get_url(props: dict, key: str) -> str:
    prop = props.get(key, {})
    return prop.get("url", "") or ""


def _get_checkbox(props: dict, key: str) -> bool:
    prop = props.get(key, {})
    return prop.get("checkbox", False)


def _get_date(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "date" in prop and prop["date"]:
        return prop["date"].get("start", "")
    return ""
