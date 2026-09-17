# 0008. 성능 계측은 콜백 기반 실측으로, replay 방식은 계측 사각지대로 재평가

- 상태: 채택 (일부 후속 조치 진행 중)
- 관련 코드: `src/agent/agent.py`의 `PerformanceTracker`, `src/server/server.py`

## 맥락
`chat.html`에서 질문했을 때 응답이 느리다는 문제 제기가 있었고, API 요청 수신/응답 시각, RAG 조회 시간, 모델 응답 시간을 실측해 분석할 수 있어야 했습니다. `run_query()`는 이미 답변을 만든 뒤 `contexts`/`trace`를 사람이 읽을 구조로 재구성하려고 `retriever.rag_search()`를 결과 메시지에서 다시 호출하는 "replay" 방식을 쓰고 있었는데, 이 replay 위에 성능 계측을 얹으면 재실행 시간까지 실측치에 섞여 들어가는 문제가 있었습니다.

## 결정
LangChain의 `AsyncCallbackHandler`(`PerformanceTracker`)를 `agent.ainvoke(..., config={"callbacks": [tracker]})`로 넘겨서, `on_tool_start`/`on_tool_end`/`on_chat_model_start`/`on_llm_end` 훅으로 에이전트 실행 **도중** 실제로 걸린 도구별/LLM 호출별 시간을 기록합니다. `contexts`/`trace`의 내용(문서 텍스트 등) 재구성은 기존 replay 방식을 그대로 두되, 계측(`duration_ms`)은 이 콜백이 실측한 값만 씁니다. API 계층(`server.py`)에서는 별도로 요청 수신/응답 시각과 왕복 시간을 측정해 `trace`에 `api` 단계로 덧붙이고, 요청마다 `performance_trace.jsonl`(gitignore 대상)에 한 줄씩 남겨 여러 요청에 걸친 집계 분석이 가능하게 했습니다.

## 결과/트레이드오프
- **장점**: 근사치가 아니라 실제 Bedrock/Chroma 호출 시간을 그대로 잡아내므로, "어느 구간이 느린지"를 추측 없이 답할 수 있습니다. 실측 사례(질문 하나에 총 33초) 분해: LLM 호출 19.3초(58%), RAG 도구 5.3초(16%), MCP 서버 기동 2.2초(7%), 미계측 6.3초(19%).
- **계측 사각지대가 실제로 발견됨**: 위 미계측 6.3초를 코드로 추적한 결과, `agent.py`가 `contexts`/`trace`를 재구성하려고 이미 실행된 `rag_search`를 답변 생성 **후에 한 번 더 그대로 재실행**하고 있었습니다. 이 replay 호출은 콜백이 붙은 `ainvoke()` 바깥에서 일어나는 순수 함수 호출이라 `PerformanceTracker`에 전혀 잡히지 않으면서도 `total_ms`에는 그대로 반영돼, 계측 결과만 봐서는 "원인 불명의 지연"처럼 보였습니다. 즉 이번 성능 계측 작업 자체가 [0002](0002-bilingual-rag-search.md)에서 설계한 replay 패턴의 숨은 비용(요청당 `rag_search`가 실질적으로 두 번 실행되어 시간과 Bedrock 호출 비용이 배로 드는 문제)을 드러낸 셈입니다.
- **후속 조치(진행 중)**: `agent.ainvoke()` 실행 중 실제로 나온 tool 결과(`ToolMessage`)를 그대로 재사용해서 `contexts`/`trace`를 재구성하도록 바꾸면, replay로 인한 중복 실행과 그로 인한 계측 사각지대를 함께 없앨 수 있습니다. 이 변경은 아직 적용하지 않았고, `README.md`의 "아직 남아 있는 한계"에 해결 예정 항목으로 남겨뒀습니다.

## 후속 발견 및 수정: 실패한 모델 호출도 계측 사각지대였다
[0009](0009-english-only-domain-language-policy.md)로 `rag_ms`를 줄인 뒤, 같은 질문을 다시 재는데 `rag_ms`는 절반으로 줄었는데 `total_ms`는 오히려 33초 → 57초로 늘어난 사례가 나왔습니다. 원인을 추적한 결과 두 가지였습니다.

1. **Bedrock 일일 토큰 쿼터 소진**: 이 세션에서 자체 평가 2라운드 + RAGAS + 여러 수동 테스트로 계정의 일일 토큰을 계속 소모하면서, 1순위 모델(Sonnet 4.5 us./global.)이 쓰로틀링(`ThrottlingException`, "Too many tokens per day")되는 빈도가 늘었습니다. boto3가 내부적으로 최대 4회까지 지수 백오프로 재시도한 뒤에야 실패를 넘겨주기 때문에, 실패한 시도 하나당 실제로 10초 이상이 소모됩니다.
2. **`PerformanceTracker`가 실패한 호출을 아예 놓치고 있었음**: `on_llm_end`는 호출이 **성공**했을 때만 불리고, 실패하면 LangChain이 `on_llm_error`를 부르는데 원래 이 콜백을 구현하지 않아서 실패한 시도의 시간이 `total_ms`에는 반영되지만 `llm_ms`에는 전혀 안 잡혔습니다. `on_llm_error`/`on_tool_error`를 추가해 `failed_llm_durations_ms`/`failed_tool_events`로 별도 기록하고, `performance` 요약에 `llm_failed_ms`/`tool_failed_ms`로 노출했습니다.
3. **수정 과정에서 또 다른 버그를 발견**: `on_llm_error`를 추가하고 처음 재검증했을 때도 여전히 `llm_failed_ms: 0`이 나왔습니다. 원인은 `run_query()`의 모델 폴백 for문 **안에서 `tracker = PerformanceTracker()`를 매 반복마다 새로 만들고 있었다는 것**이었습니다 — 실패한 모델 시도의 기록이 다음 모델로 넘어가는 순간 버려지고, 최종적으로 성공한 마지막 시도의 tracker만 살아남으니 그 안에는 실패 기록이 있을 수 없었습니다. `tracker`를 for문 **밖에서 한 번만** 만들어 모든 시도(성공/실패 포함)가 같은 인스턴스에 누적되도록 고쳤습니다. 수정 후 실측: `llm_failed_ms: 14921.8`(쓰로틀링된 2개 모델 시도에 실제로 쓰인 시간)으로 정상적으로 잡혔습니다.

**교훈**: 계측 코드 자체에도 "성공 경로만 계측하고 실패 경로는 조용히 버리는" 사각지대가 생기기 쉽고, 그 사각지대는 계측 대상(이번엔 RAG 검색)이 빨라질수록 상대적으로 더 크게 드러난다. 계측을 추가한 뒤에는 실패 케이스로도 반드시 검증해야 한다.
