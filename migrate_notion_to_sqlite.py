"""
Notion 데이터를 SQLite로 마이그레이션하는 1회성 스크립트입니다.
반드시 `pip install aiosqlite sqlalchemy httpx` 후 단독으로 실행하세요.
"""
import asyncio
import os
import httpx
from db.database import init_db, get_session_maker, Channel, VideoQueue, StockOpinion

# TODO: 기존 Notion API 키와 DB ID를 여기에 입력하세요. (또는 이전 환경변수 사용)
NOTION_API_KEY = "ntn_M5197587006EiRThVxY2TdXNySkenscIbPCJfZHRjthewl"
CHANNEL_DB_ID = "1034b1c928d0476db01cab211e0c22a5"
VIDEO_QUEUE_DB_ID = "e4a52b53010644c985a920cd0a391efc"
STOCK_OPINION_DB_ID = "5d8845aea467457bb9223282f2c60bab"
DATABASE_URL = "sqlite+aiosqlite:///korea_stock.db" # 로컬 테스트용 (도커 밖)

HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

async def fetch_all_pages(client: httpx.AsyncClient, db_id: str):
    """Notion DB에서 모든 페이지를 가져옵니다."""
    pages = []
    has_more = True
    next_cursor = None
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    
    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor
        res = await client.post(url, headers=HEADERS, json=payload)
        data = res.json()
        if "results" not in data:
            print(f"Error fetching DB {db_id}: {data}")
            break
        pages.extend(data["results"])
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")
        print(f"  Fetched {len(pages)} pages...")
    return pages

# 파싱 헬퍼 (기존 client.py 발췌)
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

async def migrate():
    # 1. 로컬 SQLite 초기화
    await init_db(DATABASE_URL)
    session_maker = get_session_maker()
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ──────────────────────────────────────────────
        # 1. 마이그레이션: 채널 목록
        # ──────────────────────────────────────────────
        print("\n--- Migrating Channels ---")
        pages = await fetch_all_pages(client, CHANNEL_DB_ID)
        async with session_maker() as session:
            for page in pages:
                props = page["properties"]
                ch = Channel(
                    page_id=page["id"],
                    name=_get_title(props, "채널명"),
                    url=_get_url(props, "URL"),
                    keyword=_get_rich_text(props, "키워드"),
                    active=_get_checkbox(props, "활성화"),
                )
                session.add(ch)
            await session.commit()
        print(f"[Done] Migrated {len(pages)} channels")

        # ──────────────────────────────────────────────
        # 2. 마이그레이션: 영상 큐
        # ──────────────────────────────────────────────
        print("\n--- Migrating Video Queue ---")
        pages = await fetch_all_pages(client, VIDEO_QUEUE_DB_ID)
        async with session_maker() as session:
            for page in pages:
                props = page["properties"]
                vq = VideoQueue(
                    page_id=page["id"],
                    title=_get_title(props, "제목"),
                    video_id=_get_rich_text(props, "영상ID"),
                    channel_name=_get_select(props, "채널명"),
                    upload_date=_get_date(props, "업로드시간"),
                    video_length=_get_rich_text(props, "영상길이"),
                    url=_get_url(props, "원본링크"),
                    subtitle_status=_get_select(props, "자막상태") or "미확인",
                    analysis_needed=_get_select(props, "분석필요") or "미정",
                    analysis_done=_get_checkbox(props, "분석완료"),
                    summary=_get_rich_text(props, "영상요약"),
                )
                session.add(vq)
            await session.commit()
        print(f"[Done] Migrated {len(pages)} video queues")

        # ──────────────────────────────────────────────
        # 3. 마이그레이션: 종목 의견
        # ──────────────────────────────────────────────
        print("\n--- Migrating Stock Opinions ---")
        pages = await fetch_all_pages(client, STOCK_OPINION_DB_ID)
        async with session_maker() as session:
            for page in pages:
                props = page["properties"]
                so = StockOpinion(
                    page_id=page["id"],
                    original_name=_get_title(props, "원본_종목명"),
                    normalized_name=_get_rich_text(props, "정규화_종목명"),
                    normalization_status=_get_select(props, "정규화_상태") or "미처리",
                    opinion_type=_get_select(props, "의견유형") or "관심",
                    recommender=_get_rich_text(props, "추천인"),
                    reason_summary=_get_rich_text(props, "근거요약"),
                    upload_date=_get_date(props, "추천일자"),
                    video_id=_get_rich_text(props, "원본영상ID"),
                )
                session.add(so)
            await session.commit()
        print(f"[Done] Migrated {len(pages)} stock opinions")

    print("\n[Success] All migrations completed successfully!")

if __name__ == "__main__":
    asyncio.run(migrate())
