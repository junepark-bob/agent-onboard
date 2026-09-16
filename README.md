# 컨플루언스 온보딩 Agent

SI/SM 프로젝트에 새로 투입된 신입 멤버가 컨플루언스에서 온보딩 정보를 찾지 못해 겪는 비효율을 해결하는 AI 에이전트입니다. 사전에 인덱싱한 문서를 RAG로 검색하고, 부족하면 MCP로 컨플루언스를 실시간 검색해 보완하며, 근거가 없으면 "모른다"고 답해 환각을 방지합니다.

> 기획 배경과 요구사항은 [documents/SERVICE.md](documents/SERVICE.md), 한 줄 소개는 [documents/INTRODUCTION.md](documents/INTRODUCTION.md), 설계 고민은 [documents/ISSUES.md](documents/ISSUES.md)를 참고하세요.

## 특징

- **RAG + MCP 하이브리드 검색**: 사전 크롤링한 문서를 벡터 검색(RAG)하고, 결과가 부족하면 컨플루언스를 실시간 검색(MCP)하는 폴백을 에이전트가 스스로 판단합니다.
- **출처 인용 + 정직한 "모름"**: 답변에는 항상 출처 링크가 따라붙고, 근거가 없으면 지어내지 않고 모른다고 답합니다.
- **한국어 질문 / 영어 문서 대응**: 문서는 영어 원문이지만 사용자는 한국어로 질문합니다. `rag_search`가 질의어와 그 번역본(한국어<->영어)을 모두 검색해 유사도가 더 높은 쪽을 자동으로 채택합니다 (자세한 내용은 [비고](#비고) 참고).
- **이미지(다이어그램) 크롤링 지원**: 페이지에 첨부 이미지가 있으면 축소한 뒤 저비용 비전 모델(Haiku)에 한 번만 보내 사진은 설명, 다이어그램은 Mermaid, 문서/표 캡처는 텍스트로 바꿔 본문에 끼워 넣습니다.
- **실무 컨플루언스로 교체 가능한 구조**: `CONFLUENCE_BASE_URL`/`CONFLUENCE_AUTH_TOKEN`을 `.env`로 분리해 대상 컨플루언스를 코드 수정 없이 교체할 수 있습니다.
- **LLM-judge 자동 평가**: `evaluation/`의 테스트 질문셋을 돌려 출처 정확성 중심으로 자동 채점하고 리포트를 남깁니다.

## 아키텍처

```
사용자(static/chat.html) → FastAPI(POST /query, server.py) → src/agent.py (create_agent, ReAct)
                                                                  ├─ src/retriever.py : RAG 검색 (chroma_db)
                                                                  └─ src/tools.py     : Confluence MCP 서버
                                                                                         (실시간 페이지 조회 / CQL 검색)
```

## 프로젝트 구조

```
crawl_confluence.py     컨플루언스 문서 수집 (data/urls.txt → data/raw/)
server.py                FastAPI 서버, POST /query, 채팅 UI 서빙
static/chat.html          채팅 UI (단일 HTML)
src/
├── agent.py               메인 에이전트 그래프 (create_agent 기반 ReAct)
├── tools.py                도메인 도구 (Confluence MCP 서버)
├── retriever.py            RAG 파이프라인 (임베딩 + 벡터 검색)
└── models.py                Bedrock 모델 폴백 후보 목록 (agent/retriever 공용)
data/
├── urls.txt                크롤링할 페이지 URL 목록 (수동 선정)
└── raw/                     크롤링된 원문 (JSON, git에는 포함되지 않음)
chroma_db/                 벡터 인덱스 (생성물, git에는 포함되지 않음)
evaluation/
├── test_queries.csv        평가용 질문 11건 (정상 8 + 범위밖 3)
├── llm_judge.py             LLM-judge 채점 로직
├── run_eval.py               평가 실행 스크립트
└── eval_report.csv           평가 결과 (실행 후 생성)
documents/                 기획 문서 (SERVICE.md, INTRODUCTION.md, IDEAS.md, ISSUES.md 등)
```

## 요구사항

- Python 3.11 이상 (개발/검증은 3.14 기준)
- AWS Bedrock 접근 권한 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`, `amazon.titan-embed-text-v2:0` 모델 사용 승인 필요, 리전 `us-east-1`)

## 설치

이 저장소(`sds-ax-practice`) 루트에 공용 가상환경이 있습니다. 루트에서 가상환경을 만들고, 루트 + `mini-pjt` 두 requirements를 모두 설치하세요.

```bash
# 저장소 루트에서
python -m venv .venv
.venv\Scripts\activate          # (PowerShell) 또는 source .venv/bin/activate (bash)
pip install -r requirements.txt
pip install -r mini-pjt/requirements.txt
```

## 환경 변수

저장소 루트의 `.env`를 그대로 사용합니다 (`load_dotenv()`가 상위 폴더까지 자동으로 탐색합니다). 루트 `.env`에 아래 항목이 필요합니다.

| 변수 | 필수 | 설명 |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | 필수 | Bedrock 호출용 AWS 자격 증명 |
| `AWS_SECRET_ACCESS_KEY` | 필수 | Bedrock 호출용 AWS 자격 증명 |
| `AWS_DEFAULT_REGION` | 필수 | `us-east-1` |
| `CONFLUENCE_BASE_URL` | 선택 | 기본값 `https://cwiki.apache.org/confluence` (ASF 공개 인스턴스). 사내 컨플루언스로 바꾸려면 이 값만 교체 |
| `CONFLUENCE_AUTH_TOKEN` | 선택 | ASF 공개 스페이스는 비워둬도 됨. 인증이 필요한 인스턴스면 Bearer 토큰 지정 |

## 사용법

모든 명령은 `mini-pjt/` 디렉터리에서 실행합니다.

### 1. 컨플루언스 문서 크롤링

`data/urls.txt`에 적힌 URL들을 수집해 `data/raw/*.json`으로 저장합니다.

```bash
python crawl_confluence.py
```

### 2. RAG 인덱스 빌드

`data/raw/`의 문서를 임베딩해 `chroma_db/`를 생성합니다.

```bash
python -m src.retriever
```

### 3. 서버 실행

```bash
uvicorn server:app --reload
```

API는 이 서버가 떠 있어야 동작합니다. 채팅 UI는 두 가지 방법 중 편한 쪽으로 엽니다.

- 브라우저에서 `http://127.0.0.1:8000` 접속 (서버가 `static/chat.html`을 서빙)
- 또는 `static/chat.html` 파일을 탐색기에서 더블클릭해 `file://`로 직접 열기 (서버는 여전히 백그라운드에서 실행 중이어야 함)

두 방법 모두 `static/chat.html`이 절대 URL(`http://127.0.0.1:8000/query`)로 API를 호출하고, `server.py`에 CORS를 열어뒀기 때문에 동일하게 동작합니다. 서버 포트를 8000이 아닌 다른 값으로 바꾸면 `static/chat.html` 상단의 `API_BASE` 값도 맞춰서 바꿔야 합니다.

### 4. API 직접 호출

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "패치를 커밋할 때 커밋 메시지에는 어떤 정보를 포함해야 하나요?"}'
```

응답 형식:

```json
{
  "answer": "한국어 요약 답변 (출처 인용 포함)",
  "contexts": [{"title": "...", "url": "...", "content": "..."}],
  "trace": [{"tool": "rag_search", "args": {"query": "...", "k": 5}, "hits": [...]}]
}
```

### 5. 평가 실행

`evaluation/test_queries.csv` 11건을 에이전트로 실행하고 LLM-judge로 채점해 `evaluation/eval_report.csv`를 생성합니다.

```bash
python evaluation/run_eval.py
```

성공 기준(자세한 내용은 `documents/SERVICE.md` 11절): 질문당 5점 만점 중 평균 4점 이상이면 통과, 11건 중 8건(약 70%) 이상 통과하면 전체 성공.

## 비고

- **양방향 번역 후 최고점 채택**: 문서는 영어 원문인데 사용자는 한국어로 질문합니다. 한국어 질의를 그대로 임베딩하면 Titan Embed v2의 교차언어 유사도가 크게 떨어져(실측 top1 ~0.13) 정답 문서를 못 찾습니다. 그래서 `src/retriever.py`의 `rag_search()`가 호출될 때마다 내부적으로 (1) 원본 질의어 번역(한국어<->영어), (2) 원본과 번역본 둘 다로 벡터 검색, (3) 최상위 유사도가 더 높은 쪽 결과 채택을 수행합니다. 호출자(에이전트/`src/agent.py`)는 질문 언어를 신경 쓸 필요가 없습니다.
- **`SIMILARITY_THRESHOLD`(`src/retriever.py`)**: 0.3으로 설정되어 있으며, 실측한 정상 질문(0.44~0.83)과 범위밖 질문(0.07~0.22) 점수 사이의 값입니다. 크롤링 대상 문서가 바뀌면 재조정이 필요합니다.
- **1차(MVP) 범위**: RAG 검색 + 출처 인용 + "모름" 판단 + trace 기록. 실시간 CQL 검색(MCP 폴백)과 "읽기 순서 가이드"는 후순위 기능입니다.
- **AWS Bedrock 일일 토큰 한도**: 평가를 반복 실행하면 계정의 일일 토큰 한도에 걸릴 수 있습니다(`ThrottlingException: Too many tokens per day`). `run_eval.py`는 문항 하나가 실패해도 나머지를 계속 진행하고 실패 사유를 리포트에 남깁니다.
- **모델 폴백**: Bedrock 쓰로틀링이 나면 `src/models.py`의 `MODEL_CANDIDATES` 순서대로 다음 모델(같은 모델의 `global.` 추론 프로필 포함)로 자동 전환합니다. `src/agent.py`, `evaluation/llm_judge.py`, `crawl_confluence.py`(비전 모델)가 모두 이 패턴을 씁니다.
- **이미지 처리와 토큰 비용**: `crawl_confluence.py`는 페이지에서 첨부 이미지(`ac:image`)를 찾으면 다운로드 후 긴 변 768px로 축소한 뒤, 저비용 모델(`claude-haiku`)에 "사진/다이어그램/문서 캡처 중 하나로 분류해서 바로 그 형식으로 답하라"는 프롬프트를 **한 번만** 보내 사진은 문장 설명, 다이어그램은 Mermaid, 문서 캡처는 텍스트 그대로 옮기게 합니다. 리사이즈(토큰의 대부분을 차지하는 이미지 크기 축소) + 모델 1회 호출 + 저비용 모델 우선이 토큰을 아끼는 핵심 장치입니다. 설계 배경은 [documents/ISSUES.md](documents/ISSUES.md) 2절 참고.
