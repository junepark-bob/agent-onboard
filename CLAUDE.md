# 프로젝트 규칙

## 기술 스택
- Python, LangChain, LangGraph
- 모델은 Amazon Bedrock (ChatBedrockConverse), 임베딩은 BedrockEmbeddings (amazon.titan-embed-text-v2:0)
- Agent 생성은 langchain.agents 의 create_agent 를 쓴다
- 컨플루언스 실시간 조회/검색 도구는 fastmcp 기반 자체 MCP 서버로 제공하고, langchain_mcp_adapters 로 에이전트에 연결한다
- 모델 서빙은 FastAPI, UI는 라이브러리를 CDN 으로 include 한 단일 HTML 파일
- 첨부 이미지 분류·텍스트화는 비전 지원 Bedrock 모델(Claude Haiku 우선, 쓰로틀링 시 폴백)을 쓴다
- 평가 지표는 자체 LLM-judge(출처/트레잇 기반)와 RAGAS(faithfulness/answer_relevancy/context_precision/context_recall)를 함께 쓴다

## 아키텍처 구성 (5파트)
모든 파이썬 코드는 `src/` 아래에 있다. `data/`, `evaluation/`, `static/`은 코드가 아닌 산출물(문서/데이터/UI)만 둔다.
1. **AI 에이전트 파트** — `src/agent/` 서브패키지(`agent.py`, `tools.py`, `retriever.py`, `models.py`)
2. **모델 서빙 FastAPI 서버 파트** — `src/server/server.py`, `POST /query`(운영 계약)와 `POST /translate`(채팅 UI의 온디맨드 번역용, 계약 외 추가 엔드포인트)를 제공
3. **UI 파트** — `static/chat.html` 하나. 빌드 없이 CDN include 로 채팅 UI 구성
4. **크롤링 & RAG 구축 파트** — `src/crawler/crawl_confluence.py` (data/urls.txt 를 읽어 data/raw/ 에 수집, 첨부 이미지는 저비용 비전 모델로 분류·텍스트화해 본문에 삽입) + `src/agent/retriever.py` 의 인덱싱 함수 (data/raw/ → chroma_db 임베딩)
5. **평가 파트** — `src/evaluation/`: `llm_judge.py`/`run_eval.py`(운영 스키마 test_queries.csv → round1/2_report.md), `self_llm_judge.py`/`self_run_eval.py`(자체 출처-정확성 스키마 test_self_queries.csv → self_test_round1/2_report.md), `ragas_eval.py`(RAGAS 지표 계산)

## 폴더 구조
```
src/
├── agent/                    AI 에이전트 파트 (아래 4개 파일이 이 안에서 서로 참조)
│   ├── agent.py                메인 에이전트 그래프
│   ├── tools.py                 도메인 도구 (MCP 서버)
│   ├── retriever.py              RAG 파이프라인
│   └── models.py                  Bedrock 모델 폴백 후보 목록 (전체 공용, agent 패키지 __init__ 이 재노출)
├── crawler/crawl_confluence.py   컨플루언스 문서 수집 (data/urls.txt → data/raw/)
├── server/server.py               FastAPI 서버, POST /query
└── evaluation/
    ├── llm_judge.py                운영 스키마 LLM-judge 채점 로직
    ├── run_eval.py                  운영 스키마 평가 실행 스크립트
    ├── self_llm_judge.py             자체(출처-정확성) 스키마 LLM-judge 채점 로직
    ├── self_run_eval.py               자체 스키마 평가 실행 스크립트
    └── ragas_eval.py                   RAGAS 지표(faithfulness 등) 계산
static/chat.html      채팅 UI (단일 HTML, 라이브러리는 CDN include)
data/                 사용한 문서와 데이터 (urls.txt, raw/, chroma_db)
evaluation/           평가용 CSV와 리포트만 둔다(코드는 없음)
├── test_queries.csv / round1_report.md / round2_report.md         운영 측이 준 스키마
└── test_self_queries.csv / self_test_round1_report.md / self_test_round2_report.md   자체 출처-정확성 스키마
architectures/        아키텍처 결정 기록(ADR). 번호가 매겨진 결정 하나당 파일 하나, README.md가 인덱스
```
`src/agent/`는 외부에서 `from ..agent import run_query, MODEL_CANDIDATES, REGION` 형태로만 접근한다 — 내부에 어떤 파일이 몇 개 있는지는 `src/agent/__init__.py`가 감춘다.

## 실행 명령
서브패키지 상대 임포트를 쓰므로 스크립트를 직접 실행하지 않고 모듈로 실행한다 (모두 `mini-pjt/` 루트에서).
```bash
python -m src.crawler.crawl_confluence
python -m src.agent.retriever
uvicorn src.server.server:app --reload
python -m src.evaluation.run_eval
python -m src.evaluation.self_run_eval
```

## 주고받는 형식 (운영 측이 준 API 계약)
- POST /query 로 받고 question 필드를 읽는다
- 답은 answer, contexts, trace 세 키로 돌려준다
- trace의 각 단계(retrieve/fetch_page/live_search)에는 실제 실행 시간(duration_ms, LangChain
  콜백으로 계측)이 같이 담기고, 마지막에 `performance`(전체/모델 폴백-MCP 준비/LLM/RAG 소요 시간
  합계)와 `api`(API 요청 수신·응답 시각, 왕복 시간) 단계가 추가된다 — 계약의 3키 구조는 그대로다.
- 요청마다 성능 지표 한 줄이 루트의 `performance_trace.jsonl`에도 append 된다 (실행 환경마다
  달라지는 로그라 gitignore 대상).
- 답변은 질문과 같은 언어로 나온다(강제 한국어 번역 없음). RAG 검색은 대상 문서가 전부 영어라
  항상 영어로만 하고, 한국어 질의는 내부에서 영어로 번역해 검색한다. 답변을 한국어로 보고
  싶으면 `POST /translate`(별도 엔드포인트)로 온디맨드 번역을 요청한다
  (`architectures/0009-english-only-domain-language-policy.md`).

## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring 을 쓴다
- 비밀 값은 .env 에서 읽고 코드에 적지 않는다

## 컨벤션 (PEP 준수)
- **PEP 8**: 4-space 들여쓰기, snake_case 함수/변수, PascalCase 클래스, 한 줄 88자 이내(ruff/black 기본값 기준).
- **타입 힌트 (PEP 484/604)**: 모든 함수·메서드의 인자와 반환값에 타입을 명시한다. 반환값이 없으면 `-> None` 도 생략하지 않는다.
- **import 순서 (PEP 8)**: 표준 라이브러리 → 서드파티 → 로컬(`src.` 이하) 순으로 묶고 그룹 사이는 빈 줄로 구분한다.
- **포맷/린트**: `ruff format` 으로 포맷을 통일하고 `ruff check` 로 린트한다. 별도 포맷터(black)나 린터(flake8)를 섞어 쓰지 않는다.
- **API 스키마**: FastAPI 요청/응답은 `pydantic.BaseModel` 로 타입을 명시한다 (`question` 요청, `answer`/`contexts`/`trace` 응답 각각 모델로 정의).
- 공개 함수/클래스가 아니어도 타입 힌트는 생략하지 않는다. 단, 한국어 docstring 규칙과 충돌하지 않도록 타입은 시그니처에, 설명은 docstring 에 둔다.

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다

## 참고
이 파일은 프로젝트를 분석해서 작성한 것으로, 과제 운영 측이 내려준 제출 제약이 아니다(단, "주고받는 형식"의 API 계약은 운영 측이 실제로 준 스키마다). 구조를 바꿀 필요가 생기면 이 문서도 그때그때 현재 상태에 맞게 고친다.
