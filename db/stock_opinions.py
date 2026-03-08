"""
종목의견 DB CRUD
종목별 의견 레코드 생성, 정규화 상태 관리를 처리합니다.
"""
import logging
from typing import Dict, List, Any, Optional

from config.settings import get_settings
from db.client import query_database, create_page, update_page

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 생성
# ──────────────────────────────────────────────
async def create_stock_opinion(opinion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    종목의견 DB에 새 레코드를 생성합니다.

    Args:
        opinion: 종목 의견 정보
            - name: 원본 종목명
            - opinion_type: 추천 | 관심 | 주의
            - recommender: 추천인 (전문가명 또는 프로그램명)
            - reason_summary: 근거 요약
            - upload_date: 추천일자 (영상 업로드 날짜)
            - video_id: 원본 영상 ID
    """
    s = get_settings()

    properties = {
        "원본_종목명": {
            "title": [{"text": {"content": opinion.get("name", "")}}]
        },
        "정규화_종목명": {
            "rich_text": []  # 초기 빈값
        },
        "정규화_상태": {
            "select": {"name": "미처리"}
        },
        "의견유형": {
            "select": {"name": opinion.get("opinion_type", "관심")}
        },
        "추천인": {
            "rich_text": [{"text": {"content": opinion.get("recommender", "")}}]
        },
        "근거요약": {
            "rich_text": [{"text": {"content": _truncate(opinion.get("reason_summary", ""), 2000)}}]
        },
        "원본영상ID": {
            "rich_text": [{"text": {"content": opinion.get("video_id", "")}}]
        },
    }

    # 추천일자 (있을 경우만)
    upload_date = opinion.get("upload_date", "")
    if upload_date:
        properties["추천일자"] = {"date": {"start": upload_date}}

    page = await create_page(s.notion.stock_opinion_db_id, properties)
    if page:
        logger.info(f"종목의견 생성: {opinion.get('name', '')} ({opinion.get('opinion_type', '')})")
    return page


async def create_stock_opinions_batch(
    opinions: List[Dict[str, Any]],
) -> int:
    """여러 종목의견을 일괄 생성합니다. 생성 성공 수를 반환합니다."""
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
    s = get_settings()
    filter_body = {
        "property": "정규화_상태",
        "select": {"equals": "미처리"},
    }
    pages = await query_database(s.notion.stock_opinion_db_id, filter_body=filter_body)
    return [_parse_opinion_page(p) for p in pages]


async def get_normalized_names() -> List[str]:
    """정규화 완료된 종목명 목록을 반환합니다."""
    s = get_settings()
    filter_body = {
        "property": "정규화_상태",
        "select": {"equals": "완료"},
    }
    pages = await query_database(s.notion.stock_opinion_db_id, filter_body=filter_body)

    names = set()
    for page in pages:
        props = page.get("properties", {})
        name = _get_rich_text(props, "정규화_종목명")
        if name:
            names.add(name)
    return sorted(names)


async def get_all_opinions() -> List[Dict[str, Any]]:
    """모든 종목의견을 조회합니다."""
    s = get_settings()
    pages = await query_database(
        s.notion.stock_opinion_db_id,
        sorts=[{"property": "추천일자", "direction": "descending"}],
    )
    return [_parse_opinion_page(p) for p in pages]


# ──────────────────────────────────────────────
# 업데이트 (정규화)
# ──────────────────────────────────────────────
async def update_normalization(
    page_id: str,
    normalized_name: str,
    status: str,  # "완료" | "수동확인필요"
) -> bool:
    """종목의견의 정규화 상태를 업데이트합니다."""
    properties = {
        "정규화_종목명": {
            "rich_text": [{"text": {"content": normalized_name}}]
        },
        "정규화_상태": {
            "select": {"name": status}
        },
    }
    return await update_page(page_id, properties)


# ──────────────────────────────────────────────
# 파싱 헬퍼
# ──────────────────────────────────────────────
def _parse_opinion_page(page: Dict[str, Any]) -> Dict[str, Any]:
    props = page.get("properties", {})
    return {
        "page_id": page.get("id"),
        "original_name": _get_title(props, "원본_종목명"),
        "normalized_name": _get_rich_text(props, "정규화_종목명"),
        "normalization_status": _get_select(props, "정규화_상태"),
        "opinion_type": _get_select(props, "의견유형"),
        "recommendation_date": _get_date(props, "추천일자"),
        "recommender": _get_rich_text(props, "추천인"),
        "reason_summary": _get_rich_text(props, "근거요약"),
        "video_id": _get_rich_text(props, "원본영상ID"),
    }


def _truncate(text: str, max_len: int) -> str:
    return text[:max_len] if len(text) > max_len else text


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

def _get_date(props: dict, key: str) -> str:
    prop = props.get(key, {})
    if "date" in prop and prop["date"]:
        return prop["date"].get("start", "")
    return ""
