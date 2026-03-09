import asyncio
import traceback
from db.database import init_db, get_session_maker, VideoQueue
from sqlalchemy import select
from config.settings import get_settings
from services.transcript import check_subtitle_available, get_transcript

async def main():
    settings = get_settings()
    await init_db(settings.db.url)
    session_maker = get_session_maker()
    async with session_maker() as session:
        stmt = select(VideoQueue).where(VideoQueue.subtitle_status == 'N')
        result = await session.execute(stmt)
        targets = result.scalars().all()
        for t in targets[:2]:  # Test first 2
            print(f"Testing video: {t.title} ({t.video_id})")
            
            try:
                avail = await check_subtitle_available(t.video_id)
                print(f"check_subtitle_available returned: {avail}")
            except Exception as e:
                print(f"check error: {traceback.format_exc()}")
            
            try:
                tx = await get_transcript(t.video_id)
                if tx:
                    print(f"Successfully fetched transcript: {len(tx)} chars")
                else:
                    print(f"Failed to fetch transcript data")
            except Exception as e:
                print(f"get_transcript error: {traceback.format_exc()}")

            print("-" * 50)

if __name__ == '__main__':
    asyncio.run(main())
