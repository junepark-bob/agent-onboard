# 아키텍처 결정 기록 (ADR)

이 폴더는 이 프로젝트를 만들면서 실제로 내린 아키텍처 결정들을 기록해둔 곳입니다. 나중에 "왜 이렇게 만들었더라?"를 코드만 보고는 알기 어려운 결정들 — 특히 대안을 검토했지만 채택하지 않은 이유 — 을 남기는 데 목적이 있습니다.

형식은 가볍게 [Michael Nygard의 ADR 템플릿](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)을 따랐습니다: 맥락(Context) → 결정(Decision) → 결과/트레이드오프(Consequences).

## 목록

| 번호 | 제목 | 상태 |
|---|---|---|
| [0001](0001-rag-mcp-hybrid-single-agent.md) | RAG + MCP 하이브리드를 단일 ReAct 에이전트로 구성 | 채택 |
| [0002](0002-bilingual-rag-search.md) | 이중 언어(한/영) 동시 검색으로 교차언어 임베딩 약점 우회 | 채택 |
| [0003](0003-model-fallback-chain.md) | 고정 모델 대신 폴백 후보 목록으로 쓰로틀링 대응 | 채택 |
| [0004](0004-single-agent-not-supervisor.md) | Multi-Agent Supervisor 대신 단일 에이전트 유지 | 채택 (스코프 판단) |
| [0005](0005-mcp-tool-scope-enforcement.md) | 도구 실행 범위(스페이스 스코프)는 프롬프트가 아니라 코드로 강제 | 채택 |
| [0006](0006-dual-track-evaluation-with-ragas.md) | 평가를 운영 스키마 / 자체 출처-정확성 스키마 두 트랙 + RAGAS 보조 지표로 구성 | 채택 |
| [0007](0007-src-subpackage-reorganization.md) | `src/` 를 역할별 서브패키지로 재구성하고 `agent/__init__.py`로 내부를 숨김 | 채택 |
| [0008](0008-performance-instrumentation.md) | 성능 계측은 콜백 기반 실측으로, replay 방식은 계측 사각지대로 재평가 | 채택 (일부 후속 조치 진행 중) |

## 참고
각 ADR의 배경이 된 더 상세한 검토/실측 로그는 `data/documents/ISSUES.md`에 있습니다. 이 폴더의 ADR은 그 검토 결과를 "결정"으로 압축·정리한 버전입니다.
