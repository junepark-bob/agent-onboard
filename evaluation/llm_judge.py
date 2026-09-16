"""llm_judge.py - 고정 루브릭 기반 LLM 심사. SERVICE.md 규약대로 출처 정확성을 최우선으로 채점한다."""

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, Field

load_dotenv()

# 1순위 모델이 쓰로틀링되면 다음 모델로 자동 전환한다. src/agent.py의 MODEL_CANDIDATES와 같은 목록.
JUDGE_MODEL_CANDIDATES = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
]
JUDGE_REGION = "us-east-1"


class JudgeResult(BaseModel):
    """LLM-judge 채점 결과. 5점 만점, 4점 이상이면 해당 질문 통과."""

    score: int = Field(ge=1, le=5)
    reasoning: str


def _invoke_judge(prompt: str) -> JudgeResult:
    """JUDGE_MODEL_CANDIDATES를 순서대로 시도해 쓰로틀링 시 다음 모델로 자동 전환한다."""
    last_error: Exception | None = None
    for model_id in JUDGE_MODEL_CANDIDATES:
        try:
            llm = ChatBedrockConverse(model=model_id, region_name=JUDGE_REGION, temperature=0)
            return llm.with_structured_output(JudgeResult).invoke(prompt)
        except ClientError as exc:
            last_error = exc
            print(f"[judge 모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    raise RuntimeError(f"모든 judge 후보 모델이 실패했습니다: {last_error}") from last_error


RUBRIC_NORMAL = """다음 기준(5점 만점)으로 평가하세요. 출처 정확성을 가장 중요하게 보세요.
5점: 정답 출처 URL을 정확히 인용했고, 답변 내용도 질문에 맞게 정확하다.
3점: 답변 내용은 대체로 맞지만 출처 URL이 다르거나 누락됐다.
1점: 답변이 틀렸거나, 근거 없이 지어냈거나(환각), 질문과 관련 없다."""

RUBRIC_OUT_OF_SCOPE = """다음 기준(5점 만점)으로 평가하세요. 이 질문은 문서에 근거가 없는 범위밖 질문입니다.
5점: 모른다고 명확히 답했거나 정직하게 거절했고, 근거 없는 내용을 지어내지(환각) 않았다.
3점: 거절은 했지만 애매하거나 불필요하게 관련 없는 정보를 덧붙였다.
1점: 모르면서도 아는 것처럼 답을 지어냈다(환각)."""


def judge_answer(question: str, category: str, expected_source_url: str, answer: str, contexts: list[dict]) -> JudgeResult:
    """질문/카테고리/기대 출처/실제 답변/인용 문서를 받아 5점 만점으로 채점한다."""
    rubric = RUBRIC_NORMAL if category == "정상" else RUBRIC_OUT_OF_SCOPE
    cited_urls = ", ".join(sorted({c["url"] for c in contexts if c.get("url")})) or "없음"
    prompt = (
        f"{rubric}\n\n"
        f"질문: {question}\n"
        f"기대 출처 URL: {expected_source_url or '없음 (범위밖 질문)'}\n"
        f"모델이 실제로 인용한 URL: {cited_urls}\n"
        f"모델 답변: {answer}"
    )
    return _invoke_judge(prompt)
