# 2차 자체 평가 리포트 (출처 정확성 기준)

- 실행 일시: 2026-09-17 12:31
- 전체: 10/11 통과 (평균 4.55점, 5점 만점 중 4점 이상이면 통과)
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
| 0.376 | 0.434 | 0.479 | 0.651 |

## 케이스별 상세

| 카테고리 | 질문 | 점수 | 결과 | 인용 출처 | RAGAS(faith/relev/prec/recall) | 판정 사유 |
|---|---|---|---|---|---|---|
| 정상 | Hadoop 개발 환경을 로컬에 구축하려면 어떤 사전 요구사항(자바 버전 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUnderIDEA; https://cwiki.apache.org/confluence/display/HADOOP2/HowToSetupYourDevelopmentEnvironment | 0.85/0.71/0.77/0.81 | 모델 답변은 expected_source_url(https://cwiki.apache.org/confluence/display/HADOOP2/H |
| 정상 | 패치를 커밋할 때 커밋 메시지에는 어떤 정보를 포함해야 하나요? | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/Jira | 0.00/0.31/0.00/0.30 | 이 답변은 5점 만점을 받을 만합니다.   1. **정확성**: 답변 내용이 expected_source_url(https://cwiki.apa |
| 정상 | 코드 리뷰를 할 때 확인해야 하는 체크리스트 항목에는 어떤 것들이 있나요 | 0 | FAIL | 없음 | -/-/-/- | [실행 오류] An error occurred (ThrottlingException) when calling the Converse operat |
| 정상 | 새 릴리즈를 준비할 때 커미터가 가장 먼저 해야 하는 준비 작업은 무엇인 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease | 0.06/0.98/0.00/1.00 | 답변이 expected_source_url(https://cwiki.apache.org/confluence/display/HADOOP2/HowT |
| 정상 | 우분투 빌드 머신에서 스냅샷 아티팩트를 배포하려면 어떤 설정 파일에 자격 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit; https://cwiki.apache.org/confluence/display/HADOOP2/HowToRelease; https://cwiki.apache.org/confluence/display/HADOOP2/HowToSetupUbuntuBuildMachine | 0.82/0.22/1.00/0.40 | 답변이 expected_source_url(HowToSetupUbuntuBuildMachine)에 근거하여 정확한 정보를 제공하고 있습니다.   |
| 정상 | IntelliJ IDEA에서 Hadoop을 빌드하고 테스트하려면 지금은  | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUnderIDEA | 0.68/0.60/0.77/0.73 | 답변이 기대 출처(https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUnderIDEA)의  |
| 정상 | Hadoop 프로젝트는 이슈 관리에 어떤 도구를 쓰고 이슈 작성 시 어떤 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/Jira | 0.78/0.66/0.42/0.55 | 답변이 기대 출처(https://cwiki.apache.org/confluence/display/HADOOP2/Jira)에 근거하여 정확하게 작 |
| 정상 | Chukwa 데이터 흐름에서 Agent는 처음에 데이터를 어디에 기록하나 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/Chukwa+Processes+and+Data+Flow | 0.57/0.85/0.50/0.77 | 답변이 기대 출처 문서(https://cwiki.apache.org/confluence/display/HADOOP2/Chukwa+Processe |
| 범위밖 | 오늘 서울 날씨가 어떤가요? | 5 | PASS | 없음 | 0.00/0.00/1.00/- | 모델이 범위밖 질문에 대해 완벽하게 대응했습니다.   1. 명확한 거부: "컨플루언스 문서에서 서울 날씨에 관한 정보를 찾을 수 없습니다"라고  |
| 범위밖 | 우리 회사 사내 VPN 접속 비밀번호를 알려주세요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit | 0.00/0.00/0.00/- | 모델이 "컨플루언스 문서에서 사내 VPN 접속 비밀번호에 관련된 내용을 찾지 못했습니다"라고 명확하게 밝혔습니다. 이후 제공한 조언(IT 지원팀 |
| 범위밖 | Kafka 클러스터에 새 Topic을 만드는 방법을 알려주세요 | 5 | PASS | https://cwiki.apache.org/confluence/display/HADOOP2/Chukwa+Processes+and+Data+Flow; https://cwiki.apache.org/confluence/display/HADOOP2/HadoopUnderIDEA; https://cwiki.apache.org/confluence/display/HADOOP2/HowToCommit | 0.00/0.00/0.33/- | 모델이 문서에서 관련 내용을 찾지 못했다고 명확하게 밝혔습니다("컨플루언스 문서에서...내용을 찾지 못했습니다", "관련 문서가 등록되어 있지  |

**주의**: 1개 케이스가 실행 오류로 채점되지 못했습니다(재실행 필요).