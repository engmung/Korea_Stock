import os
import asyncio
import logging
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# 요청 제한 관리를 위한 세마포어
# 1분당 최대 2개의 요청 허용
API_SEMAPHORE = asyncio.Semaphore(2)
API_RATE_LIMIT_SECONDS = 60  # 1분 딜레이

async def analyze_script_with_gemini(script: str, video_title: str, channel_name: str, program_name: str = "") -> str:
    """
    Gemini API를 사용하여 스크립트를 분석하고 마크다운 보고서를 생성합니다.
    
    Args:
        script: 분석할 유튜브 스크립트
        video_title: 영상 제목
        channel_name: 채널명
        program_name: 프로그램명 (제목에 표시됨)
    
    Returns:
        마크다운 형식의 분석 보고서 또는 오류 시 오류 메시지
    """
    try:
        # API 키 설정
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.error("GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
            return f"# [분석 오류] {program_name} - 주식 종목 분석 보고서\n\n## 오류 내용\n\nGEMINI_API_KEY 환경 변수가 설정되지 않았습니다."
        
        # 프롬프트 작성 - 주식 종목 분석에 특화된 프롬프트
        prompt = f"""# 주식 종목 분석 요청

제목: {video_title}
채널: {channel_name}
프로그램명: {program_name}
"""

        # 비동기적으로 Gemini API 호출 (API 제한 고려)
        async with API_SEMAPHORE:
            logger.info(f"Gemini API 호출 시작: {video_title}")
            
            # API 호출 전 타임스탬프 기록
            start_time = asyncio.get_event_loop().time()
            
            # 프로세스 시작
            def call_gemini():
                try:
                    client = genai.Client(api_key=api_key)
                    model = "gemini-2.5-flash"  # 최신 모델 사용
                    
                    # Content 객체 생성
                    contents = [
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=prompt)],
                        ),
                    ]
                    
                    # 시스템 지시사항 설정 - 종목 분석에 특화
                    system_instruction = f"""<role>
당신은 15년 경력의 한국 주식 투자 전문가입니다. 증권 방송 및 리포트 분석에 특화되어 있으며, 종목별 투자 의견을 정확하게 추출하는 전문가입니다.
</role>

<task>
주어진 투자 방송 스크립트를 분석하여 구체적인 개별 종목의 투자 의견을 추출하고 분류해주세요.
</task>

<analysis_process>
1단계: 스크립트 전체를 읽고 언급된 모든 개별 종목명을 식별
2단계: 각 종목에 대한 투자 의견과 근거를 파악
3단계: 투자 의견의 강도에 따라 카테고리 분류
4단계: 구조화된 형식으로 정리
</analysis_process>

<classification_criteria>
**강력 추천 종목**: 다음 표현이 사용된 종목
- "적극 매수", "강력 추천", "꼭 사야 한다", "지금이 기회"
- "놓치면 안 된다", "반드시 보유", "확신한다"

**관심 종목**: 다음 표현이 사용된 종목
- "관심 가질만하다", "매력적이다", "기회가 될 수 있다"
- "지켜볼 종목", "긍정적으로 본다", "유망하다"

**주의 종목**: 다음 표현이 사용된 종목
- "지금 사면 위험하다", "매도하라", "비중 줄여라"
- "지금은 때가 아니다", "주의가 필요하다", "위험하다"
</classification_criteria>

<output_format>
각 카테고리를 대제목(#)으로 구분하고, 종목들을 소제목(##)으로 나열하세요.

각 종목마다 다음 구조로 작성:
- **언급 이유**: [1-2문장으로 간결하게]
- **투자 의견 근거**: "[정확한 인용문]" - 실제 사용된 표현
- **핵심 포인트**:
  • [포인트 1]
  • [포인트 2]
  • [포인트 3]
</output_format>

<strict_rules>
1. **개별 종목만 포함**: 종목명(예: 삼성전자, SK하이닉스)이 명확하게 언급된 경우만 포함
2. **섹터/테마 제외**: "반도체주", "화장품주", "건설 관련주" 등은 절대 포함 금지
3. **현재 의견만 포함**: 과거 성공 사례만 언급하고 현재 투자 의견이 없는 종목은 제외
4. **정확한 종목명**: 종목명을 정확하게 작성 (예: "삼성전자" O, "삼성" X)
5. **해당 없음 처리**: 특정 카테고리에 종목이 없으면 해당 카테고리 전체 생략
</strict_rules>

<example>
# 강력 추천 종목

## 삼성전자
- **언급 이유**: 4분기 실적 개선과 메모리 반도체 회복세로 강력한 매수 기회
- **투자 의견 근거**: "삼성전자는 지금이 적극 매수 타이밍이다"
- **핵심 포인트**:
  • 메모리 반도체 가격 상승 전환점
  • 4분기 실적 깜짝 상승 예상
  • 배당 수익률 매력적

# 관심 종목

## LG에너지솔루션
- **언급 이유**: 전기차 시장 성장에 따른 배터리 수요 증가 기대
- **투자 의견 근거**: "LG에너지솔루션은 관심 가질만한 종목이다"
- **핵심 포인트**:
  • 북미 전기차 시장 확대
  • 신규 고객사 확보
  • 기술력 우위 지속
</example>

이제 주어진 스크립트를 분석해주세요:"""
                    
                    generate_content_config = types.GenerateContentConfig(
                        temperature=0,  # 결정적인 출력을 위해 0으로 설정
                        top_p=0.1,      # 가장 확률이 높은 토큰들만 고려
                        top_k=64,       # 선택 후보 토큰 수는 유지
                        response_mime_type="text/plain",
                        system_instruction=[types.Part.from_text(text=system_instruction)],
                    )
                    
                    # 스트리밍 응답 수집
                    response_text = ""
                    
                    # 스크립트를 분석에 사용
                    full_prompt = f"{prompt}\n\n스크립트 내용:\n{script}"
                    contents[0].parts[0].text = full_prompt
                    
                    for chunk in client.models.generate_content_stream(
                        model=model,
                        contents=contents,
                        config=generate_content_config,
                    ):
                        if chunk.text:
                            response_text += chunk.text
                    
                    return response_text
                except Exception as e:
                    logger.error(f"Gemini 함수 내 오류: {str(e)}")
                    return f"# [분석 오류] {program_name} - 주식 종목 분석 보고서\n\n## 오류 내용\n\nGemini API 호출 중 오류가 발생했습니다: {str(e)}"
            
            # 비동기적으로 API 호출 실행
            try:
                response_text = await asyncio.to_thread(call_gemini)
            except Exception as e:
                logger.error(f"asyncio.to_thread 오류: {str(e)}")
                return f"# [분석 오류] {program_name} - 주식 종목 분석 보고서\n\n## 오류 내용\n\nasyncio.to_thread 실행 중 오류가 발생했습니다: {str(e)}"
            
            # API 호출 후 경과 시간 계산
            elapsed_time = asyncio.get_event_loop().time() - start_time
            # 1분에서 경과 시간을 뺀 만큼 대기 (최소 0초)
            wait_time = max(0, API_RATE_LIMIT_SECONDS - elapsed_time)
            
            if wait_time > 0:
                logger.info(f"API 제한 준수를 위해 {wait_time:.1f}초 대기")
                await asyncio.sleep(wait_time)
            
            if response_text:
                # 오류 메시지가 포함되었는지 확인
                if "분석 오류" in response_text or "오류 내용" in response_text:
                    logger.error("Gemini 분석 오류 발생")
                    return response_text
                
                logger.info("Gemini 분석 완료")
                
                # 응답이 마크다운 형식인지 확인하고 수정
                if not response_text.startswith("# "):
                    response_text = f"# {program_name} - 주식 종목 분석 보고서\n\n" + response_text
                
                # 마크다운 형식 일관성 개선
                response_text = clean_markdown_format(response_text)
                
                return response_text
            else:
                logger.error("Gemini가 빈 응답을 반환했습니다.")
                return f"# [분석 오류] {program_name} - 주식 종목 분석 보고서\n\n## 오류 내용\n\nGemini API가 응답을 생성하지 못했습니다."
            
    except Exception as e:
        logger.error(f"Gemini API 호출 중 오류 발생: {str(e)}")
        return f"# [분석 오류] {program_name} - 주식 종목 분석 보고서\n\n## 오류 내용\n\nGemini API 호출 중 오류가 발생했습니다: {str(e)}"


def clean_markdown_format(text: str) -> str:
    """마크다운 형식을 정리하고 일관성을 높입니다."""
    lines = text.split('\n')
    result_lines = []
    
    # 불릿 포인트 형식 일관화 (* -> -)
    for i, line in enumerate(lines):
        # 불릿 포인트 일관화
        if line.strip().startswith('* '):
            line = line.replace('* ', '- ', 1)
        
        # 줄바꿈 개선: 제목 앞에는 빈 줄 추가
        if line.startswith('#') and i > 0 and lines[i-1].strip():
            result_lines.append('')
        
        # 현재 줄 추가
        result_lines.append(line)
        
        # 줄바꿈 개선: 제목 뒤에는 빈 줄 추가
        if line.startswith('#') and i < len(lines) - 1 and lines[i+1].strip() and not lines[i+1].startswith('#'):
            result_lines.append('')
    
    return '\n'.join(result_lines)