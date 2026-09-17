"""self_llm_judge.py - 출처 정확성 중심 루브릭으로 test_self_queries.csv 케이스를 채점한다.

llm_judge.py(운영 스키마: expected_traits/forbidden 기반)와 달리, 이 채점기는 기획 초안대로
"인용한 출처가 expected_source_url과 일치하는지"를 최우선 기준으로 삼는다. 출처 일치 여부는
코드로 결정적으로 판정하고(cited_doc_ids에 expected_source_url 포함 여부), LLM은 그 판정 결과를
근거로 답변의 정직성·정확성까지 함께 반영해 5점 만점 점수를 매긴다.
"""

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from pydantic import BaseModel, Field

load_dotenv()

# 1순위 모델이 쓰로틀링되면 다음 모델로 자동 전환한다. src/agent/models.py의 MODEL_CANDIDATES와 같은 목록.
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

RUBRIC_NORMAL = """이 질문은 "정상"(문서로 답변 가능) 케이스입니다. 아래 기준(5점 만점)으로 채점하세요.
5점: 답변 내용이 expected_source_url 문서에 근거해 정확하고, 실제로 그 URL을 출처로 인용했다(출처 일치 여부는 이미 코드로 확인되어 아래에 표시됨).
3점: 답변 내용은 대체로 맞지만 출처 인용이 없거나 다른 문서를 인용했다(출처 불일치).
1점: 답변이 틀렸거나(환각) expected_source_url 문서와 무관한 내용을 답했다."""

RUBRIC_OUT_OF_SCOPE = """이 질문은 "범위밖"(문서에 근거가 없어 모른다고 답해야 하는) 케이스입니다. 아래 기준(5점 만점)으로 채점하세요.
5점: 관련 문서를 찾지 못했다고 정직하게 답했고, 사전 지식(예: 유명 오픈소스 지식)으로 답을 지어내지 않았다.
3점: 모른다고는 했지만 근거 없는 내용을 일부 섞어 답했다.
1점: 모른다고 하지 않고 사전 지식에 기반해 답변을 지어냈다(환각)."""


class JudgeResult(BaseModel):
    """LLM-judge 채점 결과. 5점 만점, 4점 이상이면 해당 케이스 통과."""

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
            print(f"[self judge 모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    raise RuntimeError(f"모든 judge 후보 모델이 실패했습니다: {last_error}") from last_error


def judge_answer(case: dict, answer: str, cited_doc_ids: list[str]) -> JudgeResult:
    """test_self_queries.csv 한 행(case)과 실제 답변/인용 출처를 받아 5점 만점으로 채점한다.

    case 는 csv.DictReader 가 읽은 딕셔너리로, question/category/expected_source_url 키를 쓴다.
    cited_doc_ids 는 run_query()가 실제로 반환한 contexts의 doc_id 목록이다(코드로 결정적 확인용).
    """
    expected_url = case["expected_source_url"]
    is_normal = case["category"] == "정상"
    rubric = RUBRIC_NORMAL if is_normal else RUBRIC_OUT_OF_SCOPE

    if is_normal:
        cited_match = "일치함(정확한 출처를 인용함)" if expected_url in cited_doc_ids else "불일치(다른 출처를 인용했거나 출처가 없음)"
        source_line = f"기대 출처(expected_source_url): {expected_url}\n실제 인용 출처와의 일치 여부: {cited_match}\n실제 인용 출처 목록: {'; '.join(cited_doc_ids) or '없음'}"
    else:
        source_line = f"실제 인용 출처 목록: {'; '.join(cited_doc_ids) or '없음'} (이 케이스는 범위밖이므로 출처가 없는 것이 정상이다)"

    prompt = f"{rubric}\n\n질문: {case['question']}\n{source_line}\n모델 답변: {answer}"
    return _invoke_judge(prompt)
