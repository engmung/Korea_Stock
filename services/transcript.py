"""
자막 추출 서비스
YouTube 영상의 자막(transcript)을 가져옵니다.
"""
import logging
import asyncio
import random
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi

from config.settings import get_settings

logger = logging.getLogger(__name__)


async def get_transcript(video_id: str, max_retries: int = 10) -> Optional[str]:
    """
    비디오 ID로부터 자막 텍스트를 가져옵니다.
    WebShare Residential 프록시 (1~10번)를 자동 교체하며 최대 10회 재시도합니다.
    """
    subtitles_disabled_msg = "Subtitles are disabled for this video"
    s = get_settings()
    
    for attempt in range(max_retries):
        proxies = None
        if s.youtube.proxy_url:
            proxy_url = s.youtube.proxy_url.replace("{id}", str(random.randint(1, 10)))
            proxies = {"http": proxy_url, "https": proxy_url}

        try:
            transcript_list = await asyncio.to_thread(
                YouTubeTranscriptApi.list_transcripts, 
                video_id, 
                proxies=proxies
            )
            
            # Find any Korean transcript (manual or generated)
            ko_transcript = None
            for tx in transcript_list:
                if 'ko' in tx.language_code.lower() or 'korean' in tx.language.lower() or '한국어' in tx.language:
                    if not ko_transcript or not tx.is_generated:
                        ko_transcript = tx # Prefer manual if both exist
            
            if not ko_transcript:
                logger.info(f"자막 없음 (한국어 제외 다국어만 존재): {video_id}")
                return None
                
            data = ko_transcript.fetch()
            text = " ".join(entry["text"] for entry in data)
            logger.info(f"한국어 자막 추출 성공 ('{ko_transcript.language}', generated={ko_transcript.is_generated}, video_id={video_id})")
            return text
            
        except Exception as e:
            if "Subtitles are disabled" in str(e):
                logger.info(f"자막 비활성화: {video_id}")
                return None
            if "No transcripts were found" in str(e):
                logger.info(f"자막 없음 (아예 없음): {video_id}")
                return None

            # 429 Rate Limit → 긴 대기 후 재시도
            if "Too Many Requests" in str(e) or "429" in str(e):
                wait_time = random.uniform(20, 40)
                logger.warning(f"YouTube 429 Rate Limit (시도 {attempt + 1}/{max_retries}), {wait_time:.0f}초 대기...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"자막 가져오기 최종 실패 (429 Rate Limit): {video_id}")
                    return None

            # ProxyError나 Timeout 등 기타 오류는 짧게 대기 후 새 프록시로 즉시 재시도
            logger.warning(f"자막 오류 (시도 {attempt + 1}/{max_retries}): {type(e).__name__} - 프록시 자동 교체 진행")
            import traceback
            traceback.print_exc()
            if attempt < max_retries - 1:
                await asyncio.sleep(random.uniform(0.5, 2.0))

    return None


async def check_subtitle_available(video_id: str) -> str:
    """
    자막 존재 여부만 빠르게 확인합니다.
    """
    try:
        s = get_settings()
        proxies = None
        if s.youtube.proxy_url:
            proxy_url = s.youtube.proxy_url.replace("{id}", str(random.randint(1, 10)))
            proxies = {"http": proxy_url, "https": proxy_url}
        
        transcript_list = await asyncio.to_thread(
            YouTubeTranscriptApi.list_transcripts, 
            video_id, 
            proxies=proxies
        )
        
        ko_exists = False
        for tx in transcript_list:
            if 'ko' in tx.language_code.lower() or 'korean' in tx.language.lower() or '한국어' in tx.language:
                ko_exists = True
                break
                
        return "Y" if ko_exists else "N"
    except Exception as e:
        if "Subtitles are disabled" in str(e):
            return "N"
        if "No transcripts were found" in str(e):
            return "N"
        if "Too Many Requests" in str(e) or "429" in str(e):
            logger.warning(f"[check_subtitle] 429 Rate Limit for {video_id} → 임시 'Y' 처리")
            return "Y"
        logger.warning(f"[check_subtitle] {video_id}: {type(e).__name__}")
        return "미확인"
