"""FastAPI 서버. POST /query 하나로 에이전트를 호출하고, 정적 채팅 UI를 서빙한다."""

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent import run_query, translate, warmup

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/server -> src -> mini-pjt 루트
STATIC_DIR = PROJECT_ROOT / "static"
PERFORMANCE_LOG_PATH = PROJECT_ROOT / "performance_trace.jsonl"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """서버 기동 시 MCP 도구를 한 번 미리 띄워둔다 — 안 그러면 첫 요청이 그 기동 비용을 문다."""
    await warmup()
    yield


app = FastAPI(title="컨플루언스 온보딩 Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# static/chat.html을 file:// 로 직접 열어도 호출할 수 있도록 모든 출처를 허용한다.
# (로컬 개발/데모용 설정이며, 실제 배포 시에는 특정 출처로 좁혀야 한다.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def index() -> FileResponse:
    """채팅 UI(static/chat.html)를 서빙한다."""
    return FileResponse(STATIC_DIR / "chat.html")


class QueryRequest(BaseModel):
    """POST /query 요청 바디."""

    question: str


class Context(BaseModel):
    """근거로 인용된 문서 조각 하나. doc_id는 컨플루언스 페이지의 canonical URL을 쓴다."""

    doc_id: str
    text: str
    title: str | None = None  # 계약 필수 필드는 아니지만, 채팅 UI가 출처 링크 라벨로 쓴다


class TraceStep(BaseModel):
    """에이전트가 거친 단계 하나 (예: retrieve, fetch_page, live_search, model_select)."""

    step: str
    input: Any
    output: Any


class QueryResponse(BaseModel):
    """POST /query 응답 바디. answer/contexts/trace 계약을 따른다."""

    answer: str
    contexts: list[Context]
    trace: list[TraceStep]


class TranslateRequest(BaseModel):
    """POST /translate 요청 바디. 채팅 UI가 영어 답변을 한국어로 바꿔볼 때 쓴다."""

    text: str


class TranslateResponse(BaseModel):
    """POST /translate 응답 바디."""

    translated: str


def _log_performance(question: str, trace: list[dict[str, Any]], api_duration_ms: float) -> None:
    """요청 하나의 성능 지표를 performance_trace.jsonl 한 줄로 남겨, 나중에 집계 분석할 수 있게 한다."""
    agent_step = next((step for step in trace if step["step"] == "performance"), None)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "api_duration_ms": api_duration_ms,
        **(agent_step["output"] if agent_step else {}),
    }
    with PERFORMANCE_LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """질문을 받아 에이전트를 실행하고 answer/contexts/trace 를 반환한다.

    API 요청을 받은 시각/응답한 시각/소요 시간을 trace에 "api" 단계로 덧붙이고,
    performance_trace.jsonl에도 한 줄 남겨 요청 간 성능을 집계 분석할 수 있게 한다.
    """
    received_at = datetime.now(timezone.utc)
    start = time.perf_counter()
    result = await run_query(request.question)
    api_duration_ms = round((time.perf_counter() - start) * 1000, 1)
    responded_at = datetime.now(timezone.utc)

    result["trace"].append(
        {
            "step": "api",
            "input": None,
            "output": {
                "received_at": received_at.isoformat(),
                "responded_at": responded_at.isoformat(),
                "duration_ms": api_duration_ms,
            },
        }
    )
    _log_performance(request.question, result["trace"], api_duration_ms)

    return QueryResponse(**result)


@app.post("/translate", response_model=TranslateResponse)
def translate_text(request: TranslateRequest) -> TranslateResponse:
    """텍스트를 한국어<->영어로 번역한다.

    /query는 매 요청마다 답변을 자동으로 재번역하지 않는다(성능 저하 방지) — 대신 채팅 UI가
    필요할 때만(예: 영어 답변에 붙은 "한국어로 보기" 버튼) 이 엔드포인트를 별도로 호출하는
    온디맨드 번역 경로다 (`architectures/0009-english-only-domain-language-policy.md` 참고).
    동기 함수라 FastAPI가 자동으로 스레드풀에서 실행해 이벤트 루프를 막지 않는다.
    """
    return TranslateResponse(translated=translate(request.text))
