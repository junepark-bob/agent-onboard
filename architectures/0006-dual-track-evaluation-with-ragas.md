# 0006. 평가를 운영 스키마 / 자체 출처-정확성 스키마 두 트랙 + RAGAS 보조 지표로 구성

- 상태: 채택
- 관련 코드: `src/evaluation/llm_judge.py`+`run_eval.py`(운영 스키마), `src/evaluation/self_llm_judge.py`+`self_run_eval.py`(자체 스키마), `src/evaluation/ragas_eval.py`(RAGAS)

## 맥락
평가셋은 원래 자체적으로 `question`/`category`(정상/범위밖)/`expected_source_url` 스키마로 설계했었는데, 이후 과제 운영 측이 `id`/`category`(positive/negative/edge/guardrail)/`expected_traits`/`forbidden`/`expected_tools`/`note`라는 별도 스키마를 내려줬습니다. 운영 측에 "지금(출처 정확성 중심) 채점 기준도 괜찮다"는 피드백을 받은 뒤, 두 스키마를 하나로 합치지 않고 병행하기로 했습니다. 여기에 더해 RAGAS(faithfulness/answer_relevancy/context_precision/context_recall) 도입 필요성도 논의됐습니다.

## 결정
- **운영 스키마 트랙**: `evaluation/test_queries.csv`(20건) → `llm_judge.py`(5점 만점, `expected_traits`/`forbidden` 기반 rubric) → `run_eval.py` → `round1_report.md`/`round2_report.md`.
- **자체 스키마 트랙**: `evaluation/test_self_queries.csv`(11건) → `self_llm_judge.py`(출처 URL 일치 여부를 최우선으로 채점) → `self_run_eval.py` → `self_test_round1_report.md`/`self_test_round2_report.md`.
- **RAGAS는 자체 스키마 트랙에만 참고 지표로 추가**했습니다. 통과/실패 판정은 그대로 `self_llm_judge`(출처 정확성) 기준으로 하고, RAGAS 4개 지표는 리포트에 별도 표로만 덧붙입니다.

## 결과/트레이드오프
- **장점**: 두 채점 기준(트레잇 기반 vs 출처 기반)이 서로 다른 실패를 잡아낼 수 있어 하나로 합치는 것보다 더 많은 정보를 남깁니다. RAGAS도 코드를 건드리지 않고 관찰만 늘리는 방식으로 추가할 수 있었습니다.
- **비용**: 케이스 하나당 에이전트 호출 1회 + judge 호출 1회 + RAGAS 지표 4개(각각 LLM/임베딩 호출)가 추가로 필요해, 자체 스키마 트랙 하나를 실행하는 데만 케이스당 수십 초가 걸립니다. 11건 기준 라운드 하나에 10분 이상 소요됩니다.
- **RAGAS 도입 중 실제로 겪은 사고**: `ragas`(0.3.0)가 임포트 시점에 `nest_asyncio.apply()`를 무조건 실행하는데, 이게 `anyio`의 이벤트 루프 감지를 깨뜨려서 같은 프로세스에서 실행되는 `run_query()`의 MCP 서브프로세스 실행(`anyio.open_process`)이 `NoEventLoopError`로 전부 실패했습니다. RAGAS 자체는 격리된 스크립트로 테스트했을 때 멀쩡했기 때문에, `self_run_eval.py`처럼 에이전트 실행과 RAGAS 채점을 같은 프로세스에서 같이 쓰기 전까지는 드러나지 않은 문제였습니다. 이미 RAGAS의 공개 비동기 wrapper(`single_turn_ascore`)를 우회해서 쓰고 있어 `nest_asyncio`의 재진입 기능 자체가 필요 없었으므로, `nest_asyncio` 모듈을 무해한 스텁으로 등록해 부작용만 제거하는 방식으로 해결했습니다(`ragas_eval.py`).
- **RAGAS 수치의 신뢰도**: 일부 케이스에서 judge가 5점(정확)으로 판정한 답변인데도 `faithfulness`/`context_precision`이 0.00으로 나오는 경우가 있었습니다 — RAGAS의 내부 채점 방식(문장 단위 분해)과 이 프로젝트 답변 스타일(짧은 인용 위주) 간의 궁합 문제로 추정되며, 원인은 아직 조사 중입니다. 그래서 RAGAS를 통과/실패의 1차 기준으로 쓰지 않고 참고 지표로만 두는 이번 결정이 지금 시점에는 더 안전합니다.
