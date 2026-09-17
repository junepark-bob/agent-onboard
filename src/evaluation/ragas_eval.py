"""ragas_eval.py - RAGAS 지표(faithfulness/answer_relevancy/context_precision/context_recall)를 계산한다.

reference(정답 텍스트)가 있을 때만 context_recall을 계산한다. 나머지 세 지표는 reference 없이도
계산 가능한 방식(LLMContextPrecisionWithoutReference 등)을 쓴다.
"""

import sys
import types

# ragas.llms.base 가 langchain_community.chat_models.vertexai 를 무조건 import 하는데,
# 최신 langchain-community 에는 이 서브모듈이 없다(VertexAI 통합이 별도 패키지로 분리됨).
# 우리는 VertexAI를 쓰지 않으므로 더미 스텁으로 그 import 만 통과시킨다.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _stub = types.ModuleType("langchain_community.chat_models.vertexai")
    _stub.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _stub

# ragas.executor 가 임포트 시점에 nest_asyncio.apply()를 무조건 실행하는데, 이게 anyio의 이벤트
# 루프 감지를 깨뜨려 같은 프로세스에서 이후 실행되는 MCP stdio 서브프로세스 실행(agent.py의
# _get_mcp_tools -> anyio.open_process)이 "NoEventLoopError: Not currently running on any
# asynchronous event loop"로 실패한다. 우리는 ragas의 공개 single_turn_ascore() 래퍼를 쓰지 않고
# _single_turn_ascore()를 직접 호출하므로 nest_asyncio의 재진입 기능이 필요 없다 - 그래서 실제
# 패키지 대신 무해한 스텁으로 등록해 이 부작용 자체를 막는다.
if "nest_asyncio" not in sys.modules:
    _nest_asyncio_stub = types.ModuleType("nest_asyncio")
    _nest_asyncio_stub.apply = lambda *args, **kwargs: None
    sys.modules["nest_asyncio"] = _nest_asyncio_stub

from dotenv import load_dotenv
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from ragas import SingleTurnSample
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import AnswerRelevancy, Faithfulness, LLMContextPrecisionWithoutReference, LLMContextRecall

from ..agent import MODEL_CANDIDATES, REGION

load_dotenv()

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

_llm = LangchainLLMWrapper(ChatBedrockConverse(model=MODEL_CANDIDATES[0], region_name=REGION, temperature=0))
_embeddings = LangchainEmbeddingsWrapper(BedrockEmbeddings(model_id=EMBEDDING_MODEL_ID, region_name=REGION))

_faithfulness = Faithfulness(llm=_llm)
_answer_relevancy = AnswerRelevancy(llm=_llm, embeddings=_embeddings)
_context_precision = LLMContextPrecisionWithoutReference(llm=_llm)
_context_recall = LLMContextRecall(llm=_llm)


async def _score(metric, sample: SingleTurnSample) -> float:
    """metric.single_turn_ascore() 대신 내부 _single_turn_ascore()를 직접 호출한다.

    ragas(0.3.0)는 임포트 시점에 nest_asyncio.apply()를 무조건 실행하는데, 이게 Python 3.14의
    asyncio.timeout()과 충돌해서(공개 메서드가 쓰는 asyncio.wait_for 내부에서
    "RuntimeError: Timeout should be used inside a task") 채점이 실패한다. 실제 점수 계산 로직인
    _single_turn_ascore()는 이 타임아웃 래퍼를 거치지 않으므로 우회 경로로 직접 부른다.
    """
    return await metric._single_turn_ascore(sample=metric._only_required_columns_single_turn(sample), callbacks=[])


async def score_case(question: str, answer: str, contexts: list[str], reference: str | None = None) -> dict:
    """질문/답변/검색된 문서 조각(+ 있으면 정답 reference)으로 RAGAS 네 지표를 계산해 반환한다."""
    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts or ["(검색 결과 없음)"],
        reference=reference,
    )
    scores = {
        "faithfulness": await _score(_faithfulness, sample),
        "answer_relevancy": await _score(_answer_relevancy, sample),
        "context_precision": await _score(_context_precision, sample),
        "context_recall": None,
    }
    if reference:
        scores["context_recall"] = await _score(_context_recall, sample)
    return scores
