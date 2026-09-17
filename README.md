# 미니 PJT: 컨플루언스 온보딩 Agent

## 무엇을 푸나요
SI/SM 프로젝트에 새로 투입된 신입 멤버가 컨플루언스에서 온보딩 정보를 찾지 못해 겪는 비효율을, RAG + MCP 하이브리드 검색으로 답해드리고 근거가 없을 때는 정직하게 "모른다"고 답하는 에이전트로 풀어보려 합니다.

## 활용한 패턴 (Day 1~7)
- **Day 1 — LCEL chain (Pydantic 구조화 출력)**: `src/evaluation/llm_judge.py`의 `JudgeResult(BaseModel)`을 `with_structured_output(JudgeResult)`로 강제 파싱하도록 했고, `src/server/server.py`의 요청/응답도 `QueryRequest`/`Context`/`TraceStep`/`QueryResponse` pydantic 모델로 스키마를 검증하도록 했습니다.
- **Day 2 — RAG (쿼리 확장)**: `src/agent/retriever.py`의 `rag_search()`가 원본 질의어와 그 번역본(한국어↔영어)을 **둘 다** 검색해서 최상위 유사도가 더 높은 쪽을 채택합니다. 문서는 영어인데 질문은 한국어라 생기던 교차언어 검색 실패(실측 top1 유사도 ~0.13)를 이 방식으로 해결했습니다. 다만 고전적인 cross-encoder 리랭킹까지는 적용하지 못했습니다.
- **Day 3 — ReAct (도구 자율 선택)**: `src/agent/agent.py`의 `create_agent`가 `rag_search`/`get_page`/`search_confluence` 중 언제 무엇을 부를지 스스로 판단하도록 했습니다. 고정된 그래프 분기 대신 시스템 프롬프트로 순서만 안내합니다.
- **Day 4 — 도구 다중 결합 + MCP 서버 연동**: 한 질문에 로컬 검색(rag_search) → 원문 재조회(get_page) → 실시간 검색(search_confluence)까지 필요에 따라 자율적으로 이어서 호출합니다. `src/agent/tools.py`는 FastMCP 기반 stdio MCP 서버로 `get_page`/`search_confluence`를 노출하고, `langchain_mcp_adapters.MultiServerMCPClient`로 에이전트와 연결했습니다.
- **Day 5 — 가드레일/HITL/미들웨어**: 이 부분은 그대로 적용하지는 못했습니다. 대신 비슷한 문제(안정성)를 Bedrock 쓰로틀링에 대한 **모델 폴백 재시도**(`src/agent/models.py`의 `MODEL_CANDIDATES`)로 자체 구현해봤습니다 — 완전히 같은 패턴은 아니지만 "실패하면 대체 경로로 재시도한다"는 목적은 같습니다.
- **Day 6 — Multi-Agent Supervisor**: 적용하지 않았습니다. 도구가 2~3개뿐이라 단일 ReAct 에이전트로도 충분하다고 판단해서 의도적으로 채택하지 않았습니다 (근거는 `data/documents/ISSUES.md` 3절에 정리해뒀습니다).
- **Day 7 — Observability/Trace, 평가(LLM-as-Judge)**: `POST /query` 응답의 `trace` 필드에 각 단계(`retrieve`/`fetch_page`/`live_search`/`model_select`)의 입출력과 실행 시간(`duration_ms`)을 기록하도록 했습니다 — LangSmith나 LangFuse는 아니고 저희가 직접 구현한 방식입니다. 평가는 두 트랙으로 나눠서 구현했습니다: 운영 측 스키마(`expected_traits`/`forbidden` 기반) 채점은 `src/evaluation/llm_judge.py`, 출처 정확성 중심 자체 채점은 `src/evaluation/self_llm_judge.py`이며, 여기에 **RAGAS**(faithfulness/answer_relevancy/context_precision/context_recall, `src/evaluation/ragas_eval.py`)를 참고 지표로 함께 계산합니다 (아래 "RAGAS 평가 결과" 절 참고).

**필수 항목(1, 3, 11, 12) 충족 현황을 솔직히 말씀드리면**: 1(구조화 출력)은 충족했습니다. 3(RAG)은 쿼리 확장까지만 구현했고 리랭킹은 안 했습니다. 11(Observability)은 자체 trace(+실행 시간 계측)로 대체했고 LangSmith/LangFuse는 쓰지 않았습니다. 12(평가)는 LLM-as-Judge 두 트랙(운영 스키마/자체 출처-정확성 스키마)과 RAGAS를 함께 구현했습니다.

## 아키텍처
```
사용자(static/chat.html) → FastAPI(POST /query, src/server/server.py) → src/agent/agent.py (create_agent, ReAct)
                                                                             ├─ src/agent/retriever.py : RAG 검색 (chroma_db)
                                                                             └─ src/agent/tools.py     : Confluence MCP 서버
                                                                                                          (실시간 페이지 조회 / CQL 검색)
```
모든 파이썬 코드는 `src/` 아래에 모아뒀습니다(`src/agent/`, `src/crawler/`, `src/server/`, `src/evaluation/` 서브패키지). `src/agent/`는 외부에서 `from ..agent import run_query, MODEL_CANDIDATES, REGION` 형태로만 접근합니다 — 내부 파일 구성은 `src/agent/__init__.py`가 감춥니다. `data/`, `evaluation/`, `static/`에는 코드가 아닌 산출물(문서·데이터·UI)만 둡니다.

## 실행 방법
모든 명령은 `mini-pjt/` 디렉터리에서 실행해주세요(서브패키지 상대 임포트를 쓰고 있어서 `-m` 모듈 실행이 필요합니다). 사전 준비나 환경 변수 등 자세한 내용은 [아래 부록](#부록-설치--환경-변수)을 참고해주세요.

```bash
# 1. 컨플루언스 문서 수집 (data/urls.txt → data/raw/)
python -m src.crawler.crawl_confluence

# 2. RAG 인덱스 빌드 (data/raw/ → chroma_db/)
python -m src.agent.retriever

# 3. 서버 실행
uvicorn src.server.server:app --reload
# 브라우저에서 http://127.0.0.1:8000 에 접속하시거나 static/chat.html을 직접 열어도 채팅 UI를 쓰실 수 있습니다

# 4. 평가 실행 (운영 스키마: evaluation/test_queries.csv 20건 → LLM-judge 채점 → evaluation/round1_report.md)
python -m src.evaluation.run_eval

# 5. 자체 평가 실행 (출처 정확성 스키마: evaluation/test_self_queries.csv 11건 → self_llm_judge + RAGAS → evaluation/self_test_round1_report.md)
python -m src.evaluation.self_run_eval
```

## RAGAS 평가 결과
`src/evaluation/self_run_eval.py`가 자체 평가(출처 정확성) 케이스마다 RAGAS 4개 지표를 함께 계산해 `evaluation/self_test_round1_report.md`에 참고용으로 남깁니다. 1차 실행(11건) 평균은 다음과 같습니다.

| faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|
| 0.341 | 0.424 | 0.634 | 0.627 |

통과/실패 판정 자체는 지금까지처럼 `self_llm_judge`(출처 URL 일치 여부 중심)로 하고, RAGAS는 보조 지표로만 씁니다. `faithfulness`/`context_precision`이 케이스별로 0.00까지 떨어지는 경우가 있었는데, 실제 답변은 judge가 5점(정확)으로 판정한 케이스였습니다 — RAGAS가 내부적으로 문장을 잘게 쪼개 채점하는 방식과 저희 답변 스타일(짧은 인용 위주) 간의 궁합 문제로 보이며, 원인은 아직 더 봐야 합니다.

## 인-아웃 세트 통과율
### 운영 스키마 (test_queries.csv, 20건)
- **1차** (`evaluation/round1_report.md`): **18/20 통과 (90%)**였습니다. positive 7/8, negative 4/4, edge 4/5, guardrail 3/3. 실패한 2건은 #7(Jira 문서 질문, 3점 — 사소한 누락)과 #15(모호한 질문 "설정 파일이 뭐예요?"를 되묻지 않고 특정 파일로 단정해버림, 1점)였습니다.
- **2차** (`evaluation/round2_report.md`): 위 2건의 원인을 고쳐서 재실행한 결과 **20/20 통과 (100%)**였습니다.

### 자체 스키마 - 출처 정확성 (test_self_queries.csv, 11건)
- **1차** (`evaluation/self_test_round1_report.md`): **10/11 통과 (91%)**였습니다. 정상 7/8, 범위밖 3/3. 실패한 1건은 Chukwa 데이터 흐름 질문(3점 — judge가 출처는 맞지만 답변 내용이 다소 아쉽다고 판단)이었습니다.
- **2차**: 재실행 결과가 나오는 대로 이 자리에 갱신하겠습니다.

## 트라이앤에러 회고
- **시도했지만 실패했던 접근들**
  - 한국어 질의를 그대로 임베딩해서 검색했더니 정답 문서 top1 유사도가 ~0.13까지 떨어졌습니다(문서가 전부 영어라 교차언어 유사도가 낮아짐). → 원본+번역본을 함께 검색해서 최고점을 채택하는 방식으로 바꿨습니다.
  - 사용자 질문이 한국어인지 여부를 클라이언트(`chat.html`)가 정규식으로 판단해서 `is_korean` 플래그로 서버에 넘기게 했었는데, "HTML이 언어를 몰라도 되게 해달라"는 요청을 받고 `rag_search` 내부에서 자동 처리하는 방식으로 다시 설계하고 플래그는 걷어냈습니다.
  - 시스템 프롬프트에 "답변은 한국어로 쓰라"를 한 문장만 넣어봤는데, 영어로 질문하면 답변도 영어로 나오는 문제가 재현됐습니다(모델이 입력 언어를 따라가려는 경향을 문장 하나로는 못 눌렀습니다). → 프롬프트 맨 앞과 끝에 "절대 영어로 답하지 마라"를 반복해서 배치해 해결했습니다.
  - 컨플루언스 페이지 제목에 공백이 있는 URL(`.../Chukwa+Processes+and+Data+Flow`)을 파싱하지 못하는 문제가 있었습니다 — `urllib.parse.unquote`가 `+`를 공백으로 안 바꿔주는 게 원인이었습니다. `src/crawler/crawl_confluence.py`와 `src/agent/tools.py` 두 곳에서 순차적으로 발견해 `unquote_plus`로 고쳤습니다.
  - negative 평가 케이스("Kafka 클러스터에 Topic 만드는 법")에서 에이전트가 `AdminClient` 코드까지 곁들여 상세하게 답해버렸습니다. 처음엔 사전 지식(pretrained knowledge)으로 인한 환각이라고 의심했는데, trace를 뜯어보니 `search_confluence`가 스페이스 제한 없이 cwiki.apache.org 전체를 검색해서 **실제 KAFKA 프로젝트 스페이스의 진짜 문서**를 찾아 답한 것이었습니다. 프롬프트 문제가 아니라 도구가 스스로 범위를 제한하지 않은 게 진짜 원인이라, `CONFLUENCE_SPACE_KEY`로 CQL을 서버 쪽에서 강제로 감싸도록 고쳤습니다(`data/documents/ISSUES.md` 4절에 자세히 적어뒀습니다).
- **최종적으로 채택한 접근**: RAG(청크 임베딩 + 이중언어 검색)와 MCP(실시간 페이지 조회·검색)를 하이브리드로 묶어 단일 ReAct 에이전트(`create_agent`)로 구성했고, Bedrock 쓰로틀링에는 모델 폴백 체인으로, 첨부 이미지는 저비용 비전 모델 1회 호출로 대응했습니다.
- **아직 남아 있는 한계**
  - RAGAS를 아직 구현하지 못해서 수치가 없습니다.
  - 1차 라운드(20건)에서 실패했던 2건(#7 Jira 문서 질문 3점, #15 모호한 질문을 단정해버려서 1점)은 원인을 찾아 고쳤고, 2차에서 다시 검증했습니다.
  - 가드레일(PII/프롬프트 인젝션 방어)을 위한 전용 미들웨어는 없지만, guardrail 카테고리 3건은 시스템 프롬프트만으로 1차 라운드에서 전부(3/3) 통과했습니다. Multi-Agent Supervisor, Plan-Execute, 장기 메모리는 스코프 아웃으로 결정하고 적용하지 않았습니다.
  - 이미지 분류는 "사진/도표" 유형만 실측으로 확인했고, "문서 캡처"나 "도표가 있는 문서" 유형은 대상 스페이스(HADOOP2)에 아예 없어서 검증하지 못했습니다 (`data/documents/ISSUES.md` 2절).
  - **응답 속도가 너무 느립니다 (해결 예정)**: `agent.ainvoke()`에 LangChain 콜백으로 단계별 소요 시간을 계측해보니(`src/agent/agent.py`의 `PerformanceTracker`), 실제 질의 하나에 33초가 걸렸습니다 — LLM 호출 19.3초(58%, ReAct 루프가 순차적으로 Bedrock을 2회 이상 호출하는 구조적 원인), `rag_search` 5.3초(16%, 번역 1회 + 원문/번역본 이중 벡터 검색), MCP 서버 기동 2.2초(7%, 요청마다 stdio 서브프로세스를 새로 띄움), 그리고 계측되지 않은 6.3초(19%)로 나뉩니다. 마지막 미계측 구간을 코드로 추적해보니 `agent.py`가 `contexts`/`trace`를 구조화하려고 이미 실행된 `rag_search`를 답변 생성 후 **한 번 더 그대로 재실행**하고 있었습니다 — 즉 요청당 `rag_search`가 실질적으로 두 번 돌면서 시간과 Bedrock 호출 비용이 그만큼 더 들고 있었습니다. 남은 1.5일 동안 이 중복 실행 제거(ainvoke 실행 중 나온 실제 tool 결과 재사용), MCP 서브프로세스 재사용, 필요시 모델 교체/스트리밍까지 순서대로 고치면서 이 문단을 갱신할 계획입니다.

## 핵심 코드 위치
- `src/agent/agent.py:66` — `run_query()`, API의 메인 진입점입니다 (모델 폴백 재시도 + trace/contexts 조립)
- `src/agent/agent.py:60` — `build_agent()`, rag_search와 MCP 도구로 create_agent 인스턴스를 만듭니다
- `src/agent/agent.py:19` — `SYSTEM_PROMPT`
- `src/agent/tools.py:43` — `get_page()`, MCP 도구입니다 (페이지 실시간 조회)
- `src/agent/tools.py:75` — `search_confluence()`, MCP 도구입니다 (CQL 실시간 검색, `CONFLUENCE_SPACE_KEY`로 스페이스를 강제 제한합니다)
- `src/agent/retriever.py:110` — `rag_search()`, 쿼리 확장 + 이중 검색 + 최고점 채택을 담당합니다
- `src/agent/retriever.py:74` — `_translate()`, 한국어↔영어 번역을 담당합니다(모델 폴백 포함)
- `src/agent/models.py:7` — `MODEL_CANDIDATES`, Bedrock 모델 폴백 후보 목록입니다
- `src/crawler/crawl_confluence.py:176` — `main()`, 크롤링 진입점입니다
- `src/server/server.py:67` — `POST /query` 핸들러입니다
- `src/evaluation/llm_judge.py:58` — `judge_answer()`, LLM-as-Judge 채점을 담당합니다
- `src/evaluation/run_eval.py:142` — `run_round()`, 평가셋 전체 실행과 마크다운 리포트 저장을 담당합니다

---

## 부록: 설치 & 환경 변수

### 요구사항
- Python 3.11 이상이면 됩니다 (개발/검증은 3.14 기준으로 진행했습니다)
- AWS Bedrock 접근 권한이 필요합니다 — `src/agent/models.py`의 `MODEL_CANDIDATES`(Claude Sonnet/Haiku, us./global. 추론 프로필, Amazon Nova)에 대한 모델 액세스, 임베딩은 `amazon.titan-embed-text-v2:0`, 리전은 `us-east-1`입니다

### 설치
이 저장소 루트에 공용 가상환경이 준비되어 있습니다. 루트에서 가상환경을 만드시고, 루트 + `mini-pjt` 두 requirements를 모두 설치해주세요.

```bash
# 저장소 루트에서
python -m venv .venv
.venv\Scripts\activate          # (PowerShell) 또는 source .venv/bin/activate (bash)
pip install -r requirements.txt
pip install -r mini-pjt/requirements.txt
```

### 환경 변수
저장소 루트의 `.env`를 그대로 사용합니다 (`load_dotenv()`가 상위 폴더까지 자동으로 찾아줍니다).

| 변수 | 필수 여부 | 설명 |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | 필수 | Bedrock 호출용 AWS 자격 증명입니다 |
| `AWS_SECRET_ACCESS_KEY` | 필수 | Bedrock 호출용 AWS 자격 증명입니다 |
| `AWS_DEFAULT_REGION` | 필수 | `us-east-1`로 설정해주세요 |
| `CONFLUENCE_BASE_URL` | 선택 | 기본값은 `https://cwiki.apache.org/confluence`입니다. 사내 컨플루언스로 바꾸실 때는 이 값만 교체하시면 됩니다 |
| `CONFLUENCE_AUTH_TOKEN` | 선택 | ASF 공개 스페이스는 비워두셔도 됩니다. 인증이 필요한 인스턴스라면 Bearer 토큰을 지정해주세요 |

### API 계약
```
POST /query
Content-Type: application/json
Body: {"question": "사용자 질의"}

Response:
{
  "answer": "근거 기반 응답",
  "contexts": [{"doc_id": "...", "text": "...", "title": "..."}, ...],
  "trace": [{"step": "retrieve", "input": "...", "output": "..."}, ...]
}
```
- `contexts[].doc_id`는 컨플루언스 페이지의 canonical URL을 사용합니다(저희 시스템에서는 "문서" 단위가 페이지 하나라서 URL을 안정적인 식별자로 쓰고 있습니다). `title`은 계약에는 없는 추가 필드인데, 채팅 UI가 출처 링크의 라벨로 활용합니다.
- `trace[].step`은 `retrieve`/`fetch_page`/`live_search`/`model_select` 중 하나입니다.

### 비고
- **`SIMILARITY_THRESHOLD`**(`src/agent/retriever.py`): 0.3으로 설정해뒀습니다. 실측한 정상 질문(0.44~0.83)과 범위밖 질문(0.07~0.22) 점수 사이의 값이며, 크롤링 대상 문서가 바뀌면 재조정이 필요합니다.
- **AWS Bedrock 일일 토큰 한도**: 반복 실행하면 걸릴 수 있습니다(`ThrottlingException: Too many tokens per day`). `src/evaluation/run_eval.py`는 케이스 하나가 실패해도 나머지를 계속 진행하고 실패 사유를 리포트에 남기도록 만들어뒀습니다.
- **이미지 처리**: `src/crawler/crawl_confluence.py`가 첨부 이미지(`ac:image`)를 찾으면 긴 변을 768px로 축소한 뒤 저비용 모델(`claude-haiku`)에 분류와 추출을 한 번만 호출합니다. 설계 배경은 `data/documents/ISSUES.md` 2절을 참고해주세요.
- **`search_confluence` 스페이스 제한**: `src/agent/tools.py`가 실시간 CQL 검색을 항상 `CONFLUENCE_SPACE_KEY`(기본값 `HADOOP2`)로 감싸도록 해뒀습니다. 이렇게 하지 않으면 cwiki.apache.org 전체(수백 개 ASF 프로젝트)를 검색해버려서, 범위밖 질문에도 실제 문서를 찾아 답해버리는 문제가 있었습니다(`data/documents/ISSUES.md` 4절).

> 기획 배경/요구사항은 [data/documents/SERVICE.md](data/documents/SERVICE.md), 한 줄 소개는 [data/documents/INTRODUCTION.md](data/documents/INTRODUCTION.md), 설계 고민은 [data/documents/ISSUES.md](data/documents/ISSUES.md)를 참고해주세요.
