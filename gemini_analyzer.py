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
                    model = "gemini-2.5-flash-preview-05-20"  # 최신 모델 사용
                    
                    # Content 객체 생성
                    contents = [
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=prompt)],
                        ),
                    ]
                    
                    # 시스템 지시사항 설정 - 종목 분석에 특화
                    system_instruction = f"""당신은 투자 전문가로서 한국주식 종목 분석을 담당합니다. 주어진 스크립트에서 매수 가치가 있는 종목들과 주의해야 할 종목들을 추출하여 정리해주세요.

다음 지침을 반드시 따르세요:

다음 세 가지 카테고리로 종목들을 분류하세요:
- 강력 추천 종목: 방송에서 적극적으로 매수를 권하거나, "적극 매수", "강력 추천", "꼭 사야 한다" 등의 표현을 사용한 종목
- 관심 종목: 긍정적으로 언급되었거나, "관심 가질만하다", "매력적이다", "기회가 될 수 있다" 등으로 표현된 종목
- 주의 종목: "지금 사면 위험하다", "매도하라", "비중 줄여라", "지금은 때가 아니다" 등으로 언급된 종목

각 카테고리를 대제목(#)으로 구분하고, 그 아래 종목들을 소제목(##)으로 나열하세요.

각 종목에 대해 다음 정보를 포함하세요:
- 언급 이유: 간결하게 1-2문장으로 설명
- 추천/주의 근거: 어떤 표현이나 이유로 추천/주의가 언급되었는지
- 핵심 포인트: 3-5개의 불릿 포인트로 핵심 정보만 요약

중요 규칙:
1. 오직 구체적인 개별 종목만 포함하세요. 종목명을 명확하게 언급하지 않은 섹터, 테마, 업종 등은 절대 포함하지 마세요.
2. 단순히 과거의 매매 성공 사례를 설명하기만 하고 현재 매수/매도 의견이 없는 종목은 제외하세요.
3. 종목명은 정확하게 작성하세요.
4. "화장품주", "건설 관련주" 같은 섹터나 그룹은 포함하지 말고 구체적인 회사명(예: 아모레퍼시픽, 현대건설)만 포함하세요.
5. 특정 카테고리에 해당하는 종목이 없으면 해당 카테고리는 생략하세요.

각 종목별 내용은 간결하게 유지하고, 불필요한 반복을 피하세요.
"""
                    
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