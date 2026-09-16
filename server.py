"""FastAPI 서버. POST /query 하나로 에이전트를 호출하고, 정적 채팅 UI를 서빙한다."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agent import run_query

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="컨플루언스 온보딩 Agent")
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


class QueryResponse(BaseModel):
    """POST /query 응답 바디. SERVICE.md API 계약(answer/contexts/trace)을 따른다."""

    answer: str
    contexts: list[dict]
    trace: list[dict]


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """질문을 받아 에이전트를 실행하고 answer/contexts/trace 를 반환한다."""
    result = await run_query(request.question)
    return QueryResponse(**result)
