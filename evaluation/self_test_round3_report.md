# 3차 자체 평가 리포트 (출처 정확성 기준)

- 실행 일시: 2026-09-17 17:42
- 전체: 5/11 통과 (평균 2.55점, 5점 만점 중 4점 이상이면 통과)
- 성공 기준(70% 이상 통과): 미달
- 통과 판정은 출처 정확성 채점(self_llm_judge) 기준이며, RAGAS 지표는 참고용으로 별도 표기한다.

## 카테고리별 통과율

| 카테고리 | 통과 | 전체 | 통과율 |
|---|---|---|---|
| 정상 | 4 | 8 | 50% |
| 범위밖 | 1 | 3 | 33% |

## RAGAS 평균 지표 (참고용)

| faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|
| 0.208 | 0.414 | 0.461 | 0.600 |

## 케이스별 상세

| 카테고리 | 질문 | 점수 | 결과 | 인용 출처 | RAGAS(faith/relev/prec/recall) | 판정 사유 |
|---|---|---|---|---|---|---|
| 정상 | Hadoop 개발 환경을 로컬에 구축하려면 어떤 사전 요구사항(자바 버전 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease; https://cwiki.apache.org/confluence/display/HADOOP2/HowToSetupYourDevelopmentEnvironment | 0.71/0.72/1.00/0.81 | 이 답변은 다음 이유로 5점을 받을 자격이 있습니다:  1. **내용 정확성**: 답변에서 제시한 모든 사전 요구사항(Java 버전, Maven |
| 정상 | 패치를 커밋할 때 커밋 메시지에는 어떤 정보를 포함해야 하나요? | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |
| 정상 | 코드 리뷰를 할 때 확인해야 하는 체크리스트 항목에는 어떤 것들이 있나요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/CodeReviewChecklist; https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/Jira | 0.25/0.60/0.77/0.15 | 답변이 기대 출처인 https://cwiki.apache.org/confluence/display/HADOOP2/CodeReviewCheckli |
| 정상 | 새 릴리즈를 준비할 때 커미터가 가장 먼저 해야 하는 준비 작업은 무엇인 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease | 0.00/0.43/0.00/1.00 | 답변이 기대 출처(https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease)에 근거하 |
| 정상 | 우분투 빌드 머신에서 스냅샷 아티팩트를 배포하려면 어떤 설정 파일에 자격 | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |
| 정상 | IntelliJ IDEA에서 Hadoop을 빌드하고 테스트하려면 지금은  | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |
| 정상 | Hadoop 프로젝트는 이슈 관리에 어떤 도구를 쓰고 이슈 작성 시 어떤 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease; https://cwiki.apache.org/confluence/display/HADOOP2/Jira | 0.29/0.73/0.00/0.44 | 답변이 기대 출처(https://cwiki.apache.org/confluence/display/HADOOP2/Jira)에 근거하여 정확하게 작 |
| 정상 | Chukwa 데이터 흐름에서 Agent는 처음에 데이터를 어디에 기록하나 | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |
| 범위밖 | 오늘 서울 날씨가 어떤가요? | 5 | PASS | 없음 | 0.00/0.00/1.00/- | 모델은 날씨 정보를 조회할 수 없다고 정직하게 답변했으며, 자신의 역할(사내 온보딩 문서 및 기술 자료 안내)을 명확히 밝혔습니다. 실제 서울  |
| 범위밖 | 우리 회사 사내 VPN 접속 비밀번호를 알려주세요 | 3 | FAIL | 없음 | 0.00/0.00/0.00/- | 모델이 "사내 VPN 접속 비밀번호와 같은 보안 정보를 제공할 수 없다"고 정확히 거절한 점은 좋습니다. 그러나 이것은 범위밖 질문에 대한 평가 |
| 범위밖 | Kafka 클러스터에 새 Topic을 만드는 방법을 알려주세요 | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |

**주의**: 5개 케이스가 실행 오류로 채점되지 못했습니다(재실행 필요).