"""
채널 DB CRUD
채널 DB에서 활성 채널 목록을 조회합니다.
"""
import logging
from typing import Dict, List, Any

from config.settings import get_settings
from db.client import query_database

logger = logging.getLogger(__name__)


async def get_active_channels() -> List[Dict[str, Any]]:
    """활성화된 채널 목록을 조회하여 정리된 딕셔너리 리스트로 반환합니다."""
    s = get_settings()
    filter_body = {
        "property": "활성화",
        "checkbox": {"equals": True},
    }
    pages = await query_database(s.notion.channel_db_id, filter_body=filter_body)

    channels = []
    for page in pages:
        props = page.get("properties", {})
        channel = {
            "page_id": page.get("id"),
            "name": _get_title(props, "채널명"),
            "url": _get_url(props, "URL"),
            "keyword": _get_rich_text(props, "키워드"),
            "active": _get_checkbox(props, "활성화"),
        }
        if channel["url"]:
            channels.append(channel)
        else:
            logger.warning(f"채널 '{channel['name']}' — URL 누락, 스킵")

    logger.info(f"활성 채널 {len(channels)}개 조회")
    return channels


async def get_all_channels() -> List[Dict[str, Any]]:
    """모든 채널을 조회합니다."""
    s = get_settings()
    pages = await query_database(s.notion.channel_db_id)

    channels = []
    for page in pages:
        props = page.get("properties", {})
        channels.append({
            "page_id": page.get("id"),
            "name": _get_title(props, "채널명"),
            "url": _get_url(props, "URL"),
            "keyword": _get_rich_text(props, "키워드"),
            "active": _get_checkbox(props, "활성화"),
        })
    return channels


# ──────────────────────────────────────────────
# 속성 헬퍼
# ──────────────────────────────────────────────
def _get_title(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "title" in prop and prop["title"]:
        return prop["title"][0].get("plain_text", "")
    return ""


def _get_url(props: dict, key: str) -> str:
    prop = props.get(key, {})
    return prop.get("url", "") or ""


def _get_rich_text(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "rich_text" in prop and prop["rich_text"]:
        return prop["rich_text"][0].get("plain_text", "")
    return ""


def _get_checkbox(props: dict, key: str) -> bool:
    prop = props.get(key, {})
    return prop.get("checkbox", False)
