# Korea_Stock 파이프라인 재구축 계획

기존 단일-스케줄러 구조를 **4개 DB + 4개 에이전트 + 설정 기반 LLM** 구조로 전면 리팩터링합니다.

---

## 1. 새로운 코드 구조

```
Korea_Stock/
├── config/
│   ├── __init__.py
│   ├── settings.py          # 환경변수, DB ID, LLM 모델 등 중앙 설정
│   └── prompts.py           # LLM 프롬프트 템플릿 모음
├── db/
│   ├── __init__.py
│   ├── client.py            # Notion API 공통 클라이언트 (query, create, update)
│   ├── channels.py          # 채널 DB CRUD
│   ├── video_queue.py       # 영상 큐 DB CRUD
│   ├── reports.py           # 1차 보고서 DB CRUD
│   └── stock_opinions.py    # 종목의견 DB CRUD
├── agents/
│   ├── __init__.py
│   ├── channel_monitor.py   # ① 채널 모니터 에이전트
│   ├── filter_agent.py      # ② 필터링 에이전트
│   ├── report_agent.py      # ③ 보고서 생성 에이전트
│   └── normalize_agent.py   # ④ 정규화 에이전트
├── services/
│   ├── __init__.py
│   ├── youtube.py            # YouTube 스크래핑/API 통합
│   ├── transcript.py         # 자막 추출 서비스
│   └── llm.py                # LLM 호출 추상 레이어 (모델 교체 가능)
├── utils/
│   ├── __init__.py
│   ├── time_utils.py         # 시간 변환 (기존 유지)
│   └── notion_markdown.py    # 마크다운→노션 블록 변환 (기존 유지)
├── main.py                    # FastAPI 서버 + 스케줄러 등록
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

### 핵심 설계 원칙
- **관심사 분리**: DB 접근(`db/`), 비즈니스 로직(`agents/`), 외부 서비스(`services/`) 분리
- **설정 중앙화**: `config/settings.py`에서 모든 환경변수·모델명·주기 관리
- **LLM 교체 용이**: `services/llm.py`가 모델 추상 레이어 역할 → 설정만 바꾸면 모델 교체

---

## 2. 노션 DB 생성 가이드

사용자가 Notion에서 **4개 DB를 직접 생성**해야 합니다.

### DB 1: 채널 DB (`CHANNEL_DB_ID`)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| 채널명 | `title` | 채널 표시 이름 |
| URL | `url` | YouTube 채널 URL |
| 키워드 | `rich_text` | 검색 키워드 (영상 제목 매칭용) |
| 활성화 | `checkbox` | 모니터링 활성 여부 |

### DB 2: 영상 큐 DB (`VIDEO_QUEUE_DB_ID`)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| 제목 | `title` | 영상 제목 |
| 영상ID | `rich_text` | YouTube video ID |
| 채널명 | `select` | 출처 채널명 |
| 업로드시간 | `date` | 업로드 날짜/시간 (KST) |
| 영상길이 | `rich_text` | `"MM:SS"` 형식 |
| 원본링크 | `url` | YouTube URL |
| 자막상태 | `select` | `Y` / `N` / `미확인` |
| 분석필요 | `select` | `미정` / `필요` / `불필요` |
| 분석완료 | `checkbox` | 분석 완료 여부 |

### DB 3: 1차 보고서 DB (`REPORT_DB_ID`)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| 제목 | `title` | 보고서 제목 (프로그램명 + 날짜 등) |
| 원본영상ID | `rich_text` | 영상 큐 참조용 video ID |
| 프로그램명 | `rich_text` | 프로그램/키워드명 |
| 채널명 | `select` | 출처 채널 |
| 영상날짜 | `date` | 원본 영상 업로드 날짜 |
| 본문(페이지 body) | — | Notion 블록으로 작성 |

### DB 4: 종목의견 DB (`STOCK_OPINION_DB_ID`)

| 속성명 | 타입 | 설명 |
|--------|------|------|
| 원본_종목명 | `title` | 자막 원문 그대로의 종목명 |
| 정규화_종목명 | `rich_text` | 정규화 에이전트가 수정한 이름 (초기 빈값) |
| 정규화_상태 | `select` | `미처리` / `완료` / `수동확인필요` |
| 의견유형 | `select` | `추천` / `관심` / `주의` |
| 추천일자 | `date` | 영상 업로드 날짜 기준 |
| 추천인 | `rich_text` | 전문가명 또는 프로그램명 |
| 근거요약 | `rich_text` | 추천/관심/주의 근거 요약 (2000자 이내) |
| 원본영상ID | `rich_text` | 트레이서빌리티용 video ID |
| 원본보고서ID | `rich_text` | 1차 보고서 Notion page ID |

---

## 3. 설정 파일 (`config/settings.py`)

```python
class Settings:
    # Notion DB IDs
    CHANNEL_DB_ID: str
    VIDEO_QUEUE_DB_ID: str
    REPORT_DB_ID: str
    STOCK_OPINION_DB_ID: str

    # LLM 설정 — 여기만 바꾸면 모델 교체 완료
    LLM_PROVIDER: str       # "gemini" | "openai" | "anthropic"
    LLM_MODEL: str          # "gemini-2.5-flash" | "gpt-4o" | "claude-sonnet-4-20250514"
    LLM_API_KEY: str
    LLM_TEMPERATURE: float  # 기본 0
    LLM_MAX_TOKENS: int     # 기본 8192

    # 스케줄링 — 에이전트별 주기
    MONITOR_INTERVAL_MINUTES: int   # 10
    FILTER_INTERVAL_MINUTES: int    # 60
    FILTER_ACTIVE_HOURS: tuple      # (7, 20)
    NORMALIZE_BATCH_SIZE: int       # 10
    NORMALIZE_INTERVAL_MINUTES: int # 60
```

`.env.example`에 모든 키를 문서화합니다.

**모델 변경 방법**: `.env`에서 `LLM_PROVIDER`와 `LLM_MODEL`만 수정하면 됩니다.

---

## 4. 에이전트별 상세 로직

### ① 채널 모니터 (`agents/channel_monitor.py`) — 10분 주기

```
1. 채널 DB에서 활성화된 채널 목록 조회
2. 각 채널 URL → 스크래핑으로 최신 영상 목록 가져오기
3. 영상 큐 DB에 이미 등록된 영상ID인지 확인 (중복 스킵)
4. 새 영상 → 영상 큐 DB에 등록:
   - 자막상태: 자막 조회 시도 → Y/N/미확인
   - 분석필요: "미정"
   - 분석완료: False
5. 기존 "자막상태=미확인" 영상도 재확인
```

- AI 사용: ❌ (순수 스크래핑)
- 기존 코드 재사용: `youtube_scraper_utils.py` → `services/youtube.py`로 리팩터링

### ② 필터링 에이전트 (`agents/filter_agent.py`) — 1시간 주기, 07~20시

```
1. 영상 큐 DB에서 "분석필요=미정" 영상 조회
2. 각 영상에 대해:
   a. 자막상태=N → "미정" 유지, 스킵
   b. 영상길이 10분 이하 → "불필요"
   c. 제목+자막 앞부분을 LLM에 전달 → 분석 가치 판단
      - 시청자 전화상담, 증시 마감 브리핑 등 → "불필요"
      - 전문가 종목 분석 콘텐츠 → "필요"
3. 결과를 영상 큐 DB에 업데이트
```

- AI 사용: ✅ (제목+자막 앞부분 판단)

### ③ 보고서 생성 에이전트 (`agents/report_agent.py`) — 필터링 후 자동

```
1. 영상 큐 DB에서 "분석필요=필요" & "자막상태=Y" & "분석완료=False" 조회
2. 각 영상에 대해:
   a. 자막 전체 가져오기
   b. LLM으로 분석 → 추천/관심/주의 3분류 + 종목별 정보 추출
   c. 1차 보고서 DB에 페이지 생성 (본문 = 분석 보고서)
   d. 종목의견 DB에 각 종목별 레코드 생성 (raw 상태)
   e. 영상 큐의 분석완료 = True
```

- AI 사용: ✅ (핵심 분석)
- LLM 출력: JSON 구조화 응답 요청 → 종목의견 DB 레코드 자동 생성

### ④ 정규화 에이전트 (`agents/normalize_agent.py`) — 배치

```
트리거: "정규화_상태=미처리"가 10개 이상 OR 마지막 실행 후 1시간 경과
1. 기존 "정규화_상태=완료" 종목명 목록 추출 (캐시)
2. "미처리" 레코드들의 원본_종목명을 기존 목록과 비교
3. LLM으로 매칭 판단:
   - 매칭 확신 높음 → 정규화_종목명 채우고, 상태=완료
   - 매칭 확신 낮음 → 상태=수동확인필요
   - 완전 신규 → 원본_종목명 그대로 정규화_종목명에 넣고, 완료
```

- AI 사용: ✅ (종목명 매칭)

---

## 5. LLM 추상 레이어 (`services/llm.py`)

```python
class LLMService:
    """설정 기반으로 LLM provider를 분기하는 통합 레이어"""

    def __init__(self, settings: Settings):
        self.provider = settings.LLM_PROVIDER
        self.model = settings.LLM_MODEL

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """텍스트 생성 (공통 인터페이스)"""

    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        """JSON 구조화 응답 (보고서 에이전트용)"""
```

지원 예정 provider:
- `gemini` (기본): `google-genai` 패키지
- `openai`: `openai` 패키지
- `anthropic`: `anthropic` 패키지

---

## 6. 스케줄러 구성 (`main.py`)

```python
scheduler.add_job(channel_monitor.run, IntervalTrigger(minutes=10))
scheduler.add_job(filter_agent.run,    CronTrigger(minute=0, hour="7-20"))
scheduler.add_job(report_agent.run,    IntervalTrigger(minutes=5))
scheduler.add_job(normalize_agent.run, IntervalTrigger(minutes=10))
```

---

## 7. FastAPI 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| `GET` | `/` | 상태 확인 |
| `GET` | `/channels` | 채널 DB 목록 조회 |
| `GET` | `/queue` | 영상 큐 현황 조회 |
| `GET` | `/reports` | 보고서 목록 조회 |
| `GET` | `/opinions` | 종목의견 목록 조회 |
| `POST` | `/run/monitor` | 수동 채널 모니터링 실행 |
| `POST` | `/run/filter` | 수동 필터링 실행 |
| `POST` | `/run/report` | 수동 보고서 생성 실행 |
| `POST` | `/run/normalize` | 수동 정규화 실행 |
| `GET` | `/config` | 현재 설정값 조회 |

---

## 8. 에이전트 요약표

| 에이전트 | 역할 | 주기 | AI 사용 |
|----------|------|------|---------|
| 채널 모니터 | 새 영상 감지, 큐에 등록 | 10분 | ❌ (스크래핑) |
| 필터링 에이전트 | 분석 대상 여부 판단 | 1시간 (07~20시) | ✅ |
| 보고서 생성 에이전트 | 자막 → 종목 분석 보고서 | 필터링 후 자동 | ✅ |
| 정규화 에이전트 | 종목명 통일 및 정리 | 배치 (10개 or 1시간) | ✅ |

---

## 9. `.env.example` 예시

```env
# Notion API
NOTION_API_KEY=your_notion_api_key_here

# Notion DB IDs (4개 DB)
CHANNEL_DB_ID=your_channel_db_id
VIDEO_QUEUE_DB_ID=your_video_queue_db_id
REPORT_DB_ID=your_report_db_id
STOCK_OPINION_DB_ID=your_stock_opinion_db_id

# LLM 설정
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
LLM_API_KEY=your_llm_api_key_here
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=8192

# 스케줄링
MONITOR_INTERVAL_MINUTES=10
FILTER_INTERVAL_MINUTES=60
FILTER_ACTIVE_HOUR_START=7
FILTER_ACTIVE_HOUR_END=20
NORMALIZE_BATCH_SIZE=10
NORMALIZE_INTERVAL_MINUTES=60
```
