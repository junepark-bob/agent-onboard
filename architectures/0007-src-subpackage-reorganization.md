# 0007. `src/`를 역할별 서브패키지로 재구성하고 `agent/__init__.py`로 내부를 숨김

- 상태: 채택
- 관련 코드: `src/agent/__init__.py`, `src/agent/`, `src/crawler/`, `src/server/`, `src/evaluation/`

## 맥락
처음에는 `src/agent.py`, `src/tools.py`, `src/retriever.py`, `src/models.py`, 그리고 루트의 `server.py`, `crawl_confluence.py`, `evaluation/*.py`가 모두 평평하게 흩어져 있었습니다. 파일이 하나둘 늘면서 "이 파일이 에이전트 쪽인지, 서버 쪽인지, 평가 쪽인지"가 파일 이름만으로는 구분되지 않는 문제가 생겼습니다. `CLAUDE.md`에는 한때 이 평평한 구조가 "제출 규약(바꾸지 않는다)"이라고 적혀 있었지만, 이는 실제 운영 측이 내려준 제약이 아니라 프로젝트를 분석해서 작성한 문서였다는 점이 확인되어, 구조를 자유롭게 재정리할 수 있었습니다.

## 결정
모든 파이썬 코드를 `src/` 아래 역할별 서브패키지로 옮겼습니다: `src/agent/`(에이전트+RAG+MCP 도구+모델 목록), `src/crawler/`(크롤링), `src/server/`(FastAPI), `src/evaluation/`(평가). 이 중 `src/agent/`는 내부에 `agent.py`/`tools.py`/`retriever.py`/`models.py` 네 파일이 있지만, 외부(서버/크롤러/평가)는 이 파일들을 직접 참조하지 않고 반드시 `src/agent/__init__.py`가 재노출하는 `run_query`/`MODEL_CANDIDATES`/`REGION`만 통해서 접근합니다(`from ..agent import run_query`).

## 결과/트레이드오프
- **장점**: `agent` 패키지 내부에 파일이 몇 개 있는지, 어떻게 나뉘어 있는지를 외부가 몰라도 됩니다. 실제로 이번 재구성에서 파일이 여러 번 옮겨졌지만(`src/agent.py` → `src/agent/agent.py`), `__init__.py`의 재노출 인터페이스만 유지하면 다른 패키지의 임포트 문(`from ..agent import run_query`)은 전혀 손댈 필요가 없었습니다.
- **주의점**: 상대 임포트(`from ..agent import ...`)를 쓰기 때문에 모든 스크립트를 파일로 직접 실행(`python server.py`)할 수 없고, 반드시 `mini-pjt/` 루트에서 모듈로 실행(`uvicorn src.server.server:app`, `python -m src.evaluation.run_eval`)해야 합니다. 실제로 이 차이 때문에 "`uvicorn server:app`을 실행하면 `ImportError: attempted relative import with no known parent package`가 난다"는 혼동이 반복적으로 발생했습니다 — 코드 문제가 아니라 실행 방식/실행 위치 문제이므로, `CLAUDE.md`의 "실행 명령" 절에 정확한 커맨드를 명시해뒀습니다.
- **파일 경로 상수**: 파일이 한 단계씩 깊어질 때마다 `Path(__file__).resolve().parents[N]`의 `N`을 다시 계산해야 했습니다(`src/agent/retriever.py`는 `parents[2]`). 재구성할 때마다 이 상수들을 놓치지 않고 같이 확인해야 합니다.
