import re
import json
import logging
import httpx
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)

def extract_initial_data(html_content: str) -> dict:
    """YouTube의 초기 데이터를 추출합니다."""
    try:
        # ytInitialData가 포함된 script 태그를 찾기
        pattern = re.compile(r'var\s+ytInitialData\s*=\s*(\{.+?\});</script>', re.DOTALL)
        match = pattern.search(html_content)
        
        if not match:
            # 다른 패턴 시도
            pattern = re.compile(r'window\["ytInitialData"\]\s*=\s*(\{.+?\});', re.DOTALL)
            match = pattern.search(html_content)
        
        if not match:
            # 또 다른 패턴 시도
            pattern = re.compile(r'ytInitialData\s*=\s*(\{.+?\});', re.DOTALL)
            match = pattern.search(html_content)
        
        if match:
            json_str = match.group(1)
            data = json.loads(json_str)
            return data
        else:
            logger.warning("ytInitialData를 찾을 수 없습니다.")
            return {}
    except Exception as e:
        logger.error(f"초기 데이터 추출 오류: {str(e)}")
        return {}

def find_videos_with_keyword(data: dict, keyword: str) -> List[Dict[str, Any]]:
    """YouTube 초기 데이터에서 키워드가 포함된 영상 정보를 추출합니다."""
    videos = []
    
    try:
        # 탭 렌더러 찾기
        tab_renderers = None
        
        if "contents" in data:
            if "twoColumnBrowseResultsRenderer" in data["contents"]:
                if "tabs" in data["contents"]["twoColumnBrowseResultsRenderer"]:
                    tab_renderers = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"]
            elif "sectionListRenderer" in data["contents"]:
                if "contents" in data["contents"]["sectionListRenderer"]:
                    tab_renderers = [{"tabRenderer": {"content": data["contents"]["sectionListRenderer"]}}]
        
        if not tab_renderers:
            logger.warning("탭 렌더러를 찾을 수 없습니다.")
            return videos
        
        # 각 탭 검사
        for tab in tab_renderers:
            if "tabRenderer" not in tab:
                continue
            
            # 콘텐츠 추출
            content = tab["tabRenderer"].get("content", {})
            
            # 섹션 리스트 렌더러
            if "sectionListRenderer" in content:
                for section in content["sectionListRenderer"].get("contents", []):
                    # 아이템 섹션 렌더러
                    if "itemSectionRenderer" in section:
                        for content_item in section["itemSectionRenderer"].get("contents", []):
                            # 그리드 렌더러
                            if "gridRenderer" in content_item:
                                for item in content_item["gridRenderer"].get("items", []):
                                    # 비디오 정보 추출 (그리드 형식)
                                    if "gridVideoRenderer" in item:
                                        video_renderer = item["gridVideoRenderer"]
                                        
                                        # 제목 추출
                                        title = ""
                                        if "title" in video_renderer and "runs" in video_renderer["title"]:
                                            for run in video_renderer["title"]["runs"]:
                                                title += run.get("text", "")
                                        
                                        # 키워드 확인
                                        if keyword.lower() in title.lower():
                                            # 비디오 ID 추출
                                            video_id = video_renderer.get("videoId", "")
                                            
                                            # URL 생성
                                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                                            
                                            # 업로드 시간 추출
                                            upload_time = ""
                                            if "publishedTimeText" in video_renderer:
                                                upload_time = video_renderer["publishedTimeText"].get("simpleText", "")
                                            
                                            # 라이브 정보 확인
                                            is_upcoming = False
                                            is_live = False
                                            
                                            if "thumbnailOverlays" in video_renderer:
                                                for overlay in video_renderer["thumbnailOverlays"]:
                                                    if "thumbnailOverlayTimeStatusRenderer" in overlay:
                                                        status_renderer = overlay["thumbnailOverlayTimeStatusRenderer"]
                                                        if "style" in status_renderer:
                                                            if status_renderer["style"] == "UPCOMING":
                                                                is_upcoming = True
                                                            elif status_renderer["style"] == "LIVE":
                                                                is_live = True
                                            
                                            # 비디오 길이 추출
                                            video_length = "Unknown"
                                            duration_seconds = 0
                                            if "lengthText" in video_renderer:
                                                if "simpleText" in video_renderer["lengthText"]:
                                                    video_length = video_renderer["lengthText"]["simpleText"]
                                                    # 길이 문자열을 초로 변환
                                                    duration_seconds = parse_duration_from_text(video_length)
                                            
                                            videos.append({
                                                "title": title,
                                                "url": video_url,
                                                "video_id": video_id,
                                                "upload_date": upload_time,
                                                "is_upcoming": is_upcoming,
                                                "is_live": is_live,
                                                "video_length": video_length,
                                                "duration_seconds": duration_seconds
                                            })
                                            logger.info(f"매칭된 영상 발견: {title} {'(예정됨)' if is_upcoming else '(라이브 중)' if is_live else ''}")
                            
                            # 일반 비디오 정보 추출 (리스트 형식)
                            elif "videoRenderer" in content_item:
                                video_renderer = content_item["videoRenderer"]
                                
                                # 제목 추출
                                title = ""
                                if "title" in video_renderer and "runs" in video_renderer["title"]:
                                    for run in video_renderer["title"]["runs"]:
                                        title += run.get("text", "")
                                
                                # 키워드 확인
                                if keyword.lower() in title.lower():
                                    # 비디오 ID 추출
                                    video_id = video_renderer.get("videoId", "")
                                    
                                    # URL 생성
                                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                                    
                                    # 업로드 시간 추출
                                    upload_time = ""
                                    if "publishedTimeText" in video_renderer:
                                        upload_time = video_renderer["publishedTimeText"].get("simpleText", "")
                                    
                                    # 라이브 정보 확인
                                    is_upcoming = False
                                    is_live = False
                                    
                                    if "badges" in video_renderer:
                                        for badge in video_renderer["badges"]:
                                            if "metadataBadgeRenderer" in badge:
                                                badge_renderer = badge["metadataBadgeRenderer"]
                                                if "style" in badge_renderer and badge_renderer.get("style") == "BADGE_STYLE_TYPE_LIVE_NOW":
                                                    is_live = True
                                    
                                    if "thumbnailOverlays" in video_renderer:
                                        for overlay in video_renderer["thumbnailOverlays"]:
                                            if "thumbnailOverlayTimeStatusRenderer" in overlay:
                                                status_renderer = overlay["thumbnailOverlayTimeStatusRenderer"]
                                                if "style" in status_renderer:
                                                    if status_renderer["style"] == "UPCOMING":
                                                        is_upcoming = True
                                                    elif status_renderer["style"] == "LIVE":
                                                        is_live = True
                                    
                                    # 비디오 길이 추출
                                    video_length = "Unknown"
                                    duration_seconds = 0
                                    if "lengthText" in video_renderer:
                                        if "simpleText" in video_renderer["lengthText"]:
                                            video_length = video_renderer["lengthText"]["simpleText"]
                                            # 길이 문자열을 초로 변환
                                            duration_seconds = parse_duration_from_text(video_length)
                                    
                                    videos.append({
                                        "title": title,
                                        "url": video_url,
                                        "video_id": video_id,
                                        "upload_date": upload_time,
                                        "is_upcoming": is_upcoming,
                                        "is_live": is_live,
                                        "video_length": video_length,
                                        "duration_seconds": duration_seconds
                                    })
                                    logger.info(f"매칭된 영상 발견: {title} {'(예정됨)' if is_upcoming else '(라이브 중)' if is_live else ''}")
            
            # 리치 그리드 렌더러
            elif "richGridRenderer" in content:
                for item in content["richGridRenderer"].get("contents", []):
                    if "richItemRenderer" in item:
                        if "content" in item["richItemRenderer"]:
                            content_item = item["richItemRenderer"]["content"]
                            
                            # 비디오 정보 추출
                            if "videoRenderer" in content_item:
                                video_renderer = content_item["videoRenderer"]
                                
                                # 제목 추출
                                title = ""
                                if "title" in video_renderer and "runs" in video_renderer["title"]:
                                    for run in video_renderer["title"]["runs"]:
                                        title += run.get("text", "")
                                
                                # 키워드 확인
                                if keyword.lower() in title.lower():
                                    # 비디오 ID 추출
                                    video_id = video_renderer.get("videoId", "")
                                    
                                    # URL 생성
                                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                                    
                                    # 업로드 시간 추출
                                    upload_time = ""
                                    if "publishedTimeText" in video_renderer:
                                        upload_time = video_renderer["publishedTimeText"].get("simpleText", "")
                                    
                                    # 라이브 정보 확인
                                    is_upcoming = False
                                    is_live = False
                                    
                                    if "badges" in video_renderer:
                                        for badge in video_renderer["badges"]:
                                            if "metadataBadgeRenderer" in badge:
                                                badge_renderer = badge["metadataBadgeRenderer"]
                                                if "style" in badge_renderer and badge_renderer.get("style") == "BADGE_STYLE_TYPE_LIVE_NOW":
                                                    is_live = True
                                    
                                    if "thumbnailOverlays" in video_renderer:
                                        for overlay in video_renderer["thumbnailOverlays"]:
                                            if "thumbnailOverlayTimeStatusRenderer" in overlay:
                                                status_renderer = overlay["thumbnailOverlayTimeStatusRenderer"]
                                                if "style" in status_renderer:
                                                    if status_renderer["style"] == "UPCOMING":
                                                        is_upcoming = True
                                                    elif status_renderer["style"] == "LIVE":
                                                        is_live = True
                                    
                                    # 비디오 길이 추출
                                    video_length = "Unknown"
                                    duration_seconds = 0
                                    if "lengthText" in video_renderer:
                                        if "simpleText" in video_renderer["lengthText"]:
                                            video_length = video_renderer["lengthText"]["simpleText"]
                                            # 길이 문자열을 초로 변환
                                            duration_seconds = parse_duration_from_text(video_length)
                                    
                                    videos.append({
                                        "title": title,
                                        "url": video_url,
                                        "video_id": video_id,
                                        "upload_date": upload_time,
                                        "is_upcoming": is_upcoming,
                                        "is_live": is_live,
                                        "video_length": video_length,
                                        "duration_seconds": duration_seconds
                                    })
                                    logger.info(f"매칭된 영상 발견: {title} {'(예정됨)' if is_upcoming else '(라이브 중)' if is_live else ''}")
        
        # 비디오 정렬 (라이브 > 일반 비디오 > 예정)
        videos.sort(key=lambda v: (
            -1 if v.get("is_live", False) else (1 if v.get("is_upcoming", False) else 0)
        ))
        
        return videos
    except Exception as e:
        logger.error(f"비디오 정보 추출 오류: {str(e)}")
        return videos

def parse_duration_from_text(duration_text: str) -> int:
    """
    "10:30"과 같은 형식의 영상 길이 텍스트를 초 단위로 변환합니다.
    
    Args:
        duration_text: 영상 길이 텍스트 (예: "10:30", "1:30:45")
        
    Returns:
        초 단위의 영상 길이
    """
    try:
        parts = duration_text.split(":")
        
        if len(parts) == 3:  # 시:분:초 형식
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        elif len(parts) == 2:  # 분:초 형식
            minutes = int(parts[0])
            seconds = int(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 1:  # 초 형식
            return int(parts[0])
        else:
            return 0
    except:
        return 0

async def extract_channel_id_from_page(channel_url: str, max_retries: int = 3, timeout: float = 30.0) -> Optional[str]:
    """
    웹 스크래핑을 사용하여 채널 페이지에서 채널 ID를 추출합니다.
    
    Args:
        channel_url: YouTube 채널 URL
        max_retries: 최대 재시도 횟수
        timeout: 요청 타임아웃(초)
        
    Returns:
        채널 ID 또는 None (추출 실패 시)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"채널 페이지 요청 중 (시도 {attempt+1}/{max_retries})")
                response = await client.get(
                    channel_url, 
                    headers=headers, 
                    follow_redirects=True, 
                    timeout=timeout
                )
                response.raise_for_status()
                
                # 정규식을 사용하여 채널 ID 추출
                html_content = response.text
                
                # 방법 1: channelId 직접 찾기
                channel_id_pattern = re.compile(r'"channelId"\s*:\s*"([^"]+)"')
                match = channel_id_pattern.search(html_content)
                if match:
                    channel_id = match.group(1)
                    logger.info(f"채널 ID 추출 성공: {channel_id}")
                    return channel_id
                
                # 방법 2: externalId 찾기
                external_id_pattern = re.compile(r'"externalId"\s*:\s*"([^"]+)"')
                match = external_id_pattern.search(html_content)
                if match:
                    channel_id = match.group(1)
                    logger.info(f"외부 ID를 통한 채널 ID 추출 성공: {channel_id}")
                    return channel_id
                
                # 방법 3: browseId 찾기
                browse_id_pattern = re.compile(r'"browseId"\s*:\s*"([^"]+)"')
                match = browse_id_pattern.search(html_content)
                if match:
                    browse_id = match.group(1)
                    if browse_id.startswith("UC"):
                        logger.info(f"browseId를 통한 채널 ID 추출 성공: {browse_id}")
                        return browse_id
                
                logger.warning(f"채널 페이지에서 채널 ID를 찾을 수 없습니다 (시도 {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                
        except httpx.TimeoutException:
            logger.warning(f"채널 페이지 요청 타임아웃 (시도 {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                
        except Exception as e:
            logger.error(f"채널 ID 추출 중 오류: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    logger.error(f"채널 ID 추출 실패: {channel_url}")
    return None

def parse_upload_date(upload_time_text: str) -> datetime:
    """
    YouTube 업로드 시간 텍스트를 실제 날짜로 변환합니다.
    예: "3일 전", "5시간 전" 등을 실제 날짜로 변환
    반환된 datetime에는 KST 시간대 정보가 포함됨
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Seoul"))  # 명시적으로 KST 시간대 사용
    
    if not upload_time_text:
        return now
    
    try:
        # "스트리밍 시간:" 접두어 제거
        if "스트리밍 시간:" in upload_time_text:
            upload_time_text = upload_time_text.replace("스트리밍 시간:", "").strip()
        
        # 숫자 추출
        number_match = re.search(r'(\d+)', upload_time_text)
        if not number_match:
            return now
        
        value = int(number_match.group(1))
        
        # 시간 단위에 따른 계산
        if "분 전" in upload_time_text or "minutes ago" in upload_time_text:
            return now - timedelta(minutes=value)
        elif "시간 전" in upload_time_text or "hours ago" in upload_time_text:
            return now - timedelta(hours=value)
        elif "일 전" in upload_time_text or "days ago" in upload_time_text:
            return now - timedelta(days=value)
        elif "주 전" in upload_time_text or "weeks ago" in upload_time_text:
            return now - timedelta(weeks=value)
        elif "개월 전" in upload_time_text or "months ago" in upload_time_text:
            return now - timedelta(days=value*30)
        elif "년 전" in upload_time_text or "years ago" in upload_time_text:
            return now - timedelta(days=value*365)
        else:
            # 직접적인 날짜 형식 처리 (예: "2024년 3월 13일")
            date_match = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일', upload_time_text)
            if date_match:
                year, month, day = map(int, date_match.groups())
                return datetime(year, month, day, tzinfo=ZoneInfo("Asia/Seoul"))
            
            # 영어 날짜 형식 처리 (예: "Mar 13, 2024")
            eng_date_match = re.search(r'([A-Za-z]{3})\s*(\d{1,2}),?\s*(\d{4})', upload_time_text)
            if eng_date_match:
                month_str, day, year = eng_date_match.groups()
                month_dict = {
                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                }
                month = month_dict.get(month_str, 1)
                return datetime(int(year), int(day), month, tzinfo=ZoneInfo("Asia/Seoul"))
    except Exception as e:
        logger.error(f"날짜 파싱 오류: {str(e)}")
    
    return now

async def find_latest_video_by_scraping(channel_url: str, keyword: str, max_retries: int = 3, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
    """
    웹 스크래핑을 사용하여 채널에서 키워드가 포함된 최신 영상을 찾습니다.
    
    Args:
        channel_url: YouTube 채널 URL
        keyword: 검색할 키워드
        max_retries: 최대 재시도 횟수
        timeout: 요청 타임아웃(초)
        
    Returns:
        최신 영상 정보 또는 None
    """
    logger.info(f"채널 URL 스크래핑 시작: {channel_url}, 키워드: {keyword}")
    
    # URL에 /videos 또는 /streams가 없으면 추가
    if not any(path in channel_url for path in ["/videos", "/streams"]):
        # 먼저 /streams 시도 (라이브 및 업로드된 영상 모두 포함)
        channel_url = f"{channel_url.rstrip('/')}/streams"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                logger.info(f"채널 페이지 요청 중 (시도 {attempt+1}/{max_retries})")
                response = await client.get(
                    channel_url, 
                    headers=headers, 
                    follow_redirects=True, 
                    timeout=timeout
                )
                response.raise_for_status()
                
                # YouTube의 초기 데이터 추출
                data = extract_initial_data(response.text)
                
                if not data:
                    logger.warning(f"YouTube 데이터를 추출할 수 없습니다 (시도 {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    else:
                        if "/streams" in channel_url:
                            # /streams가 실패하면 /videos로 재시도
                            new_url = channel_url.replace("/streams", "/videos")
                            logger.info(f"/streams 실패, /videos로 재시도: {new_url}")
                            return await find_latest_video_by_scraping(new_url, keyword, max_retries, timeout)
                        return None
                
                # 키워드가 포함된 비디오 찾기
                videos = find_videos_with_keyword(data, keyword)
                
                if not videos:
                    logger.warning(f"키워드 '{keyword}'가 포함된 영상을 찾을 수 없습니다 (시도 {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    else:
                        if "/streams" in channel_url:
                            # /streams가 실패하면 /videos로 재시도
                            new_url = channel_url.replace("/streams", "/videos")
                            logger.info(f"/streams 실패, /videos로 재시도: {new_url}")
                            return await find_latest_video_by_scraping(new_url, keyword, max_retries, timeout)
                        return None
                
                # 라이브, 예정, 일반 영상 분류
                live_videos = [v for v in videos if v.get("is_live", False)]
                upcoming_videos = [v for v in videos if v.get("is_upcoming", False)]
                normal_videos = [v for v in videos if not v.get("is_live", False) and not v.get("is_upcoming", False)]
                
                # 우선순위: 라이브 > 일반(5분 이상) > 예정
                if live_videos:
                    logger.info(f"라이브 중인 영상 발견: {live_videos[0]['title']}")
                    return live_videos[0]
                
                # 일반 영상 중 5분(300초) 이상인 것만 필터링
                filtered_normal_videos = [v for v in normal_videos if v.get("duration_seconds", 0) >= 300]
                
                if filtered_normal_videos:
                    logger.info(f"일반 영상(5분 이상) 발견: {filtered_normal_videos[0]['title']}")
                    return filtered_normal_videos[0]
                
                if upcoming_videos:
                    logger.info(f"라이브 예정 영상 발견: {upcoming_videos[0]['title']}")
                    return upcoming_videos[0]
                
                logger.warning("적합한 영상을 찾을 수 없습니다 (모두 5분 이하 또는 없음)")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    if "/streams" in channel_url:
                        # /streams가 실패하면 /videos로 재시도
                        new_url = channel_url.replace("/streams", "/videos")
                        logger.info(f"/streams 실패, /videos로 재시도: {new_url}")
                        return await find_latest_video_by_scraping(new_url, keyword, max_retries, timeout)
                    return None
                
        except httpx.TimeoutException:
            logger.warning(f"채널 페이지 요청 타임아웃 (시도 {attempt+1}/{max_retries})")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                if "/streams" in channel_url:
                    # /streams가 실패하면 /videos로 재시도
                    new_url = channel_url.replace("/streams", "/videos")
                    logger.info(f"/streams 실패, /videos로 재시도: {new_url}")
                    return await find_latest_video_by_scraping(new_url, keyword, max_retries, timeout)
                return None
                
        except Exception as e:
            logger.error(f"채널 스크래핑 중 오류: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                if "/streams" in channel_url:
                    # /streams가 실패하면 /videos로 재시도
                    new_url = channel_url.replace("/streams", "/videos")
                    logger.info(f"/streams 실패, /videos로 재시도: {new_url}")
                    return await find_latest_video_by_scraping(new_url, keyword, max_retries, timeout)
                return None
    
    logger.error(f"최대 재시도 횟수 초과: {channel_url}")
    return None

async def get_video_transcript(video_id: str, max_retries: int = 3) -> str:
    """비디오 ID로부터 자막을 가져옵니다."""
    logger.info(f"비디오 ID의 자막 가져오기: {video_id}")
    
    subtitles_disabled_error = "Subtitles are disabled for this video"
    
    for attempt in range(max_retries):
        try:
            # 한국어 자막 시도
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko"])
            logger.info(f"한국어 자막 {len(transcript_list)}개 항목 발견")
            return " ".join([entry["text"] for entry in transcript_list])
        except Exception as e:
            error_str = str(e)
            
            # 자막이 비활성화된 경우 (실제 오류가 아님)
            if subtitles_disabled_error in error_str:
                if attempt == 0:  # 첫 시도에서만 로그 출력
                    logger.info(f"이 영상에는 아직 자막이 업로드되지 않았습니다: {video_id}")
            else:
                # 다른 종류의 오류인 경우에만 경고 로그 출력
                logger.warning(f"한국어 자막 오류 (시도 {attempt+1}/{max_retries}): {error_str}")
            
            try:
                # 자동 언어 감지 시도
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                logger.info(f"자동 감지 언어로 자막 발견")
                return " ".join([entry["text"] for entry in transcript_list])
            except Exception as e2:
                error_str2 = str(e2)
                
                # 자막이 비활성화된 경우 (실제 오류가 아님)
                if subtitles_disabled_error in error_str2:
                    if attempt == 0:  # 첫 시도에서만 로그 출력
                        logger.info(f"이 영상에는 아직 자막이 업로드되지 않았습니다: {video_id}")
                else:
                    # 다른 종류의 오류인 경우에만 경고 로그 출력
                    logger.warning(f"자동 감지 자막 오류 (시도 {attempt+1}/{max_retries}): {error_str2}")
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    return "자막이 아직 업로드되지 않았습니다."
    
    return "자막이 아직 업로드되지 않았습니다."