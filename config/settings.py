"""
중앙 설정 모듈
환경변수, Notion DB ID, LLM 모델, 스케줄링 주기 등 전체 설정을 관리합니다.
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class DatabaseConfig:
    """SQLite DB 관련 설정"""
    url: str = "sqlite+aiosqlite:///data/korea_stock.db"


@dataclass
class LLMConfig:
    """LLM 관련 설정 — provider/model만 바꾸면 모델 교체 완료"""
    provider: str = "gemini"          # "gemini" | "openai" | "anthropic"
    model: str = "gemini-2.5-flash"   # 모델명
    api_key: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192


@dataclass
class SchedulerConfig:
    """에이전트별 스케줄링 주기"""
    monitor_interval_minutes: int = 10
    filter_interval_minutes: int = 60
    filter_active_hour_start: int = 7
    filter_active_hour_end: int = 20
    report_interval_minutes: int = 5
    normalize_batch_size: int = 10
    normalize_interval_minutes: int = 60


@dataclass
class YouTubeConfig:
    """YouTube 스크래핑 관련 설정"""
    proxy_url: str = ""


@dataclass
class Settings:
    """전체 설정을 통합 관리하는 루트 설정 클래스"""
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    log_level: str = "INFO"


# ──────────────────────────────────────────────
# 싱글턴 설정 인스턴스
# ──────────────────────────────────────────────
_settings: Settings | None = None



def get_settings() -> Settings:
    """환경변수에서 설정을 로드하여 싱글턴 Settings 인스턴스를 반환합니다."""
    global _settings
    if _settings is not None:
        return _settings

    _settings = Settings(
        db=DatabaseConfig(
            url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/korea_stock.db"),
        ),
        llm=LLMConfig(
            provider=os.getenv("LLM_PROVIDER", "gemini"),
            model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            api_key=os.getenv("LLM_API_KEY", ""),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "8192")),
        ),
        scheduler=SchedulerConfig(
            monitor_interval_minutes=int(os.getenv("MONITOR_INTERVAL_MINUTES", "10")),
            filter_interval_minutes=int(os.getenv("FILTER_INTERVAL_MINUTES", "60")),
            filter_active_hour_start=int(os.getenv("FILTER_ACTIVE_HOUR_START", "7")),
            filter_active_hour_end=int(os.getenv("FILTER_ACTIVE_HOUR_END", "20")),
            report_interval_minutes=int(os.getenv("REPORT_INTERVAL_MINUTES", "5")),
            normalize_batch_size=int(os.getenv("NORMALIZE_BATCH_SIZE", "10")),
            normalize_interval_minutes=int(os.getenv("NORMALIZE_INTERVAL_MINUTES", "60")),
        ),
        youtube=YouTubeConfig(
            proxy_url=os.getenv("YOUTUBE_PROXY_URL", ""),
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
    return _settings


def reload_settings() -> Settings:
    """설정을 강제로 다시 로드합니다."""
    global _settings
    _settings = None
    load_dotenv(override=True)
    return get_settings()
