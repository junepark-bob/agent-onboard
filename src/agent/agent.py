"""RAG 검색과 Confluence MCP 도구를 묶어 온보딩 질문에 답하는 단일 ReAct 에이전트."""

import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_mcp_adapters.client import MultiServerMCPClient

from . import retriever
from .models import MODEL_CANDIDATES, REGION

TOOLS_SERVER_PATH = Path(__file__).parent / "tools.py"

TEMPERATURE = 0  # 평가 재현성을 위해 고정

SYSTEM_PROMPT = (
    "너는 한국어로만 답하는 한국 기업 사내 온보딩 어시스턴트다. "
    "사용자가 영어로 질문해도 절대 영어로 답하지 마라. 답변의 첫 단어부터 끝까지 전부 한국어로 써라. "
    "예외는 출처 인용구뿐이며, 그 부분만 원문(영어) 그대로 남긴다. "
    "먼저 rag_search로 로컬 문서를 검색하고, 결과가 부족하면 search_confluence로 실시간 검색하라. "
    "rag_search는 질의어를 한국어/영어 둘 다로 알아서 검색하므로 질문을 어느 언어로 넘겨도 된다. "
    "너는 오직 rag_search/search_confluence/get_page 로 실제로 찾아낸 내용에만 근거해 답해야 한다. "
    "검색 결과에 질문과 관련된 근거가 없으면, 그 주제(예: 유명한 오픈소스 프로젝트나 기술 용어)를 "
    "네가 이미 잘 알고 있더라도 절대 그 사전 지식으로 답하지 마라 — 이 규칙에는 예외가 없다. "
    "그런 경우 '컨플루언스 문서에서 관련 내용을 찾지 못했습니다'라고만 정직하게 답하라. "
    "다시 한번 강조한다: 질문이 어떤 언어였든 최종 답변은 반드시 한국어여야 하고, "
    "검색으로 찾지 못한 내용을 네 지식으로 채워 넣지 마라. "
    "질문이 짧거나 모호해서 여러 의미로 해석될 수 있으면(예: '설정 파일이 뭐예요?'), "
    "검색 결과 중 하나를 임의로 골라 그것이 정답인 것처럼 단정하지 마라. "
    "대신 질문이 모호하다는 점을 먼저 밝히고, 검색으로 찾은 후보들을 '~을 말씀하시는 거라면' 식으로 "
    "제시한 뒤 더 구체적으로 알려주면 정확히 답하겠다고 안내하라."
)


class PerformanceTracker(AsyncCallbackHandler):
    """도구 호출과 LLM 호출이 각각 얼마나 걸렸는지 실행 순서대로 기록한다.

    성능 분석용 계측이라 내용(입출력)은 담지 않고 이름과 소요 시간만 남긴다 — trace의
    contexts/output 재구성은 기존 방식(메시지 순회 + rag_search 재호출)을 그대로 쓴다.
    """

    def __init__(self) -> None:
        self.tool_events: list[dict[str, Any]] = []  # 실행 순서대로: {"name": str, "duration_ms": float}
        self.llm_durations_ms: list[float] = []
        self._tool_starts: dict[UUID, tuple[str, float]] = {}
        self._llm_starts: dict[UUID, float] = {}

    async def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, **kwargs: Any) -> None:
        name = (serialized or {}).get("name", "unknown")
        self._tool_starts[run_id] = (name, time.perf_counter())

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        entry = self._tool_starts.pop(run_id, None)
        if entry is None:
            return
        name, start = entry
        self.tool_events.append({"name": name, "duration_ms": round((time.perf_counter() - start) * 1000, 1)})

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_starts[run_id] = time.perf_counter()

    async def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_starts[run_id] = time.perf_counter()

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._llm_starts.pop(run_id, None)
        if start is not None:
            self.llm_durations_ms.append(round((time.perf_counter() - start) * 1000, 1))

    def tool_ms(self, name: str) -> float:
        """특정 도구(name) 호출들의 소요 시간 합을 반환한다."""
        return round(sum(t["duration_ms"] for t in self.tool_events if t["name"] == name), 1)


def _get_text(message: Any) -> str:
    """ChatBedrockConverse 메시지의 content(문자열 또는 블록 리스트)에서 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


async def _get_mcp_tools() -> list[Any]:
    """tools.py를 stdio MCP 서버로 띄워 get_page/search_confluence 도구를 가져온다."""
    client = MultiServerMCPClient(
        {
            "confluence": {
                "command": sys.executable,
                "args": [str(TOOLS_SERVER_PATH)],
                "transport": "stdio",
            }
        }
    )
    return await client.get_tools()


def build_agent(model_id: str, mcp_tools: list[Any]) -> Any:
    """지정한 모델과 rag_search + MCP 도구로 create_agent 인스턴스를 만든다."""
    model = ChatBedrockConverse(model=model_id, region_name=REGION, temperature=TEMPERATURE)
    return create_agent(model, tools=[retriever.rag_search, *mcp_tools], system_prompt=SYSTEM_PROMPT)


async def run_query(question: str) -> dict:
    """질문을 받아 에이전트를 실행하고 SERVICE.md API 계약대로 answer/contexts/trace 를 반환한다.

    질문이 한국어든 영어든 그대로 넘기면 된다. rag_search가 내부적으로 질의어와 그 번역본
    둘 다 검색해 더 유사도가 높은 쪽을 채택하므로, 호출자가 언어를 미리 알려줄 필요는 없다.

    Bedrock 쓰로틀링 등으로 모델 호출이 실패하면 MODEL_CANDIDATES 순서대로 다음 모델로
    자동 전환해 재시도한다. MCP 도구는 모델과 무관하므로 한 번만 가져와 재사용한다.

    trace에는 각 단계의 결과뿐 아니라 실제 소요 시간(duration_ms)도 함께 담아, 성능 분석에
    쓸 수 있게 한다.
    """
    request_start = time.perf_counter()

    mcp_setup_start = time.perf_counter()
    mcp_tools = await _get_mcp_tools()
    mcp_setup_ms = round((time.perf_counter() - mcp_setup_start) * 1000, 1)

    result = None
    used_model = None
    last_error: Exception | None = None
    for model_id in MODEL_CANDIDATES:
        try:
            tracker = PerformanceTracker()
            agent = build_agent(model_id, mcp_tools)
            result = await agent.ainvoke({"messages": [("user", question)]}, config={"callbacks": [tracker]})
            used_model = model_id
            break
        except ClientError as exc:
            last_error = exc
            print(f"[모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    if result is None:
        raise RuntimeError(f"모든 후보 모델이 실패했습니다: {last_error}") from last_error

    tool_outputs = {
        message.tool_call_id: _get_text(message)
        for message in result["messages"]
        if getattr(message, "type", None) == "tool"
    }

    # 도구 이름별로 실제 실행 순서대로 소요 시간을 꺼내 쓰기 위한 큐.
    durations_by_name: dict[str, list[float]] = {}
    for event in tracker.tool_events:
        durations_by_name.setdefault(event["name"], []).append(event["duration_ms"])

    def _next_duration(name: str) -> float | None:
        queue = durations_by_name.get(name)
        return queue.pop(0) if queue else None

    trace: list[dict] = [{"step": "model_select", "input": MODEL_CANDIDATES, "output": used_model}]
    contexts: list[dict] = []
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            if call["name"] == "rag_search":
                hits = retriever.rag_search(**call["args"])
                trace.append(
                    {
                        "step": "retrieve",
                        "input": call["args"],
                        "output": [
                            {"doc_id": hit["url"], "title": hit["title"], "score": round(hit["score"], 3)}
                            for hit in hits
                        ],
                        "duration_ms": _next_duration("rag_search"),
                    }
                )
                contexts.extend({"doc_id": hit["url"], "title": hit["title"], "text": hit["content"]} for hit in hits)
            elif call["name"] == "get_page":
                trace.append(
                    {
                        "step": "fetch_page",
                        "input": call["args"],
                        "output": tool_outputs.get(call["id"]),
                        "duration_ms": _next_duration("get_page"),
                    }
                )
            elif call["name"] == "search_confluence":
                trace.append(
                    {
                        "step": "live_search",
                        "input": call["args"],
                        "output": tool_outputs.get(call["id"]),
                        "duration_ms": _next_duration("search_confluence"),
                    }
                )

    total_ms = round((time.perf_counter() - request_start) * 1000, 1)
    trace.append(
        {
            "step": "performance",
            "input": None,
            "output": {
                "total_ms": total_ms,
                "mcp_setup_ms": mcp_setup_ms,
                "llm_ms": round(sum(tracker.llm_durations_ms), 1),
                "rag_ms": tracker.tool_ms("rag_search"),
            },
        }
    )

    return {"answer": _get_text(result["messages"][-1]), "contexts": contexts, "trace": trace}
