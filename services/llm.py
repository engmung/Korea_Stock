"""
LLM 추상 레이어
config/settings.py의 LLM_PROVIDER / LLM_MODEL 설정에 따라
Gemini, OpenAI, Anthropic 중 하나를 사용합니다.
"""
import json
import logging
import asyncio
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from config.settings import get_settings, LLMConfig

logger = logging.getLogger(__name__)

# 요청 제한: 동시 2개까지
_SEMAPHORE = asyncio.Semaphore(2)


class LLMService:
    """설정 기반 LLM 통합 레이어"""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or get_settings().llm
        self.provider = self.config.provider.lower()
        self.model = self.config.model
        logger.info(f"LLM 초기화: provider={self.provider}, model={self.model}")

    # ──────────────────────────────────────────
    # 텍스트 생성 (공통 인터페이스)
    # ──────────────────────────────────────────
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """텍스트 생성. provider에 따라 분기합니다."""
        async with _SEMAPHORE:
            if self.provider == "gemini":
                return await self._generate_gemini(system_prompt, user_prompt)
            elif self.provider == "openai":
                return await self._generate_openai(system_prompt, user_prompt)
            elif self.provider == "anthropic":
                return await self._generate_anthropic(system_prompt, user_prompt)
            else:
                raise ValueError(f"지원하지 않는 LLM provider: {self.provider}")

    # ──────────────────────────────────────────
    # JSON 구조화 응답
    # ──────────────────────────────────────────
    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        """JSON 파싱이 포함된 텍스트 생성."""
        raw = await self.generate(system_prompt, user_prompt)
        return _parse_json_response(raw)

    # ──────────────────────────────────────────
    # Pydantic 기반 구조화 응답 (Gemini structured output)
    # ──────────────────────────────────────────
    T = TypeVar("T", bound=BaseModel)

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type["LLMService.T"],
    ) -> "LLMService.T":
        """
        Pydantic 모델 기반 구조화 응답.
        Gemini의 response_json_schema를 사용하여 타입 안전한 JSON 응답을 받습니다.
        """
        async with _SEMAPHORE:
            if self.provider == "gemini":
                return await self._generate_gemini_structured(system_prompt, user_prompt, response_model)
            else:
                # 다른 provider는 기존 generate_json 후 Pydantic 파싱
                raw = await self.generate(system_prompt, user_prompt)
                parsed = _parse_json_response(raw)
                return response_model.model_validate(parsed)

    # ──────────────────────────────────────────
    # Gemini
    # ──────────────────────────────────────────
    async def _generate_gemini(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai 패키지가 필요합니다: pip install google-genai")

        def _call():
            client = genai.Client(api_key=self.config.api_key)
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_prompt)],
                )
            ]
            config = types.GenerateContentConfig(
                temperature=self.config.temperature,
                top_p=0.1,
                top_k=64,
                response_mime_type="text/plain",
                system_instruction=[types.Part.from_text(text=system_prompt)],
            )

            response_text = ""
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    response_text += chunk.text
            return response_text

        return await asyncio.to_thread(_call)

    async def _generate_gemini_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
    ) -> BaseModel:
        """Gemini structured output: Pydantic 스키마 기반 JSON 응답"""
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai 패키지가 필요합니다: pip install google-genai")

        def _call():
            client = genai.Client(api_key=self.config.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json",
                    "response_json_schema": response_model.model_json_schema(),
                    "temperature": self.config.temperature,
                },
            )
            return response_model.model_validate_json(response.text)

        return await asyncio.to_thread(_call)

    # ──────────────────────────────────────────
    # OpenAI
    # ──────────────────────────────────────────
    async def _generate_openai(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai 패키지가 필요합니다: pip install openai")

        def _call():
            client = OpenAI(api_key=self.config.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            return response.choices[0].message.content or ""

        return await asyncio.to_thread(_call)

    # ──────────────────────────────────────────
    # Anthropic
    # ──────────────────────────────────────────
    async def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError("anthropic 패키지가 필요합니다: pip install anthropic")

        def _call():
            client = Anthropic(api_key=self.config.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=self.config.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text

        return await asyncio.to_thread(_call)


# ──────────────────────────────────────────────
# JSON 파싱 헬퍼
# ──────────────────────────────────────────────
def _parse_json_response(raw: str) -> dict:
    """LLM 응답에서 JSON을 추출합니다. 코드블록 래핑도 처리합니다."""
    text = raw.strip()

    # ```json ... ``` 코드블록 제거
    if text.startswith("```"):
        lines = text.split("\n")
        # 첫 줄(```json)과 마지막 줄(```) 제거
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSON 부분만 추출 시도
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.error(f"JSON 파싱 실패: {text[:200]}...")
        return {"error": "JSON 파싱 실패", "raw": text}


# ──────────────────────────────────────────────
# 싱글턴 편의 함수
# ──────────────────────────────────────────────
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """싱글턴 LLMService 인스턴스를 반환합니다."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
