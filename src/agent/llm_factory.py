"""llm_factory.py - MODEL_PROVIDER 환경 변수로 실제 LLM 제공자(Bedrock/Google AI Studio)를 고른다.

AX 교육 기간에는 Bedrock 계정을 쓰지만, 교육이 끝나면 Bedrock 접근이 끊긴다. 그때 기존 코드를
건드리지 않고 .env에 MODEL_PROVIDER=google, GOOGLE_API_KEY만 설정하면 Google AI Studio(Gemini)
로 전환해서 계속 동작하도록 만든 대체 경로다(architectures/0014 참고). 기본값은 bedrock이라
지금까지의 동작은 그대로 유지된다.
"""

import os
from typing import Any

from dotenv import load_dotenv

from .models import GOOGLE_MODEL_CANDIDATES, MODEL_CANDIDATES, REGION

load_dotenv()

MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "bedrock")
# MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "google")  # "bedrock"(기본값) | "google"

TEMPERATURE = 0  # 평가 재현성을 위해 고정
MAX_OUTPUT_TOKENS = 1000  # architectures/0012 참고 - 완결된 답변을 자르지 않는 넉넉한 안전망


def active_model_candidates() -> list[str]:
    """현재 MODEL_PROVIDER에 맞는 모델 폴백 후보 목록을 반환한다."""
    return GOOGLE_MODEL_CANDIDATES if MODEL_PROVIDER == "google" else MODEL_CANDIDATES


def build_chat_model(model_id: str) -> Any:
    """model_id에 대한 채팅 모델 인스턴스를 현재 제공자에 맞게 만든다."""
    if MODEL_PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_id,
            google_api_key=os.environ["GOOGLE_API_KEY"],
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            max_retries=1,
        )

    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(
        model=model_id,
        region_name=REGION,
        temperature=TEMPERATURE,
        max_retries=1,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


def is_retryable_error(exc: Exception) -> bool:
    """모델 폴백 루프에서 "다음 후보로 넘어갈 만한 실패"인지 제공자별로 판단한다.

    인식하지 못하는 예외라면 폴백으로 조용히 삼키지 않고 그대로 올려보내야 한다 - 이 함수가
    False를 반환하면 호출자는 그 예외를 다시 raise 한다.
    """
    if MODEL_PROVIDER == "google":
        from langchain_core.exceptions import ModelError

        # ModelAPIError/ModelNotFoundError/ModelRateLimitError 등은 전부 ModelError의
        # "형제" 서브클래스라(서로 상속 관계가 아님) 공통 부모인 ModelError로 잡아야 전부
        # 커버된다 - ModelAPIError만 잡으면 ModelNotFoundError 같은 실패가 안 잡혀서
        # 폴백 없이 그대로 예외가 올라가버린다(실측으로 확인).
        return isinstance(exc, ModelError)

    from botocore.exceptions import ClientError

    return isinstance(exc, ClientError)
