# 0014. Google AI Studio를 Bedrock 접근 종료 대비 대체 제공자로 추가

- 상태: 채택 (구현 완료, 종단 간 실측 1건으로 검증)
- 관련 코드: `src/agent/llm_factory.py`(신규), `src/agent/models.py`, `src/agent/agent.py`, `src/agent/retriever.py`, `src/agent/translator.py`
- 관련 문서: [0003](0003-model-fallback-chain.md)(모델 폴백 체인), [0010](0010-router-pattern-for-translation.md)(번역 백엔드 선택)

## 맥락
이 프로젝트는 AX 교육 기간 동안 제공되는 Bedrock 계정으로 개발·검증됐다. 교육이 끝나면 이 Bedrock 접근이 끊기므로, 기존 코드(Bedrock 경로)는 그대로 유지하면서 `.env`의 `GOOGLE_API_KEY`(Google AI Studio API 키)만으로 계속 실행할 수 있는 대체 경로가 필요했다.

## 결정
`MODEL_PROVIDER` 환경 변수(기본값 `bedrock`)로 두 제공자를 고른다.

1. **`src/agent/llm_factory.py`(신규)**: `active_model_candidates()`(제공자별 모델 폴백 후보 목록), `build_chat_model(model_id)`(제공자에 맞는 채팅 모델 인스턴스 생성), `is_retryable_error(exc)`(폴백 루프에서 "다음 후보로 넘어갈 실패"인지 제공자별로 판단)를 제공한다. `agent.py`는 더 이상 `ChatBedrockConverse`를 직접 만들지 않고 이 팩토리에 위임한다.
2. **`src/agent/models.py`**: `GOOGLE_MODEL_CANDIDATES`(`gemini-3.6-flash` → `gemini-3.5-flash-lite` → `gemini-3.5-flash`)와 `GOOGLE_EMBEDDING_MODEL_ID`(`models/gemini-embedding-001`)를 추가했다.
3. **`src/agent/retriever.py`**: 임베딩 클라이언트(`_embeddings()`)도 `MODEL_PROVIDER`를 따른다. **제공자마다 임베딩 벡터 공간이 달라 인덱스를 공유할 수 없으므로**, `PERSIST_DIR`을 `chroma_db`(bedrock)와 `chroma_db_google`(google)로 완전히 분리했다 — 전환 시 기존 인덱스를 잘못된 임베딩으로 검색하는 사고를 코드 레벨에서 막는다. 대신 제공자를 바꾸면 `python -m src.agent.retriever`로 해당 제공자의 인덱스를 새로 만들어야 한다.
4. **`src/agent/translator.py`**: `TRANSLATION_BACKEND`의 기본값이 `MODEL_PROVIDER`를 따라가게 했다 — `MODEL_PROVIDER=google`인데 `TRANSLATION_BACKEND`를 따로 지정하지 않으면 자동으로 `local`(NLLB-200, [0010](0010-router-pattern-for-translation.md))이 된다. `TRANSLATION_BACKEND=bedrock`으로 번역만 계속 Bedrock을 쓰게 강제로 지정하지 않는 한, `MODEL_PROVIDER` 하나만 바꿔도 시스템 전체가 Bedrock 없이 동작한다.

## 구현 중 실제로 발견하고 고친 문제
API 호출 없이 확인할 수 있는 것(Pydantic 필드명)은 코드 실행 전에 미리 검증했지만, 아래 세 가지는 실제 호출을 한 번씩 해봐야 알 수 있었다.

1. **임베딩 모델명 오류**: 처음 썼던 `models/text-embedding-004`는 이 API 버전에서 404였다. `client.models.list()`(생성 호출이 아닌 메타데이터 조회라 쿼터 소모가 적다)로 실제 사용 가능한 임베딩 모델을 확인해 `models/gemini-embedding-001`로 교체했다.
2. **`is_retryable_error()`의 예외 계층 오판**: 처음엔 `isinstance(exc, ModelAPIError)`로 판단했는데, 실제로 첫 종단 간 테스트에서 `GoogleModelNotFoundError`가 나면서 폴백 없이 그대로 예외가 올라갔다. 확인해보니 `ModelAPIError`/`ModelNotFoundError`/`ModelRateLimitError`는 전부 `ModelError`의 "형제" 서브클래스이지 `ModelAPIError`의 자식이 아니었다 — 공통 부모인 `ModelError`로 잡도록 고쳤다.
3. **`gemini-2.5-flash`가 이 계정에서 막혀 있음**: `list_models()` 응답에는 있었지만 실제 호출 시 "This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.6-flash" 404가 났다. **모델 목록에 있다고 실제로 호출 가능하다는 보장은 아니라는 걸 확인**했고, 에러 메시지가 권장한 `gemini-3.6-flash`로 교체했다.

## 검증
쿼터가 넉넉하지 않다는 요청에 따라 실제 생성 호출은 최소화했다.
- 객체 생성(Pydantic 검증)까지는 API 호출 없이 확인: 기본값(Bedrock)이 기존과 동일하게 동작하는지, `MODEL_PROVIDER=google`일 때 `ChatGoogleGenerativeAI`/`GoogleGenerativeAIEmbeddings`/`PERSIST_DIR`/`TRANSLATION_BACKEND`가 전부 의도대로 전환되는지 확인했다.
- `client.models.list()`로 실제 사용 가능한 모델명을 확인(메타데이터 조회, 저비용).
- `python -m src.agent.retriever`로 `chroma_db_google` 인덱스를 1회 생성(RAG가 동작하려면 반드시 필요한 실제 작업이지, 테스트용 소모가 아니다).
- `run_query()` 종단 간 실행 **1회**로 최종 확인 — RAG 검색(712.2ms, 컨텍스트 5개), MCP 도구, 최종 답변 생성, 정확한 출처 인용까지 전부 정상 동작했다.

## 결과/트레이드오프
- **장점**: `MODEL_PROVIDER=google` 하나만 `.env`에 설정하면(추가로 `TRANSLATION_BACKEND` 조정 불필요) 에이전트 본체·RAG 임베딩·번역까지 전부 Bedrock 없이 동작한다. 기존 Bedrock 경로는 코드/동작 모두 변경 없이 그대로 유지된다(기본값이 bedrock).
- **알려진 제약**: `gemini-3.6-flash`는 "fixed sampling defaults"라 `temperature=0` 설정이 무시된다는 경고가 실측에서 나왔다 — 평가 재현성 목적(`TEMPERATURE = 0`)이 이 모델에서는 완전히 보장되지 않는다.
- **범위 밖으로 남겨둔 것**: 크롤러의 비전 모델(`crawl_confluence.py`)과 평가용 judge 모델(`llm_judge.py`/`self_llm_judge.py`/`ragas_eval.py`)은 여전히 Bedrock 전용이다. 크롤링은 일회성 오프라인 작업이고 judge는 평가 전용이라, 실제 서비스 응답(agent.py)과 RAG(retriever.py)만 우선 다뤘다. Bedrock이 완전히 끊긴 뒤 크롤링/평가를 다시 돌려야 한다면 추가 작업이 필요하다.
- **인덱스 재구축 필요**: 제공자를 전환하면 해당 제공자용 `chroma_db_google`을 최초 1회 빌드해야 한다(자동화 안 됨, 수동으로 `python -m src.agent.retriever` 실행).
