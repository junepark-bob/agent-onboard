# 1차 자체 평가 리포트 (출처 정확성 기준)

- 실행 일시: 2026-09-17 11:04
- 전체: 10/11 통과 (평균 4.82점, 5점 만점 중 4점 이상이면 통과)
- 성공 기준(70% 이상 통과): 달성
- 통과 판정은 출처 정확성 채점(self_llm_judge) 기준이며, RAGAS 지표는 참고용으로 별도 표기한다.

## 카테고리별 통과율

| 카테고리 | 통과 | 전체 | 통과율 |
|---|---|---|---|
| 정상 | 7 | 8 | 88% |
| 범위밖 | 3 | 3 | 100% |

## RAGAS 평균 지표 (참고용)

| faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|
| 0.341 | 0.424 | 0.634 | 0.627 |

## 케이스별 상세

| 카테고리 | 질문 | 점수 | 결과 | 인용 출처 | RAGAS(faith/relev/prec/recall) | 판정 사유 |
|---|---|---|---|---|---|---|
| 정상 | Hadoop 개발 환경을 로컬에 구축하려면 어떤 사전 요구사항(자바 버전 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUn | 0.94/0.72/1.00/0.81 | 답변이 expected_source_url(HowToSetupYourDevelopmentEnvironment)에 근거하여 정확한 정보를 제공하고 |
| 정상 | 패치를 커밋할 때 커밋 메시지에는 어떤 정보를 포함해야 하나요? | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCom | 0.00/0.31/0.00/0.63 | 답변이 expected_source_url(https://cwiki.apache.org/confluence/display/HADOOP2/HowT |
| 정상 | 코드 리뷰를 할 때 확인해야 하는 체크리스트 항목에는 어떤 것들이 있나요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/CodeRevi | 0.10/0.59/1.00/0.15 | 답변이 기대 출처인 https://cwiki.apache.org/confluence/display/HADOOP2/CodeReviewCheckli |
| 정상 | 새 릴리즈를 준비할 때 커미터가 가장 먼저 해야 하는 준비 작업은 무엇인 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCom | 0.00/0.43/0.00/0.70 | 답변이 expected_source_url(https://cwiki.apache.org/confluence/display/HADOOP2/HowT |
| 정상 | 우분투 빌드 머신에서 스냅샷 아티팩트를 배포하려면 어떤 설정 파일에 자격 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCom | 0.82/0.36/1.00/0.40 | 답변이 기대 출처(HowToSetupUbuntuBuildMachine)에 근거하여 정확한 정보를 제공하고 있습니다.   1. 정확성: ~/.m2 |
| 정상 | IntelliJ IDEA에서 Hadoop을 빌드하고 테스트하려면 지금은  | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUn | 0.44/0.80/1.00/1.00 | 답변이 expected_source_url 문서(https://cwiki.apache.org/confluence/display/HADOOP2/H |
| 정상 | Hadoop 프로젝트는 이슈 관리에 어떤 도구를 쓰고 이슈 작성 시 어떤 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/Jira | 0.78/0.66/0.42/0.55 | 답변이 기대 출처(https://cwiki.apache.org/confluence/display/HADOOP2/Jira)에 근거하여 정확하게 작 |
| 정상 | Chukwa 데이터 흐름에서 Agent는 처음에 데이터를 어디에 기록하나 | 3 | FAIL | https://cwiki.apache.org/confluence/display/HADOOP2/Chukwa+P | 0.67/0.78/0.50/0.77 | 답변 내용을 분석하면:  1. **출처 일치 여부**: 시스템에서 확인된 바에 따르면 정확한 출처(expected_source_url)를 인용했 |
| 범위밖 | 오늘 서울 날씨가 어떤가요? | 5 | PASS | 없음 | 0.00/0.00/1.00/- | 모델이 범위밖 질문에 대해 매우 적절하게 대응했습니다.   평가 근거: 1. 정직한 답변: 자신이 회사 내부 컨플루언스 문서를 검색하는 온보딩  |
| 범위밖 | 우리 회사 사내 VPN 접속 비밀번호를 알려주세요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCom | 0.00/0.00/0.25/- | 모델은 "검색 결과에서도 VPN 접속 비밀번호와 관련된 내용은 전혀 찾을 수 없었습니다"라고 명확하게 문서에 근거가 없음을 밝혔습니다. 또한 사 |
| 범위밖 | Kafka 클러스터에 새 Topic을 만드는 방법을 알려주세요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/Chukwa+P | 0.00/0.00/0.80/- | 모델이 문서에서 관련 내용을 찾지 못했다고 명확하게 밝혔으며("컨플루언스 문서에서... 찾지 못했습니다"), 사전 지식을 활용하여 Kafka T |