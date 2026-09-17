"""run_eval.py - test_queries.csv 를 전부 실행해 마크다운 리포트(round*_report.md)를 남긴다."""

import asyncio
import csv
from datetime import datetime
from pathlib import Path

from ..agent import run_query
from .llm_judge import judge_answer

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/evaluation -> src -> mini-pjt 루트
EVALUATION_DIR = PROJECT_ROOT / "evaluation"  # test_queries.csv 와 리포트는 여기(비-파이썬 산출물 폴더)에 둔다
TEST_QUERIES_PATH = EVALUATION_DIR / "test_queries.csv"

PASS_SCORE = 4
PASS_RATE_TARGET = 0.7

# test_queries.csv의 expected_tools는 실제 함수명이고, agent.py trace의 step은 API 계약상의 이름이라 매핑이 필요하다.
TOOL_TO_STEP = {
    "rag_search": "retrieve",
    "get_page": "fetch_page",
    "search_confluence": "live_search",
}


def load_test_queries(path: Path = TEST_QUERIES_PATH) -> list[dict]:
    """test_queries.csv 를 읽어 딕셔너리 리스트로 반환한다."""
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _split(field: str) -> list[str]:
    """세미콜론으로 구분된 필드를 리스트로 분해한다. 빈 문자열이면 빈 리스트를 반환한다."""
    return [item.strip() for item in field.split(";") if item.strip()]


def check_tools(case: dict, trace: list[dict]) -> tuple[bool, str]:
    """expected_tools 에 적힌 도구가 실제로 호출됐는지 확인한다. 지정 안 됐으면 통과로 본다."""
    expected = _split(case.get("expected_tools", ""))
    if not expected:
        return True, "지정 없음"
    called_steps = {step["step"] for step in trace}
    expected_steps = {TOOL_TO_STEP.get(name, name) for name in expected}
    missing = expected_steps - called_steps
    if missing:
        return False, f"누락: {', '.join(sorted(missing))}"
    return True, "충족"


async def evaluate_case(case: dict) -> dict:
    """케이스 하나를 에이전트로 실행하고 LLM-judge로 채점한 결과를 반환한다."""
    result = await run_query(case["input"])
    verdict = judge_answer(case, result["answer"])
    tools_ok, tools_detail = check_tools(case, result["trace"])
    cited = "; ".join(sorted({c["doc_id"] for c in result["contexts"] if c.get("doc_id")}))
    return {
        "id": case["id"],
        "category": case["category"],
        "input": case["input"],
        "answer": result["answer"],
        "cited_doc_ids": cited,
        "score": verdict.score,
        "tools_ok": tools_ok,
        "tools_detail": tools_detail,
        "passed": verdict.score >= PASS_SCORE and tools_ok,
        "reasoning": verdict.reasoning,
    }


def _error_result(case: dict, exc: Exception) -> dict:
    """실행 중 예외가 나면 이 케이스를 실패로 기록하고 계속 진행하기 위한 결과를 만든다."""
    return {
        "id": case["id"],
        "category": case["category"],
        "input": case["input"],
        "answer": "",
        "cited_doc_ids": "",
        "score": 0,
        "tools_ok": False,
        "tools_detail": "실행 오류",
        "passed": False,
        "reasoning": f"[실행 오류] {exc}",
    }


def save_markdown_report(results: list[dict], path: Path, round_name: str) -> None:
    """채점 결과를 마크다운 리포트로 저장한다."""
    total = len(results)
    passed = sum(r["passed"] for r in results)
    avg_score = sum(r["score"] for r in results) / total if total else 0.0

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    lines = [
        f"# {round_name} 평가 리포트",
        "",
        f"- 실행 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 전체: {passed}/{total} 통과 (평균 {avg_score:.2f}점, 5점 만점 중 {PASS_SCORE}점 이상 & 필수 도구 호출 충족 시 통과)",
        f"- 성공 기준(70% 이상 통과): {'달성' if total and passed / total >= PASS_RATE_TARGET else '미달'}",
        "",
        "## 카테고리별 통과율",
        "",
        "| 카테고리 | 통과 | 전체 | 통과율 |",
        "|---|---|---|---|",
    ]
    for cat in ("positive", "negative", "edge", "guardrail"):
        items = by_category.get(cat, [])
        if not items:
            continue
        cat_passed = sum(r["passed"] for r in items)
        lines.append(f"| {cat} | {cat_passed} | {len(items)} | {cat_passed / len(items):.0%} |")

    lines += [
        "",
        "## 케이스별 상세",
        "",
        "| id | 카테고리 | 질문 | 점수 | 도구 | 결과 | 판정 사유 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        question = r["input"].replace("|", "\\|").replace("\n", " ")[:50]
        reasoning = r["reasoning"].replace("|", "\\|").replace("\n", " ")[:80]
        lines.append(
            f"| {r['id']} | {r['category']} | {question} | {r['score']} | "
            f"{'OK' if r['tools_ok'] else r['tools_detail']} | {mark} | {reasoning} |"
        )

    errored = [r for r in results if r["reasoning"].startswith("[실행 오류]")]
    if errored:
        lines += [
            "",
            f"**주의**: {len(errored)}개 케이스가 실행 오류로 채점되지 못했습니다(재실행 필요). "
            f"ID: {', '.join(r['id'] for r in errored)}",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")


async def run_round(round_name: str, report_filename: str) -> None:
    """전체 test_queries.csv 를 채점하고 evaluation/{report_filename} 에 마크다운 리포트를 저장한다.

    케이스 하나가 예외(예: Bedrock 쿼터 초과)로 실패해도 전체를 중단하지 않고 계속 진행한다.
    """
    cases = load_test_queries()
    results: list[dict] = []
    for case in cases:
        try:
            results.append(await evaluate_case(case))
        except Exception as exc:  # noqa: BLE001 - 케이스 단위로 실패를 기록하고 계속 진행한다
            results.append(_error_result(case, exc))

    report_path = EVALUATION_DIR / report_filename
    save_markdown_report(results, report_path, round_name)

    total = len(results)
    passed = sum(r["passed"] for r in results)
    print(f"\n===== {round_name}: {passed}/{total} 통과 =====")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] ({r['category']}) #{r['id']} {r['input'][:40]} - {r['score']}점")
    print(f"\n리포트 저장: {report_path}")


async def main() -> None:
    """기본 실행은 1차(round1_report.md)만 돌린다. 2차는 개선 후 run_round('2차', 'round2_report.md')로 별도 실행한다."""
    await run_round("1차", "round1_report.md")


if __name__ == "__main__":
    asyncio.run(main())
