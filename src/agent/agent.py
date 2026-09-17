"""RAG 검색과 Confluence MCP 도구를 묶어 온보딩 질문에 답하는 단일 ReAct 에이전트."""

import json
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
    "너는 한국 기업 SI/SM 프로젝트의 사내 온보딩 어시스턴트다. "
    "답변은 질문과 같은 언어로 자연스럽게 써라 — 질문이 한국어면 한국어로, 영어면 영어로 답하면 된다. "
    "답을 다 쓴 뒤에 그 답 전체를 다른 언어로 다시 번역하는 별도 작업은 하지 마라 — "
    "번역이 필요하면 사용자가 채팅 UI에서 답변을 보고 별도로 번역을 요청한다. "
    "예외는 출처 인용구뿐이며, 그 부분만 항상 원문(영어) 그대로 남긴다. "
    "먼저 rag_search로 로컬 문서를 검색하고, 결과가 부족하면 search_confluence로 실시간 검색하라. "
    "rag_search는 한국어 질의어를 알아서 영어로 번역해 검색하므로 질문을 어느 언어로 넘겨도 된다. "
    "너는 오직 rag_search/search_confluence/get_page 로 실제로 찾아낸 내용에만 근거해 답해야 한다. "
    "검색 결과에 질문과 관련된 근거가 없으면, 그 주제(예: 유명한 오픈소스 프로젝트나 기술 용어)를 "
    "네가 이미 잘 알고 있더라도 절대 그 사전 지식으로 답하지 마라 — 이 규칙에는 예외가 없다. "
    "그런 경우 관련 내용을 찾지 못했다고만 정직하게 답하라(질문 언어에 맞춰서). "
    "검색으로 찾지 못한 내용을 네 지식으로 채워 넣지 마라. "
    "질문이 짧거나 모호해서 여러 의미로 해석될 수 있으면(예: '설정 파일이 뭐예요?'), "
    "검색 결과 중 하나를 임의로 골라 그것이 정답인 것처럼 단정하지 마라. "
    "대신 질문이 모호하다는 점을 먼저 밝히고, 검색으로 찾은 후보들을 '~을 말씀하시는 거라면' 식으로 "
    "제시한 뒤 더 구체적으로 알려주면 정확히 답하겠다고 안내하라."
)


class PerformanceTracker(AsyncCallbackHandler):
    """도구 호출과 LLM 호출이 각각 얼마나 걸렸는지 실행 순서대로 기록한다.

    성공한 호출뿐 아니라 실패한 호출(쓰로틀링 등으로 on_tool_error/on_llm_error가 불린 경우)도
    별도로 기록한다 — 실패한 시도는 wall-clock 시간(total_ms)에는 그대로 반영되지만 성공 케이스만
    잡던 이전 버전에서는 어디로 사라졌는지 전혀 안 보였다(모델 폴백 중 쓰로틀링 재시도로 30초
    가까이 사라진 사례로 발견). 성능 분석용 계측이라 내용(입출력)은 담지 않고 이름과 소요 시간만
    남긴다 — trace의 contexts/output 재구성은 실제 ToolMessage 내용을 그대로 재사용한다(재호출 없음).
    """

    def __init__(self) -> None:
        self.tool_events: list[dict[str, Any]] = []  # 실행 순서대로: {"name": str, "duration_ms": float}
        self.failed_tool_events: list[dict[str, Any]] = []
        self.llm_durations_ms: list[float] = []
        self.failed_llm_durations_ms: list[float] = []
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

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        entry = self._tool_starts.pop(run_id, None)
        if entry is None:
            return
        name, start = entry
        self.failed_tool_events.append({"name": name, "duration_ms": round((time.perf_counter() - start) * 1000, 1)})

    async def on_chat_model_start(self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_starts[run_id] = time.perf_counter()

    async def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._llm_starts[run_id] = time.perf_counter()

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._llm_starts.pop(run_id, None)
        if start is not None:
            self.llm_durations_ms.append(round((time.perf_counter() - start) * 1000, 1))

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._llm_starts.pop(run_id, None)
        if start is not None:
            self.failed_llm_durations_ms.append(round((time.perf_counter() - start) * 1000, 1))

    def tool_ms(self, name: str) -> float:
        """특정 도구(name) 의 성공한 호출들의 소요 시간 합을 반환한다."""
        return round(sum(t["duration_ms"] for t in self.tool_events if t["name"] == name), 1)


def _get_text(message: Any) -> str:
    """ChatBedrockConverse 메시지의 content(문자열 또는 블록 리스트)에서 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


_mcp_tools_cache: list[Any] | None = None


async def _get_mcp_tools() -> list[Any]:
    """tools.py를 stdio MCP 서버로 띄워 get_page/search_confluence 도구를 가져온다.

    프로세스당 한 번만 생성해서 재사용한다(모듈 전역 캐시) — 매 요청마다 새 stdio
    서브프로세스를 띄우면 요청 내용과 무관한 순수 오버헤드(실측 2.2~2.5초)가 매번 추가된다.
    서버는 기동 시 warmup()으로 미리 채워서, 첫 요청부터 이 캐시를 그대로 쓴다.
    """
    global _mcp_tools_cache
    if _mcp_tools_cache is None:
        client = MultiServerMCPClient(
            {
                "confluence": {
                    "command": sys.executable,
                    "args": [str(TOOLS_SERVER_PATH)],
                    "transport": "stdio",
                }
            }
        )
        _mcp_tools_cache = await client.get_tools()
    return _mcp_tools_cache


async def warmup() -> None:
    """MCP 도구를 미리 만들어 캐시를 채운다. FastAPI 서버가 기동 시(lifespan) 한 번 호출한다."""
    await _get_mcp_tools()


def build_agent(model_id: str, mcp_tools: list[Any]) -> Any:
    """지정한 모델과 rag_search + MCP 도구로 create_agent 인스턴스를 만든다.

    max_retries=1로 boto3 자체 재시도를 끄고 즉시 실패하게 한다 — 안 그러면 쓰로틀링 한 번마다
    boto3가 내부적으로 최대 4회 지수 백오프 재시도를 다 마친 뒤에야 실패를 넘겨줘서, 우리 코드의
    MODEL_CANDIDATES 폴백으로 넘어가기까지 실측 10초 이상이 걸렸다.
    """
    model = ChatBedrockConverse(model=model_id, region_name=REGION, temperature=TEMPERATURE, max_retries=1)
    return create_agent(model, tools=[retriever.rag_search, *mcp_tools], system_prompt=SYSTEM_PROMPT)


async def run_query(question: str) -> dict:
    """질문을 받아 에이전트를 실행하고 SERVICE.md API 계약대로 answer/contexts/trace 를 반환한다.

    질문이 한국어든 영어든 그대로 넘기면 된다. rag_search가 한국어 질의만 내부적으로 영어로
    번역해 검색하므로, 호출자가 언어를 미리 알려줄 필요는 없다.

    Bedrock 쓰로틀링 등으로 모델 호출이 실패하면 MODEL_CANDIDATES 순서대로 다음 모델로
    자동 전환해 재시도한다. MCP 도구는 모델과 무관하므로 한 번만 가져와 재사용한다.

    trace에는 각 단계의 결과뿐 아니라 실제 소요 시간(duration_ms)도 함께 담아, 성능 분석에
    쓸 수 있게 한다.
    """
    request_start = time.perf_counter()

    mcp_setup_start = time.perf_counter()
    mcp_tools = await _get_mcp_tools()
    mcp_setup_ms = round((time.perf_counter() - mcp_setup_start) * 1000, 1)

    # 루프 밖에서 한 번만 만들어 모든 모델 시도(성공/실패 포함)의 이벤트를 누적한다 — 루프
    # 안에서 매번 새로 만들면 실패한 시도의 기록(failed_llm_durations_ms 등)이 다음 시도로
    # 넘어가기 전에 버려져서, 쓰로틀링 재시도에 쓴 실제 시간이 성능 요약에서 사라진다.
    tracker = PerformanceTracker()
    result = None
    used_model = None
    last_error: Exception | None = None
    for model_id in MODEL_CANDIDATES:
        try:
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
                # rag_search를 다시 부르지 않고, 실제 실행 결과(ToolMessage, JSON 문자열)를
                # 그대로 파싱해 재사용한다 — 재호출하면 번역+벡터검색이 요청당 실질적으로
                # 두 번 돌아 시간과 비용이 배로 든다(architectures/0008 참고).
                parsed = json.loads(tool_outputs.get(call["id"], "[]"))
                hits = parsed if isinstance(parsed, list) else [parsed]
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
                # 실패한(쓰로틀링 등) 모델/도구 호출에 소모된 시간. 성공 호출만 잡는 위 지표들과
                # 달리, 여기 잡히지 않으면 total_ms에는 남지만 원인 모를 "미계측 구간"이 된다.
                "llm_failed_ms": round(sum(tracker.failed_llm_durations_ms), 1),
                "tool_failed_ms": round(sum(t["duration_ms"] for t in tracker.failed_tool_events), 1),
            },
        }
    )

    return {"answer": _get_text(result["messages"][-1]), "contexts": contexts, "trace": trace}
