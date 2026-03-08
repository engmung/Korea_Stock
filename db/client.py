"""
Notion API 공용 클라이언트
query, create, update, append 등 공통 동작을 캡슐화합니다.
"""
import logging
import asyncio
from typing import Dict, List, Any, Optional

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
BASE_URL = "https://api.notion.com/v1"


def _headers() -> dict:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.notion.api_key}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }


# ──────────────────────────────────────────────
# 데이터베이스 쿼리
# ──────────────────────────────────────────────
async def query_database(
    database_id: str,
    filter_body: Optional[dict] = None,
    sorts: Optional[list] = None,
    max_retries: int = 3,
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Notion 데이터베이스를 쿼리합니다.
    페이지네이션을 자동 처리하여 전체 결과를 반환합니다.
    """
    url = f"{BASE_URL}/databases/{database_id}/query"
    all_results: list = []
    has_more = True
    start_cursor: Optional[str] = None

    while has_more:
        body: dict = {}
        if filter_body:
            body["filter"] = filter_body
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url, headers=_headers(), json=body, timeout=timeout
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    all_results.extend(data.get("results", []))
                    has_more = data.get("has_more", False)
                    start_cursor = data.get("next_cursor")
                    break  # 성공 시 재시도 루프 탈출
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    retry_after = int(e.response.headers.get("Retry-After", 5))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                else:
                    logger.error(f"HTTP error querying DB: {e.response.status_code}")
                    return all_results
            except Exception as e:
                logger.error(f"Error querying DB: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return all_results

    logger.info(f"Queried {len(all_results)} records from {database_id}")
    return all_results


# ──────────────────────────────────────────────
# 페이지 생성
# ──────────────────────────────────────────────
async def create_page(
    database_id: str,
    properties: Dict[str, Any],
    children: Optional[List[Dict[str, Any]]] = None,
    max_retries: int = 3,
    timeout: float = 120.0,
) -> Optional[Dict[str, Any]]:
    """
    Notion 데이터베이스에 새 페이지를 생성합니다.
    children(블록)이 100개를 초과하면 분할 요청합니다.
    """
    url = f"{BASE_URL}/pages"
    MAX_BLOCKS = 90

    all_children = children or []
    first_children = all_children[:MAX_BLOCKS]
    remaining_children = all_children[MAX_BLOCKS:]

    data = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }
    if first_children:
        data["children"] = first_children

    # 첫 번째 요청
    page_response = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, headers=_headers(), json=data, timeout=timeout
                )
                resp.raise_for_status()
                page_response = resp.json()
                break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries - 1:
                retry_after = int(e.response.headers.get("Retry-After", 5))
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"Error creating page: {e.response.status_code} - {e.response.text}")
                return None
        except Exception as e:
            logger.error(f"Error creating page: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                return None

    if not page_response:
        return None

    # 남은 블록 추가
    if remaining_children:
        page_id = page_response["id"]
        await append_blocks(page_id, remaining_children, max_retries, timeout)

    return page_response


# ──────────────────────────────────────────────
# 페이지 속성 업데이트
# ──────────────────────────────────────────────
async def update_page(
    page_id: str,
    properties: Dict[str, Any],
    max_retries: int = 3,
    timeout: float = 30.0,
) -> bool:
    """Notion 페이지의 속성을 업데이트합니다."""
    url = f"{BASE_URL}/pages/{page_id}"

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.patch(
                    url,
                    headers=_headers(),
                    json={"properties": properties},
                    timeout=timeout,
                )
                resp.raise_for_status()
                return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries - 1:
                retry_after = int(e.response.headers.get("Retry-After", 5))
                await asyncio.sleep(retry_after)
            else:
                logger.error(f"Error updating page: {e.response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error updating page: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                return False
    return False


# ──────────────────────────────────────────────
# 블록 추가 (append children)
# ──────────────────────────────────────────────
async def append_blocks(
    page_id: str,
    blocks: List[Dict[str, Any]],
    max_retries: int = 3,
    timeout: float = 120.0,
) -> bool:
    """페이지에 블록을 추가합니다. 90개씩 분할하여 요청합니다."""
    MAX_BLOCKS = 90
    url = f"{BASE_URL}/blocks/{page_id}/children"

    for i in range(0, len(blocks), MAX_BLOCKS):
        chunk = blocks[i : i + MAX_BLOCKS]
        success = False
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.patch(
                        url,
                        headers=_headers(),
                        json={"children": chunk},
                        timeout=timeout,
                    )
                    resp.raise_for_status()
                    success = True
                    await asyncio.sleep(0.5)  # rate limit 준수
                    break
            except Exception as e:
                logger.error(f"Error appending blocks (part {i // MAX_BLOCKS + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        if not success:
            logger.warning("Could not append all blocks")
            return False

    return True
