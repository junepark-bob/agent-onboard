# 0011. 성능 최적화 라운드 정리 — 수정사항과 결과

- 상태: 채택 (4건 모두 적용 완료, 실측 검증 완료)
- 관련 코드: `src/agent/agent.py`, `src/agent/retriever.py`, `src/agent/translator.py`, `src/crawler/crawl_confluence.py`, `src/evaluation/llm_judge.py`, `src/evaluation/self_llm_judge.py`, `src/server/server.py`
- 선행 문서: [0008](0008-performance-instrumentation.md)(계측 도입과 문제 발견 과정의 상세 서사), [0009](0009-english-only-domain-language-policy.md), [0010](0010-router-pattern-for-translation.md)

이 문서는 성능 계측([0008](0008-performance-instrumentation.md))으로 찾아낸 병목에 대해 실제로 적용한 수정사항과 그 결과를 한곳에 정리한 요약본이다. 각 문제를 어떻게 발견했는지의 서사(실측 로그, 시행착오)는 [0008](0008-performance-instrumentation.md)에 이미 자세히 있으므로, 여기서는 "무엇을 고쳤고 결과가 어땠는가"만 간결하게 정리한다.

## 적용한 수정사항

| # | 수정 | 파일 | 핵심 내용 |
|---|---|---|---|
| 1 | `rag_search` 중복 실행 제거 | `src/agent/agent.py` | `contexts`/`trace` 재구성 시 `retriever.rag_search()`를 다시 부르지 않고, `agent.ainvoke()` 실행 중 실제로 나온 `ToolMessage`의 내용(유효한 JSON)을 `json.loads()`로 그대로 파싱해 재사용한다. 요청당 번역+벡터검색이 정확히 한 번만 실행된다. |
| 2 | boto3 재시도 횟수 축소 | `agent.py`, `translator.py`, `crawl_confluence.py`, `llm_judge.py`, `self_llm_judge.py` | 모델 폴백 체인을 쓰는 모든 `ChatBedrockConverse` 생성 시 `max_retries=1`을 지정했다. boto3가 내부적으로 최대 4회 지수 백오프 재시도를 다 마친 뒤에야 실패를 넘겨주던 것을, 즉시 실패하고 우리 코드의 `MODEL_CANDIDATES` 폴백으로 바로 넘어가게 했다. `ragas_eval.py`는 폴백 후보가 없는 단일 모델이라 제외했다(재시도를 줄이면 안전망 없이 실패율만 오른다). |
| 3 | MCP 도구 프로세스당 1회 생성 | `agent.py`, `server.py` | `_get_mcp_tools()`가 요청마다 새 stdio 서브프로세스를 띄우던 것을 모듈 전역 캐시(`_mcp_tools_cache`)로 바꿨다. `agent.py`에 공개 함수 `warmup()`을 추가하고, FastAPI `lifespan`에서 서버 기동 시 한 번 호출해 첫 요청부터 캐시를 쓰도록 했다. |
| 4 | Chroma 클라이언트 캐싱 | `retriever.py` | 위 3번을 검증하는 과정에서, `_vector_search()`가 호출마다 새 `Chroma`(`chromadb.PersistentClient`)를 만들고 버리다가 `chromadb`의 `KeyError`(`SharedSystemClient._identifier_to_system`)로 요청이 통째로 실패하는 걸 재현했다(이 세션에서 3번째 재현). 3번과 같은 패턴(모듈 전역 캐시, 프로세스당 1회 생성)으로 고치고, `rag_search`가 LangChain 스레드풀에서 동시 실행될 수 있는 점을 감안해 `threading.Lock`으로 이중 생성 경쟁도 막았다. |

## 성능 개선 결과 (실측)

| 지표 | 조치 전 | 조치 후 |
|---|---|---|
| `rag_search` 1회 성공 실행 | ~5322.7ms (이중 검색 + 중복 재실행, [0002](0002-bilingual-rag-search.md)/[0008](0008-performance-instrumentation.md) 시점) | ~1200~3000ms (단일 검색, 중복 실행 제거) |
| `mcp_setup_ms` (두 번째 요청부터) | 매 요청 ~2200ms | **0ms** |
| 실패한 모델 1개당 비용 | ~7500~14700ms (모델 2개 실패에 14.9~29.5초 소모) | ~1100~1240ms (모델 4개 실패에 4.4~5.0초 소모) |
| Chroma 관련 요청 실패 | 간헐적으로 요청 전체가 죽음(이 세션 3회 재현) | 동시 20회 스트레스 테스트 + 반복 실행 모두 크래시 없이 통과 |

**정직한 평가**: 위 네 가지는 모두 "통제 가능한" 오버헤드(중복 실행, 재시도 대기, 프로세스 재기동, 클라이언트 재생성)를 없앤 것이지, 에이전트 본체가 실제로 추론하는 시간(`llm_ms`, 성공한 호출 기준)을 줄인 게 아니다. 4건을 막 적용한 시점에도 `total_ms`는 여전히 28~30초대였는데, 그 이유는 Bedrock 계정의 일일 토큰 쿼터가 소진돼 후보 모델 4개(Sonnet 4.5 us./global., Sonnet 4.6 us./global.)가 실시간으로 전부 쓰로틀링되고 있었기 때문이다 — 이건 이번 조치로 고칠 수 있는 부분이 아니다.

## 동일 질문 기준 최초 대비 실측 비교

`performance_trace.jsonl`에는 같은 질문("Hadoop 프로젝트는 이슈 관리에 어떤 도구를 쓰고...")을 **이번 세션 최초 측정**(1라인, 어떤 조치도 적용하기 전)과 **위 4건 적용 + 모델을 Haiku로 고정**(`MODEL_CANDIDATES`를 Haiku 단일 후보로 하드코딩, 쓰로틀링 없이 성공한 7라인) 양쪽으로 기록이 남아 있다. 쿼터 변동성을 배제한 가장 깨끗한 비교다.

| 지표 | 1라인 (최초, 조치 전) | 7라인 (4건 적용 + Haiku, 쓰로틀링 없음) | 변화 |
|---|---|---|---|
| `total_ms` | 33132.5 | 17673.8 | **-47%** |
| `mcp_setup_ms` | 2234.6 | 0.0 | **-100%** |
| `rag_ms` | 5322.7 | 2623.4 | **-51%** |
| `llm_ms` | 19314.8 | 13084.8 | -32% |
| `llm_failed_ms` | (계측 이전) | 0 | 쓰로틀링 없음 |

`total_ms`가 33.1초 → 17.7초로 거의 절반이 됐다. 다만 각 지표의 개선 원인을 정확히 나눠보면:
- `mcp_setup_ms`/`rag_ms` 감소는 이번 라운드([0009](0009-english-only-domain-language-policy.md)의 이중 검색 폐지 + 이 문서의 1·4번 수정)의 직접적인 효과다.
- `llm_ms`가 32% 줄어든 건 이번 라운드의 수정 때문이 아니라, **모델을 `MODEL_CANDIDATES`의 Sonnet 우선 폴백 체인 대신 Haiku 하나로 고정**했기 때문이다(사용자가 직접 하드코딩해 테스트, 위 "고칠 위치" 안내 참고) — Haiku가 Sonnet보다 응답 생성 자체가 빠른 모델이라는 별개의 효과이지, 이 ADR이 다루는 캐싱/재시도 수정과는 무관하다.
- `llm_failed_ms`가 0인 것도 이번 세션 동안 관찰상 Haiku가 Sonnet과 별도의 쿼터 풀을 쓰는 덕에 쓰로틀링을 피한 결과이며, 마찬가지로 이번 라운드의 수정 자체가 만들어낸 효과는 아니다(다만 2번 수정으로 인해 설령 쓰로틀링이 나더라도 그 비용은 훨씬 작아진다).

즉 "거의 절반으로 줄었다"는 결과는 **이번 라운드의 인프라 수정(캐싱/재시도/중복 제거)**과 **모델을 Haiku로 바꾼 효과**가 합쳐진 것이며, 인프라 수정만의 순수 효과는 위 "성능 개선 결과(실측)" 표의 개별 지표(특히 `mcp_setup_ms`, `rag_ms`, 실패한 모델 1개당 비용)로 보는 게 더 정확하다.

## 검증 방법
- 4건 모두 `py_compile`로 컴파일 확인
- `run_query()`를 직접 호출해 실제 trace/성능 지표로 개별 검증(1·2번은 로그 메시지 변화와 `llm_failed_ms` 실측치로, 4번은 `ThreadPoolExecutor`로 20개 동시 호출을 던지는 스트레스 테스트로 확인)
- 실제 `uvicorn` 서버를 기동해 3번(MCP 캐싱)을 종단 간 검증 — 로그상 MCP 서버 배너가 `Application startup complete` 이전에 출력되고, 첫 `/query` 요청부터 `mcp_setup_ms: 0.0`이 나오는 것까지 확인

## 남아 있는 한계
- **`llm_ms`(에이전트 본체 추론 시간) 자체는 줄이지 못했다.** ReAct 루프가 순차적으로 Bedrock을 여러 번 호출하는 구조적 특성([0001](0001-rag-mcp-hybrid-single-agent.md))은 그대로다. 스트리밍 응답(체감 대기 시간 개선)이나 불필요한 턴 감소는 아직 시도하지 않았다.
- **Bedrock 일일 토큰 쿼터 소진**은 이번 조치로 해결할 수 없는 외부 제약이다. 쿼터가 회복되기 전까지는 `total_ms`가 여전히 들쭉날쭉할 수 있다.
- **글로서리·콜드스타트 등 [0010](0010-router-pattern-for-translation.md)의 한계**는 이번 라운드의 범위 밖이라 그대로 남아 있다.
