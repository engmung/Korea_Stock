import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import Dict, Any, List, Optional

from notion_utils import (
    query_notion_database, 
    update_notion_page, 
    check_script_exists, 
    create_script_report_page,
    check_recent_scripts_for_title,
    reset_all_channels,
    REFERENCE_DB_ID, 
    SCRIPT_DB_ID
)
from youtube_api_utils import get_channel_id_from_url, is_shorts
from youtube_scraper_utils import find_latest_video_by_scraping, get_video_transcript, parse_upload_date
from gemini_analyzer import analyze_script_with_gemini
from time_utils import convert_to_kst_datetime, get_notion_date_property

# 글로벌 스케줄러 인스턴스
scheduler = None

async def process_channel(page: Dict[str, Any]) -> bool:
    """특정 채널 페이지를 처리하여 새 스크립트를 생성합니다."""
    try:
        # 페이지 속성 가져오기
        properties = page.get("properties", {})
        page_id = page.get("id")
        
        # 활성화 상태 확인
        is_active = False
        active_property = properties.get("활성화", {})
        if "checkbox" in active_property:
            is_active = active_property["checkbox"]
        
        # 활성화되지 않은 항목은 건너뛰기
        if not is_active:
            print("비활성화된 채널입니다. 스킵합니다.")
            return False
        
        # 제목(키워드) 가져오기
        keyword = ""
        title_property = properties.get("제목", {})
        if "title" in title_property and title_property["title"]:
            keyword = title_property["title"][0]["plain_text"].strip()
        
        # URL 가져오기
        channel_url = ""
        url_property = properties.get("URL", {})
        if "url" in url_property:
            channel_url = url_property["url"]
        
        # 채널명 가져오기
        channel_name = "기타"
        channel_property = properties.get("채널명", {})
        if "select" in channel_property and channel_property["select"]:
            channel_name = properties["채널명"]["select"]["name"]
        
        if not channel_url or not keyword:
            print(f"채널 URL 또는 키워드가 없습니다. 스킵합니다.")
            return False
        
        # 유튜브 채널 URL이 아니면 스킵
        if "youtube.com/" not in channel_url:
            print(f"유효한 YouTube 채널 URL이 아닙니다: {channel_url}")
            return False
        
        print(f"Processing channel: {channel_url} with keyword: {keyword}")
        
        # 스크래핑을 통해 최신 영상 찾기
        latest_video = await find_latest_video_by_scraping(channel_url, keyword)
        
        if not latest_video:
            print(f"채널에서 키워드가 포함된 적합한 영상을 찾을 수 없습니다: {channel_url}")
            return False

        # 라이브 예정(Upcoming) 또는 라이브 중(Live) 영상인 경우 처리하지 않고 활성화 상태 유지
        if latest_video.get("is_upcoming", False) or latest_video.get("is_live", False):
            status = "라이브 예정" if latest_video.get("is_upcoming", False) else "라이브 중"
            print(f"{status} 영상입니다: {latest_video['title']}. 활성화 상태 유지하고 다음에 다시 확인합니다.")
            return False

        # 이미 스크립트가 있는지 영상 URL로 확인
        if await check_script_exists(latest_video["url"]):
            print(f"이미 스크립트가 존재합니다: {latest_video['title']}")
            return False  # 활성화 유지

        # 최근 5일 이내의 스크립트 중 동일한 프로그램의 동일한 영상이 이미 처리되었는지 확인
        five_days_ago = datetime.now() - timedelta(days=5)
        if await check_recent_scripts_for_title(keyword, latest_video["url"], five_days_ago.isoformat()):
            print(f"최근 5일 이내에 동일한 프로그램의 동일한 영상이 이미 처리되었습니다: {latest_video['title']}")
            return False  # 활성화 유지
        
        # 스크립트 가져오기
        script = await get_video_transcript(latest_video["video_id"])
        
        if not script or script.strip() == "자막이 아직 업로드되지 않았습니다." or script.startswith("스크립트를 가져올 수 없습니다"):
            print(f"자막이 아직 업로드되지 않았습니다: {latest_video['title']}")
            return False  # 활성화 유지
        
        # 업로드 날짜/시간 변환 - 상대적 시간 텍스트를 실제 날짜로 변환
        upload_time_text = latest_video.get("upload_date", "")
        print(f"원본 업로드 시간 텍스트: {upload_time_text}")
        
        # 상대적 시간 텍스트를 datetime 객체로 변환 (이미 KST 시간대 정보 포함)
        upload_datetime = parse_upload_date(upload_time_text)
        print(f"변환된 업로드 시간(datetime): {upload_datetime}")
        
        # 이미 KST 시간대가 포함된 datetime을 Notion 날짜 속성으로 직접 변환
        # KST 중복 변환을 방지하기 위해 datetime 객체를 직접 사용
        upload_date_property = {
            "date": {
                "start": upload_datetime.isoformat()
            }
        }
        
        # 스크립트 DB에 새 페이지 생성 (속성 설정)
        properties = {
            # 제목은 참고용 DB의 키워드 사용 (중요: 프로그램 제목으로 사용)
            "제목": {
                "title": [
                    {
                        "text": {
                            "content": keyword
                        }
                    }
                ]
            },
            # URL 속성 (기존의 원본 영상)
            "URL": {
                "url": latest_video["url"]
            },
            # 영상 날짜 - 상대적 시간을 변환한 날짜 속성
            "영상 날짜": upload_date_property,
            # 채널명 속성
            "채널명": {
                "select": {
                    "name": channel_name
                }
            },
            # 영상 길이 속성 추가
            "영상 길이": {
                "rich_text": [
                    {
                        "text": {
                            "content": latest_video.get("video_length", "알 수 없음")
                        }
                    }
                ]
            },
            # 인용 횟수 초기화
            "인용 횟수": {
                "number": 0
            },
            # 출연자 정보
            "출연자": {
                "multi_select": []  # 초기에는 비어있음, 필요시 채울 수 있음
            }
        }
        
        # 디버깅 정보 로깅 (KST 중복 변환 없이 직접 사용)
        print(f"Creating page for video: {latest_video['title']}")
        print(f"Keyword: {keyword}, Channel: {channel_name}")
        print(f"Upload date (KST): {upload_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        try:
            # Gemini로 스크립트 분석 - 스크립트는 분석에만 사용하고 결과에는 포함하지 않음
            print(f"Gemini API로 스크립트 분석 시작: {latest_video['title']}")
            analysis = await analyze_script_with_gemini(script, latest_video['title'], channel_name, keyword)
            
            # 분석 결과 확인 - 오류 포함 여부 체크
            if "분석 오류" in analysis or "## 오류" in analysis:
                print(f"AI 분석 중 오류가 발생했습니다: {analysis}")
                # 오류가 있는 경우 페이지 생성 중단
                return False
            
            # 분석 결과만 사용 (원본 스크립트 제외)
            combined_content = analysis
            print("AI 분석 보고서가 성공적으로 생성되었습니다.")
        except Exception as e:
            print(f"AI 분석 중 오류 발생: {str(e)}")
            # 분석 실패 시 페이지 생성하지 않음
            print("AI 분석에 실패했습니다. 페이지를 생성하지 않습니다.")
            return False
        
        # 수정된 내용으로 페이지 생성
        script_page = await create_script_report_page(SCRIPT_DB_ID, properties, combined_content)
        
        if script_page:
            print(f"스크립트+보고서 페이지 생성 완료: {latest_video['title']}")
            return True
        else:
            print(f"스크립트+보고서 페이지 생성 실패: {latest_video['title']}")
            return False
        
    except Exception as e:
        print(f"채널 처리 중 오류: {str(e)}")
        return False

async def process_channels_without_time_check() -> None:
    """
    활성화된 모든 채널을 처리합니다. 시간대 설정과 무관하게 실행됩니다.
    이 함수는 /sync-channels 엔드포인트에서 호출됩니다.
    """
    print("시간대 무관 채널 처리 시작 - 활성화된 모든 채널 대상")
    
    try:
        # 참고용 DB의 모든 채널 가져오기
        reference_pages = await query_notion_database(REFERENCE_DB_ID)
        print(f"참고용 DB에서 {len(reference_pages)}개의 채널을 가져왔습니다.")
        
        # 활성화된 채널만 선택 (시간대 체크 안 함)
        active_channels = []
        
        for page in reference_pages:
            properties = page.get("properties", {})
            
            # 활성화 상태 확인
            is_active = False
            active_property = properties.get("활성화", {})
            if "checkbox" in active_property:
                is_active = active_property["checkbox"]
            
            if is_active:
                channel_name = "기타"
                if "채널명" in properties and "select" in properties["채널명"] and properties["채널명"]["select"]:
                    channel_name = properties["채널명"]["select"]["name"]
                
                print(f"채널 '{channel_name}'은 활성화되어 있어 처리 대상입니다.")
                active_channels.append(page)
        
        print(f"처리할 활성화된 채널 {len(active_channels)}개를 찾았습니다.")
        
        if not active_channels:
            print(f"처리할 활성화된 채널이 없습니다.")
            return
        
        # 채널 처리 - API 제한 고려하여 순차적으로 처리
        success_count = 0
        
        for index, channel_page in enumerate(active_channels):
            try:
                channel_name = "Unknown"
                properties = channel_page.get("properties", {})
                if "채널명" in properties and "select" in properties["채널명"] and properties["채널명"]["select"]:
                    channel_name = properties["채널명"]["select"]["name"]
                    
                print(f"채널 처리 시작 ({index+1}/{len(active_channels)}): {channel_name}")
                success = await process_channel(channel_page)
                
                if success:
                    success_count += 1
                    print(f"채널 처리 성공: {channel_name}")
                else:
                    print(f"채널 처리 실패 또는 스킵: {channel_name}")
                    
                # 다음 채널 처리 전 대기
                # 마지막 항목이 아니면 대기
                if index < len(active_channels) - 1:
                    print(f"API 제한 준수를 위해 2초 대기 중...")
                    await asyncio.sleep(2)
                    
            except Exception as e:
                print(f"채널 처리 중 예외 발생: {str(e)}")
                # 다음 채널 처리 전 대기
                if index < len(active_channels) - 1:
                    print(f"오류 후 API 제한 준수를 위해 2초 대기 중...")
                    await asyncio.sleep(2)
        
        print(f"처리 완료: {success_count}/{len(active_channels)} 채널 성공")
    except Exception as e:
        print(f"process_channels_without_time_check 실행 중 오류: {str(e)}")

async def reset_channels_daily() -> None:
    """매일 모든 채널을 활성화 상태로 초기화합니다."""
    print("모든 채널 활성화 작업 시작")
    success = await reset_all_channels()
    
    if success:
        print("모든 채널이 성공적으로 활성화되었습니다.")
    else:
        print("일부 또는 모든 채널의 활성화에 실패했습니다.")

def run_async_task(coroutine):
    """비동기 코루틴을 새 이벤트 루프에서 실행합니다."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()

async def simulate_scheduler_at_time(time_setting: int, simulate_only: bool = True) -> Dict[str, Any]:
    """특정 시간 설정에 대한 작업 시뮬레이션"""
    print(f"시간 설정 {time_setting}에 대한 작업 시뮬레이션")
    
    try:
        # 참고용 DB의 모든 채널 조회
        reference_pages = await query_notion_database(REFERENCE_DB_ID)
        print(f"테스트: {len(reference_pages)}개의 채널을 가져왔습니다.")
        
        # 활성화된 채널 찾기
        active_channels = []
        for page in reference_pages:
            properties = page.get("properties", {})
            
            # 활성화 상태 확인
            is_active = False
            active_property = properties.get("활성화", {})
            if "checkbox" in active_property:
                is_active = active_property["checkbox"]
            
            if not is_active:
                continue
            
            # 채널명과 키워드 가져오기
            channel_name = "기타"
            if "채널명" in properties and "select" in properties["채널명"] and properties["채널명"]["select"]:
                channel_name = properties["채널명"]["select"]["name"]
            
            keyword = ""
            if "제목" in properties and "title" in properties["제목"] and properties["제목"]["title"]:
                keyword = properties["제목"]["title"][0]["plain_text"].strip()
            
            print(f"채널 '{channel_name}'은 활성화되어 있어 처리 대상입니다.")
            
            active_channels.append({
                "channel_name": channel_name,
                "keyword": keyword,
                "page_id": page.get("id"),
                "page": page
            })
        
        print(f"시뮬레이션: 활성화된 채널 {len(active_channels)}개 찾음")
        
        if not simulate_only and active_channels:
            # 실제 실행 모드
            print("실제 채널 처리 실행 시작")
            for i, channel in enumerate(active_channels):
                print(f"채널 처리 중 ({i+1}/{len(active_channels)}): {channel['channel_name']}")
                await process_channel(channel["page"])
                
                # 마지막 항목이 아니면 API 제한을 위해 대기
                if i < len(active_channels) - 1:
                    print("API 제한을 위해 2초 대기")
                    await asyncio.sleep(2)
            
            print("모든 채널 처리 완료")
        
        return {
            "time_setting": time_setting,
            "active_channels": [
                {
                    "channel_name": c["channel_name"],
                    "keyword": c["keyword"]
                } for c in active_channels
            ],
            "total_active": len(active_channels),
            "simulate_only": simulate_only
        }
    except Exception as e:
        print(f"시뮬레이션 중 오류 발생: {str(e)}")
        return {
            "time_setting": time_setting,
            "error": str(e),
            "simulate_only": simulate_only
        }

def setup_scheduler() -> AsyncIOScheduler:
    """스케줄러를 설정하고 작업을 예약합니다."""
    global scheduler
    
    if scheduler is not None:
        scheduler.shutdown()
    
    scheduler = AsyncIOScheduler()
    
    # 새벽 4시 30분에 모든 채널 초기화
    scheduler.add_job(
        lambda: run_async_task(reset_channels_daily()),
        CronTrigger(hour=4, minute=30),
        id="reset_channels_daily",
        replace_existing=True
    )
    
    # 지정된 시간에 활성화된 채널 처리 (모두 30분에 실행)
    check_times = [1, 5, 8, 9, 10, 14, 16, 17, 19, 20]  # 새벽 1시, 새벽 5시, 오전 11시, 오후 4시, 오후 8시
    
    for hour in check_times:
        scheduler.add_job(
            lambda: run_async_task(process_channels_without_time_check()),
            CronTrigger(hour=hour, minute=30),
            id=f"process_active_channels_{hour}",
            replace_existing=True
        )
    
    # 스케줄러 시작
    scheduler.start()
    print("Scheduler has been set up and is running.")
    print(f"활성화된 채널 확인 시간: {', '.join([f'{hour}시 30분' for hour in check_times])}")
    
    return scheduler