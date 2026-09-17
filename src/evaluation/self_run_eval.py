"""self_run_eval.py - test_self_queries.csv 를 전부 실행해 마크다운 리포트(self_test_round*_report.md)를 남긴다.

llm_judge/run_eval(운영 스키마)과 나란히 두는 자체 평가 트랙이다. 채점은 self_llm_judge(출처
정확성 최우선)로 하고, RAGAS 지표(faithfulness/answer_relevancy/context_precision/context_recall)는
참고용으로 함께 계산해 리포트에 덧붙인다. 통과 판정은 기존 방식대로 self_llm_judge 점수만 본다.
"""

import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path

from ..agent import run_query
from .ragas_eval import score_case
from .self_llm_judge import judge_answer

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/evaluation -> src -> mini-pjt 루트
EVALUATION_DIR = PROJECT_ROOT / "evaluation"
TEST_SELF_QUERIES_PATH = EVALUATION_DIR / "test_self_queries.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

PASS_SCORE = 4
PASS_RATE_TARGET = 0.7


def load_test_self_queries(path: Path = TEST_SELF_QUERIES_PATH) -> list[dict]:
    """test_self_queries.csv 를 읽어 딕셔너리 리스트로 반환한다."""
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_reference_texts(raw_dir: Path = RAW_DIR) -> dict[str, str]:
    """data/raw/*.json 을 훑어 {페이지 url: 본문} 맵을 만든다. RAGAS context_recall의 reference로 쓴다."""
    references: dict[str, str] = {}
    for path in raw_dir.glob("*.json"):
        page = json.loads(path.read_text(encoding="utf-8"))
        references[page["url"]] = page["content"]
    return references


async def evaluate_case(case: dict, reference_texts: dict[str, str]) -> dict:
    """케이스 하나를 에이전트로 실행하고 self_llm_judge + RAGAS로 채점한 결과를 반환한다."""
    result = await run_query(case["question"])
    cited_doc_ids = sorted({c["doc_id"] for c in result["contexts"] if c.get("doc_id")})

    verdict = judge_answer(case, result["answer"], cited_doc_ids)

    reference = reference_texts.get(case["expected_source_url"]) if case["category"] == "정상" else None
    ragas_scores = await score_case(
        question=case["question"],
        answer=result["answer"],
        contexts=[c["text"] for c in result["contexts"]],
        reference=reference,
    )

    return {
        "question": case["question"],
        "category": case["category"],
        "expected_source_url": case["expected_source_url"],
        "answer": result["answer"],
        "cited_doc_ids": "; ".join(cited_doc_ids),
        "score": verdict.score,
        "passed": verdict.score >= PASS_SCORE,
        "reasoning": verdict.reasoning,
        "ragas": ragas_scores,
    }


def _error_result(case: dict, exc: Exception) -> dict:
    """실행 중 예외가 나면 이 케이스를 실패로 기록하고 계속 진행하기 위한 결과를 만든다."""
    return {
        "question": case["question"],
        "category": case["category"],
        "expected_source_url": case["expected_source_url"],
        "answer": "",
        "cited_doc_ids": "",
        "score": 0,
        "passed": False,
        "reasoning": f"[실행 오류] {exc}",
        "ragas": {"faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": None},
    }


def _avg(values: list[float | None]) -> float | None:
    """None을 제외한 값들의 평균을 반환한다. 값이 하나도 없으면 None."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def save_markdown_report(results: list[dict], path: Path, round_name: str) -> None:
    """채점 결과를 마크다운 리포트로 저장한다."""
    total = len(results)
    passed = sum(r["passed"] for r in results)
    avg_score = sum(r["score"] for r in results) / total if total else 0.0

    by_category: dict[str, list[dict]] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    ragas_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    ragas_avgs = {k: _avg([r["ragas"].get(k) for r in results]) for k in ragas_keys}

    lines = [
        f"# {round_name} 자체 평가 리포트 (출처 정확성 기준)",
        "",
        f"- 실행 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 전체: {passed}/{total} 통과 (평균 {avg_score:.2f}점, 5점 만점 중 {PASS_SCORE}점 이상이면 통과)",
        f"- 성공 기준(70% 이상 통과): {'달성' if total and passed / total >= PASS_RATE_TARGET else '미달'}",
        "- 통과 판정은 출처 정확성 채점(self_llm_judge) 기준이며, RAGAS 지표는 참고용으로 별도 표기한다.",
        "",
        "## 카테고리별 통과율",
        "",
        "| 카테고리 | 통과 | 전체 | 통과율 |",
        "|---|---|---|---|",
    ]
    for cat in ("정상", "범위밖"):
        items = by_category.get(cat, [])
        if not items:
            continue
        cat_passed = sum(r["passed"] for r in items)
        lines.append(f"| {cat} | {cat_passed} | {len(items)} | {cat_passed / len(items):.0%} |")

    lines += [
        "",
        "## RAGAS 평균 지표 (참고용)",
        "",
        "| faithfulness | answer_relevancy | context_precision | context_recall |",
        "|---|---|---|---|",
        "| "
        + " | ".join(f"{ragas_avgs[k]:.3f}" if ragas_avgs[k] is not None else "N/A" for k in ragas_keys)
        + " |",
        "",
        "## 케이스별 상세",
        "",
        "| 카테고리 | 질문 | 점수 | 결과 | 인용 출처 | RAGAS(faith/relev/prec/recall) | 판정 사유 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        question = r["question"].replace("|", "\\|").replace("\n", " ")[:40]
        cited = r["cited_doc_ids"].replace("|", "\\|")[:60] or "없음"
        reasoning = r["reasoning"].replace("|", "\\|").replace("\n", " ")[:80]
        ragas = r["ragas"]
        ragas_str = "/".join(f"{ragas[k]:.2f}" if ragas.get(k) is not None else "-" for k in ragas_keys)
        lines.append(
            f"| {r['category']} | {question} | {r['score']} | {mark} | {cited} | {ragas_str} | {reasoning} |"
        )

    errored = [r for r in results if r["reasoning"].startswith("[실행 오류]")]
    if errored:
        lines += [
            "",
            f"**주의**: {len(errored)}개 케이스가 실행 오류로 채점되지 못했습니다(재실행 필요).",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")


async def run_round(round_name: str, report_filename: str) -> None:
    """전체 test_self_queries.csv 를 채점하고 evaluation/{report_filename} 에 마크다운 리포트를 저장한다.

    케이스 하나가 예외로 실패해도 전체를 중단하지 않고 계속 진행한다.
    """
    cases = load_test_self_queries()
    reference_texts = _load_reference_texts()
    results: list[dict] = []
    for case in cases:
        try:
            results.append(await evaluate_case(case, reference_texts))
        except Exception as exc:  # noqa: BLE001 - 케이스 단위로 실패를 기록하고 계속 진행한다
            results.append(_error_result(case, exc))

    report_path = EVALUATION_DIR / report_filename
    save_markdown_report(results, report_path, round_name)

    total = len(results)
    passed = sum(r["passed"] for r in results)
    print(f"\n===== {round_name}: {passed}/{total} 통과 =====")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] ({r['category']}) {r['question'][:40]} - {r['score']}점")
    print(f"\n리포트 저장: {report_path}")


async def main() -> None:
    """기본 실행은 1차(self_test_round1_report.md)만 돌린다. 2차는 개선 후 별도 실행한다."""
    await run_round("1차", "self_test_round1_report.md")


if __name__ == "__main__":
    asyncio.run(main())
