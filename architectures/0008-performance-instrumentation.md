# 0008. 성능 계측은 콜백 기반 실측으로, replay 방식은 계측 사각지대로 재평가

- 상태: 채택 (아래 세 가지 후속 조치 모두 적용 완료)
- 관련 코드: `src/agent/agent.py`의 `PerformanceTracker`, `src/server/server.py`

## 맥락
`chat.html`에서 질문했을 때 응답이 느리다는 문제 제기가 있었고, API 요청 수신/응답 시각, RAG 조회 시간, 모델 응답 시간을 실측해 분석할 수 있어야 했습니다. `run_query()`는 이미 답변을 만든 뒤 `contexts`/`trace`를 사람이 읽을 구조로 재구성하려고 `retriever.rag_search()`를 결과 메시지에서 다시 호출하는 "replay" 방식을 쓰고 있었는데, 이 replay 위에 성능 계측을 얹으면 재실행 시간까지 실측치에 섞여 들어가는 문제가 있었습니다.

## 결정
LangChain의 `AsyncCallbackHandler`(`PerformanceTracker`)를 `agent.ainvoke(..., config={"callbacks": [tracker]})`로 넘겨서, `on_tool_start`/`on_tool_end`/`on_chat_model_start`/`on_llm_end` 훅으로 에이전트 실행 **도중** 실제로 걸린 도구별/LLM 호출별 시간을 기록합니다. `contexts`/`trace`의 내용(문서 텍스트 등) 재구성은 기존 replay 방식을 그대로 두되, 계측(`duration_ms`)은 이 콜백이 실측한 값만 씁니다. API 계층(`server.py`)에서는 별도로 요청 수신/응답 시각과 왕복 시간을 측정해 `trace`에 `api` 단계로 덧붙이고, 요청마다 `performance_trace.jsonl`(gitignore 대상)에 한 줄씩 남겨 여러 요청에 걸친 집계 분석이 가능하게 했습니다.

## 결과/트레이드오프
- **장점**: 근사치가 아니라 실제 Bedrock/Chroma 호출 시간을 그대로 잡아내므로, "어느 구간이 느린지"를 추측 없이 답할 수 있습니다. 실측 사례(질문 하나에 총 33초) 분해: LLM 호출 19.3초(58%), RAG 도구 5.3초(16%), MCP 서버 기동 2.2초(7%), 미계측 6.3초(19%).
- **계측 사각지대가 실제로 발견됨**: 위 미계측 6.3초를 코드로 추적한 결과, `agent.py`가 `contexts`/`trace`를 재구성하려고 이미 실행된 `rag_search`를 답변 생성 **후에 한 번 더 그대로 재실행**하고 있었습니다. 이 replay 호출은 콜백이 붙은 `ainvoke()` 바깥에서 일어나는 순수 함수 호출이라 `PerformanceTracker`에 전혀 잡히지 않으면서도 `total_ms`에는 그대로 반영돼, 계측 결과만 봐서는 "원인 불명의 지연"처럼 보였습니다. 즉 이번 성능 계측 작업 자체가 [0002](0002-bilingual-rag-search.md)에서 설계한 replay 패턴의 숨은 비용(요청당 `rag_search`가 실질적으로 두 번 실행되어 시간과 Bedrock 호출 비용이 배로 드는 문제)을 드러낸 셈입니다.
- **후속 조치(적용 완료)**: `agent.ainvoke()` 실행 중 실제로 나온 tool 결과(`ToolMessage`, JSON 문자열)를 `json.loads()`로 그대로 파싱해 재사용하도록 바꿨다 — `retriever.rag_search()`를 다시 부르지 않는다. `on_tool_end`의 `output` 파라미터를 직접 조사해 ToolMessage의 content가 이미 유효한 JSON(`[{"title":...,"url":...,"content":...,"score":...}]`)이라는 걸 확인하고 적용했다. 이제 요청당 `rag_search`가 정확히 한 번만 실행된다.

## 후속 발견 및 수정: 실패한 모델 호출도 계측 사각지대였다
[0009](0009-english-only-domain-language-policy.md)로 `rag_ms`를 줄인 뒤, 같은 질문을 다시 재는데 `rag_ms`는 절반으로 줄었는데 `total_ms`는 오히려 33초 → 57초로 늘어난 사례가 나왔습니다. 원인을 추적한 결과 두 가지였습니다.

1. **Bedrock 일일 토큰 쿼터 소진**: 이 세션에서 자체 평가 2라운드 + RAGAS + 여러 수동 테스트로 계정의 일일 토큰을 계속 소모하면서, 1순위 모델(Sonnet 4.5 us./global.)이 쓰로틀링(`ThrottlingException`, "Too many tokens per day")되는 빈도가 늘었습니다. boto3가 내부적으로 최대 4회까지 지수 백오프로 재시도한 뒤에야 실패를 넘겨주기 때문에, 실패한 시도 하나당 실제로 10초 이상이 소모됩니다.
2. **`PerformanceTracker`가 실패한 호출을 아예 놓치고 있었음**: `on_llm_end`는 호출이 **성공**했을 때만 불리고, 실패하면 LangChain이 `on_llm_error`를 부르는데 원래 이 콜백을 구현하지 않아서 실패한 시도의 시간이 `total_ms`에는 반영되지만 `llm_ms`에는 전혀 안 잡혔습니다. `on_llm_error`/`on_tool_error`를 추가해 `failed_llm_durations_ms`/`failed_tool_events`로 별도 기록하고, `performance` 요약에 `llm_failed_ms`/`tool_failed_ms`로 노출했습니다.
3. **수정 과정에서 또 다른 버그를 발견**: `on_llm_error`를 추가하고 처음 재검증했을 때도 여전히 `llm_failed_ms: 0`이 나왔습니다. 원인은 `run_query()`의 모델 폴백 for문 **안에서 `tracker = PerformanceTracker()`를 매 반복마다 새로 만들고 있었다는 것**이었습니다 — 실패한 모델 시도의 기록이 다음 모델로 넘어가는 순간 버려지고, 최종적으로 성공한 마지막 시도의 tracker만 살아남으니 그 안에는 실패 기록이 있을 수 없었습니다. `tracker`를 for문 **밖에서 한 번만** 만들어 모든 시도(성공/실패 포함)가 같은 인스턴스에 누적되도록 고쳤습니다. 수정 후 실측: `llm_failed_ms: 14921.8`(쓰로틀링된 2개 모델 시도에 실제로 쓰인 시간)으로 정상적으로 잡혔습니다.

**교훈**: 계측 코드 자체에도 "성공 경로만 계측하고 실패 경로는 조용히 버리는" 사각지대가 생기기 쉽고, 그 사각지대는 계측 대상(이번엔 RAG 검색)이 빨라질수록 상대적으로 더 크게 드러난다. 계측을 추가한 뒤에는 실패 케이스로도 반드시 검증해야 한다.

## 후속 조치: boto3 재시도 횟수 축소, MCP 서브프로세스 재사용
성능 개선 추천 목록 중 남은 두 가지도 적용했다.

- **`max_retries=1`**: `ChatBedrockConverse` 생성 시 boto3 자체 재시도를 1회(=재시도 없음)로 줄였다. 기존에는 쓰로틀링 한 번마다 boto3가 내부적으로 최대 4회 지수 백오프 재시도를 다 마친 뒤에야 `ClientError`를 우리 코드에 넘겨줘서, `MODEL_CANDIDATES` 폴백으로 넘어가기까지 실패한 시도 하나당 10초 이상이 걸렸다. 적용 후 실측: 로그의 오류 메시지가 "reached max retries: 4" → "reached max retries: 1"로 바뀌었고, 같은 4개 모델이 전부 쓰로틀링된 요청에서 `llm_failed_ms`가 5992.4ms/4715.6ms로 나왔다 — 이전에 단 2개 모델 실패로 14921.8ms~29471.0ms가 나왔던 것과 비교하면, 실패한 시도당 비용이 대략 1/5~1/10로 줄었다. 에이전트 본체(`agent.py`)뿐 아니라 같은 폴백 패턴을 쓰는 `translator.py`(번역), `crawl_confluence.py`(비전), `llm_judge.py`/`self_llm_judge.py`(채점)에도 동일하게 적용했다. `ragas_eval.py`는 폴백 후보 목록이 없는 단일 모델 호출이라 대상에서 뺐다(재시도를 줄이면 안전망 없이 실패율만 올라간다).
- **MCP 도구 캐싱**: `_get_mcp_tools()`가 요청마다 새 stdio 서브프로세스를 띄우던 것을, 모듈 전역 캐시(`_mcp_tools_cache`)로 프로세스당 한 번만 만들도록 바꿨다. FastAPI 서버는 `lifespan`에서 `warmup()`을 호출해 기동 시점에 미리 채워두므로, 첫 요청부터 이 캐시를 쓴다. 실측: 첫 호출 `mcp_setup_ms: 2044.5` → 이후 모든 호출 `mcp_setup_ms: 0.0`. 서버로 실제 기동해서 첫 `/query` 요청까지 확인했다(로그상 MCP 서버 배너가 `Application startup complete` 이전에 출력됨).
- **Chroma 클라이언트 캐싱(추가 발견)**: 위 검증 중 `_vector_search()`가 호출마다 새 `Chroma(...)`(내부적으로 `chromadb.PersistentClient`)를 만들고 버리는 지점에서 `chromadb`의 `KeyError`(`SharedSystemClient._identifier_to_system`)가 실제 요청을 실패시키는 걸 이 세션에서 3번째로 재현했다. `retriever.py`에 `_get_vectorstore()`를 추가해 MCP와 같은 패턴(모듈 전역 캐시, 프로세스당 한 번만 생성)으로 고쳤다 — `rag_search`가 LangChain 스레드풀에서 동기 실행되므로 `threading.Lock`으로 동시 생성 경쟁도 막았다. 수정 후 `ThreadPoolExecutor`로 20개 동시 호출을 던지는 스트레스 테스트와, 이어서 실제 에이전트로 연속 2회 호출까지 크래시 없이 통과했다.

## 후속 검증: MCP 도구 등록 자체는 `llm_ms` 증가의 원인이 아니었다
`llm_ms`가 계속 늘어나는 사례들을 보며 "MCP 도구(`get_page`/`search_confluence`)가 프롬프트에 등록돼 있는 것 자체가 매 턴 판단을 느리게 만드는가"도 실측으로 확인했다. 같은 모델·같은 질문으로 MCP 도구 유무만 다르게 비교한 결과, 두 조건에서 조건이 완전히 동일한 첫 턴은 거의 차이가 없었다(1728.7ms vs 1671.8ms) — 늘어난 구간은 대화 컨텍스트가 누적된 이후의 턴이었지 도구 스키마 개수 때문이 아니었다. 이 실험과 함께, `get_page` 도구의 실제 실행 시간(3191.1ms)과 그 도구를 "부르기로 판단"하는 LLM 턴의 시간(9.5~10.7초)을 혼동하지 않도록 구분한 상세 내용은 `data/documents/ISSUES.md` 3절("업데이트: MCP 도구 등록 자체가 LLM 판단 속도를 늦추는지 실측")에 정리했다.
