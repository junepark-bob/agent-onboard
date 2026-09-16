"""RAG 검색과 Confluence MCP 도구를 묶어 온보딩 질문에 답하는 단일 ReAct 에이전트."""

import sys
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse
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
    "그래도 근거를 찾지 못하면 모른다고 답하라. "
    "rag_search는 질의어를 한국어/영어 둘 다로 알아서 검색하므로 질문을 어느 언어로 넘겨도 된다. "
    "다시 한번 강조한다: 질문이 어떤 언어였든 최종 답변은 반드시 한국어여야 한다."
)


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
    """
    mcp_tools = await _get_mcp_tools()

    result = None
    used_model = None
    last_error: Exception | None = None
    for model_id in MODEL_CANDIDATES:
        try:
            agent = build_agent(model_id, mcp_tools)
            result = await agent.ainvoke({"messages": [("user", question)]})
            used_model = model_id
            break
        except ClientError as exc:
            last_error = exc
            print(f"[모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    if result is None:
        raise RuntimeError(f"모든 후보 모델이 실패했습니다: {last_error}") from last_error

    trace: list[dict] = [{"model": used_model}]
    contexts: list[dict] = []
    for message in result["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            step: dict[str, Any] = {"tool": call["name"], "args": call["args"]}
            if call["name"] == "rag_search":
                hits = retriever.rag_search(**call["args"])
                step["hits"] = [
                    {"title": hit["title"], "url": hit["url"], "score": round(hit["score"], 3)} for hit in hits
                ]
                contexts.extend({"title": hit["title"], "url": hit["url"], "content": hit["content"]} for hit in hits)
            trace.append(step)

    return {"answer": _get_text(result["messages"][-1]), "contexts": contexts, "trace": trace}
