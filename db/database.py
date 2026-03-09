"""
SQLite 데이터베이스 연결 및 SQLAlchemy ORM 모델 정의
"""
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, Integer, Boolean, Text, DateTime, func

logger = logging.getLogger(__name__)

Base = declarative_base()

# ──────────────────────────────────────────────
# 모델 정의
# ──────────────────────────────────────────────
class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(255), unique=True, index=True) # 기존 Notion ID 유지용 (선택)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), nullable=True, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class VideoQueue(Base):
    __tablename__ = "video_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(255), unique=True, index=True) # 기존 Notion ID 유지용
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    video_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    channel_name: Mapped[str] = mapped_column(String(255), nullable=True)
    upload_date: Mapped[str] = mapped_column(String(255), nullable=True) # ISO format string
    video_length: Mapped[str] = mapped_column(String(50), nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=True)
    subtitle_status: Mapped[str] = mapped_column(String(50), default="미확인") # 미확인, Y, N
    analysis_needed: Mapped[str] = mapped_column(String(50), default="미정")   # 미정, 필요, 불필요
    analysis_done: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

class StockOpinion(Base):
    __tablename__ = "stock_opinions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[str] = mapped_column(String(255), unique=True, index=True) # 기존 Notion ID 유지용
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=True)
    normalization_status: Mapped[str] = mapped_column(String(50), default="미처리") # 미처리, 완료, 수동확인필요
    opinion_type: Mapped[str] = mapped_column(String(50), default="관심") # 추천, 관심, 주의
    recommender: Mapped[str] = mapped_column(String(255), nullable=True)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=True)
    upload_date: Mapped[str] = mapped_column(String(255), nullable=True) # ISO format string
    video_id: Mapped[str] = mapped_column(String(255), index=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now())

# ──────────────────────────────────────────────
# DB 세션 설정
# ──────────────────────────────────────────────
_engine = None
_async_session_maker = None

async def init_db(database_url: str):
    global _engine, _async_session_maker
    if _engine is None:
        _engine = create_async_engine(database_url, echo=False)
        _async_session_maker = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
        
        # 모델 생성을 위해 임시로 활성화 (운영 환경에서는 Alembic 등 마이그레이션 툴 권장)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"SQLite DB 초기화 완료: {database_url}")

def get_session_maker() -> async_sessionmaker[AsyncSession]:
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db first.")
    return _async_session_maker
