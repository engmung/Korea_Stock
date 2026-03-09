import asyncio
from db.database import init_db, get_session_maker, VideoQueue
from sqlalchemy import select
from youtube_transcript_api import YouTubeTranscriptApi
from config.settings import get_settings

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
            try:
                tx = YouTubeTranscriptApi.get_transcript(t.video_id, languages=['ko'])
                print(f"Success get_transcript: {len(tx)} items")
            except Exception as e:
                print(f"Exception for ko: {type(e).__name__} - {e}")
                
            try:
                tx_list = YouTubeTranscriptApi.list_transcripts(t.video_id)
                generated = []
                for transcript in tx_list:
                    generated.append(f"{transcript.language} ({transcript.language_code}) - {'Generated' if transcript.is_generated else 'Manual'}")
                print(f"Available transcripts: {generated}")
            except Exception as e:
                print(f"Exception list: {type(e).__name__} - {e}")
            print("-" * 50)

if __name__ == '__main__':
    asyncio.run(main())
