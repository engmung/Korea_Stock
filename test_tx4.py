import asyncio
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
        for t in targets:
            print(f"Testing video: {t.title} ({t.video_id})")
            
            avail = await check_subtitle_available(t.video_id)
            print(f"check_subtitle_available returned: {avail}")
            
            if avail == 'Y':
                tx = await get_transcript(t.video_id)
                if tx:
                    print(f"Successfully fetched transcript: {len(tx)} chars")
                else:
                    print(f"Failed to fetch transcript data despite available='Y'")

            print("-" * 50)

if __name__ == '__main__':
    asyncio.run(main())
