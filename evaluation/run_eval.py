"""run_eval.py - test_queries.csv 를 전부 실행해 eval_report.csv 로 채점 리포트를 남긴다."""

import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # mini-pjt 루트를 sys.path 에 추가해 src 패키지를 import 한다

from llm_judge import judge_answer
from src.agent import run_query

TEST_QUERIES_PATH = Path(__file__).parent / "test_queries.csv"
REPORT_PATH = Path(__file__).parent / "eval_report.csv"

# SERVICE.md 11절의 성공 기준
PASS_SCORE = 4
PASS_RATE_TARGET = 0.7


def load_test_queries(path: Path = TEST_QUERIES_PATH) -> list[dict]:
    """test_queries.csv 를 읽어 딕셔너리 리스트로 반환한다."""
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


async def evaluate_case(case: dict) -> dict:
    """질문 하나를 에이전트로 실행하고 LLM-judge로 채점한 결과를 반환한다."""
    result = await run_query(case["question"])
    verdict = judge_answer(
        question=case["question"],
        category=case["category"],
        expected_source_url=case["expected_source_url"],
        answer=result["answer"],
        contexts=result["contexts"],
    )
    cited_urls = "; ".join(sorted({c["url"] for c in result["contexts"] if c.get("url")}))
    return {
        "question": case["question"],
        "category": case["category"],
        "expected_source_url": case["expected_source_url"],
        "cited_urls": cited_urls,
        "answer": result["answer"],
        "score": verdict.score,
        "passed": verdict.score >= PASS_SCORE,
        "reasoning": verdict.reasoning,
    }


def save_report(results: list[dict], path: Path = REPORT_PATH) -> None:
    """질문별 채점 결과를 CSV 로 저장한다."""
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)


async def main() -> None:
    """전체 test_queries.csv 를 채점하고 eval_report.csv 에 저장한 뒤 요약을 출력한다.

    한 문항에서 예외(예: Bedrock 쿼터 초과)가 나도 전체를 중단하지 않고, 해당 문항을
    실패로 기록한 뒤 나머지를 계속 진행한다. 그래야 리포트가 항상 남는다.
    """
    cases = load_test_queries()
    results: list[dict] = []
    for case in cases:
        try:
            results.append(await evaluate_case(case))
        except Exception as exc:  # noqa: BLE001 - 어떤 이유로 실패했든 문항 단위로 기록하고 계속 진행한다
            results.append(
                {
                    "question": case["question"],
                    "category": case["category"],
                    "expected_source_url": case["expected_source_url"],
                    "cited_urls": "",
                    "answer": "",
                    "score": 0,
                    "passed": False,
                    "reasoning": f"[실행 오류] {exc}",
                }
            )

    save_report(results)

    total = len(results)
    passed = sum(r["passed"] for r in results)
    errored = [r for r in results if r["reasoning"].startswith("[실행 오류]")]
    avg_score = sum(r["score"] for r in results) / total

    print(f"\n===== 결과: {passed}/{total} 통과 (평균 {avg_score:.2f}점) =====")
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"  [{mark}] ({r['category']}) {r['question'][:40]} - {r['score']}점 - {r['reasoning'][:60]}")

    if errored:
        print(f"\n주의: {len(errored)}개 문항이 실행 오류로 채점되지 못했습니다 (재실행 필요).")

    success = (passed / total) >= PASS_RATE_TARGET
    print(f"\n성공 기준(70% 이상 통과): {'달성' if success else '미달'} ({passed}/{total} = {passed / total:.0%})")
    print(f"리포트 저장: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
