# 0003. 고정 모델 대신 폴백 후보 목록으로 쓰로틀링 대응

- 상태: 채택
- 관련 코드: `src/agent/models.py`(`MODEL_CANDIDATES`), `src/agent/agent.py`, `src/agent/retriever.py`(번역), `src/crawler/crawl_confluence.py`(비전), `src/evaluation/llm_judge.py`/`self_llm_judge.py`(채점)

## 맥락
Bedrock 모델 호출은 개발/평가 중 반복적으로 `ThrottlingException`(계정/모델별 요청 한도 초과, 심할 때는 "Too many tokens per day" 같은 일일 한도 초과)에 부딪힙니다. 단일 모델 ID로 고정하면 쓰로틀링이 발생하는 즉시 그 요청 전체가 실패합니다. 이 저장소 day5의 가드레일/재시도 패턴을 그대로 가져다 쓸 수는 없었지만(day5는 별도 사유로 스코프 아웃, [0004](0004-single-agent-not-supervisor.md) 참고), "실패하면 대체 경로로 재시도한다"는 목적은 같습니다.

## 결정
같은 모델의 `us.`/`global.` 추론 프로필(별도 용량 풀)과 Claude Sonnet/Haiku, Amazon Nova Pro/Lite 등 여러 후보를 우선순위 목록(`MODEL_CANDIDATES`)으로 두고, `ClientError`(쓰로틀링 포함)가 나면 다음 후보로 자동 전환해 재시도합니다. 이 패턴을 에이전트 본체뿐 아니라 번역, 이미지 설명(비전), LLM-judge 채점까지 Bedrock을 호출하는 모든 지점에 동일하게 적용했습니다.

## 결과/트레이드오프
- **장점**: 평가처럼 짧은 시간에 많은 요청을 보내는 워크로드에서도 실행이 중간에 끊기지 않고 끝까지 진행됩니다. 실제로 자체 평가 실행 중 1순위 모델이 일일 토큰 한도로 반복 쓰로틀링됐지만, 폴백 목록 덕분에 평가 자체는 끝까지 완료됐습니다.
- **단점**: 후보 목록 뒤쪽 모델(Haiku, Nova Lite 등)로 넘어가면 응답 품질/일관성이 1순위 모델(Sonnet)과 달라질 수 있는데, 지금은 이 차이를 별도로 측정하거나 리포트에 표시하지 않습니다 — `trace`의 `model_select` 단계에 실제로 어떤 모델이 쓰였는지는 남기지만, 폴백이 실제로 발생했는지에 따른 품질 편차를 평가 리포트에서 구분하지는 않습니다.
- **재현성**: 평가 재현성을 위해 온도(temperature)는 0으로 고정했지만, 폴백으로 모델 자체가 바뀌면 temperature=0이어도 동일 질문에 다른 모델이 응답할 수 있어 완전한 재현성은 보장되지 않습니다.
