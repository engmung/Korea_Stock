"""
시간 처리를 위한 유틸리티 함수들
다양한 형식의 시간 입력을 처리하고 일관된 KST 시간으로 변환
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Union
from zoneinfo import ZoneInfo

# KST 시간대 정의
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc

def parse_iso_datetime(iso_str: str) -> Optional[datetime]:
    """
    ISO 8601 형식 문자열을 datetime 객체로 변환
    
    Args:
        iso_str: ISO 8601 형식의 날짜/시간 문자열 (예: "2024-04-15T12:30:45Z")
        
    Returns:
        datetime 객체 또는 None (파싱 실패 시)
    """
    try:
        # 'Z' 표기는 UTC를 의미 - '+00:00'으로 대체
        if 'Z' in iso_str:
            iso_str = iso_str.replace('Z', '+00:00')
            
        # ISO 문자열 파싱 - timezone 정보 보존
        dt = datetime.fromisoformat(iso_str)
        
        # timezone 정보가 없는 경우 UTC로 가정
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
            
        return dt
    except Exception as e:
        print(f"ISO 날짜 파싱 오류: {str(e)}")
        return None

def convert_to_kst_datetime(time_input: Union[str, datetime, None]) -> datetime:
    """
    다양한 형식의 시간 입력을 KST 시간대 datetime 객체로 변환
    
    Args:
        time_input: 시간 정보 (ISO 문자열, datetime 객체 또는 None)
        
    Returns:
        KST 시간대의 datetime 객체
    """
    # 입력이 없으면 현재 시간 사용
    if time_input is None:
        return datetime.now(KST)
    
    # 이미 datetime 객체인 경우
    if isinstance(time_input, datetime):
        dt = time_input
        # timezone 정보가 없는 경우 UTC로 가정
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        # KST로 변환하여 반환
        return dt.astimezone(KST)
    
    # 문자열 입력인 경우
    if isinstance(time_input, str):
        # 문자열이 비어있으면 현재 시간 사용
        if not time_input.strip():
            return datetime.now(KST)
        
        # ISO 형식으로 가정하고 파싱 시도
        dt = parse_iso_datetime(time_input)
        if dt:
            return dt.astimezone(KST)
    
    # 모든 처리 실패 시 현재 시간 반환
    return datetime.now(KST)

def format_for_notion(dt: datetime) -> str:
    """
    datetime 객체를 Notion API 형식으로 변환
    
    Args:
        dt: datetime 객체
        
    Returns:
        Notion API 형식의 날짜/시간 문자열
    """
    # timezone이 없는 경우 KST로 가정
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    
    # KST로 변환
    dt_kst = dt.astimezone(KST)
    
    # Notion API 형식으로 포맷팅 (ISO 8601 + KST 오프셋)
    return dt_kst.isoformat()

def get_notion_date_property(time_input: Union[str, datetime, None]) -> dict:
    """
    시간 입력을 Notion 날짜 속성 형식으로 변환
    
    Args:
        time_input: 시간 정보 (ISO 문자열, datetime 객체 또는 None)
        
    Returns:
        Notion API 날짜 속성 딕셔너리
    """
    dt_kst = convert_to_kst_datetime(time_input)
    return {
        "date": {
            "start": format_for_notion(dt_kst)
        }
    }