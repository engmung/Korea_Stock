"""
채널 DB CRUD
SQLite 채널 테이블에서 활성 채널 목록을 조회합니다.
"""
import logging
from typing import Dict, List, Any
from sqlalchemy.future import select

from db.database import get_session_maker, Channel

logger = logging.getLogger(__name__)


async def get_active_channels() -> List[Dict[str, Any]]:
    """활성화된 채널 목록을 조회하여 정리된 딕셔너리 리스트로 반환합니다."""
    session_maker = get_session_maker()
    channels = []
    
    async with session_maker() as session:
        stmt = select(Channel).where(Channel.active == True)
        result = await session.execute(stmt)
        channel_objs = result.scalars().all()
        
        for ch in channel_objs:
            channel = {
                "page_id": ch.page_id,
                "name": ch.name,
                "url": ch.url,
                "keyword": ch.keyword,
                "active": ch.active,
            }
            if channel["url"]:
                channels.append(channel)
            else:
                logger.warning(f"채널 '{channel['name']}' — URL 누락, 스킵")

    logger.info(f"활성 채널 {len(channels)}개 조회")
    return channels


async def get_all_channels() -> List[Dict[str, Any]]:
    """모든 채널을 조회합니다."""
    session_maker = get_session_maker()
    channels = []
    
    async with session_maker() as session:
        stmt = select(Channel)
        result = await session.execute(stmt)
        channel_objs = result.scalars().all()
        
        for ch in channel_objs:
            channels.append({
                "page_id": ch.page_id,
                "name": ch.name,
                "url": ch.url,
                "keyword": ch.keyword,
                "active": ch.active,
            })
            
    return channels
