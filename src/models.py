"""src 패키지 전체가 공유하는 Bedrock 모델 폴백 후보 목록.

1순위 모델이 쓰로틀링(ThrottlingException 등)되면 다음 모델로 자동 전환한다.
같은 모델의 us./global. 추론 프로필은 별도 용량 풀이라 쓰로틀링 회피에 도움이 된다.
"""

MODEL_CANDIDATES: list[str] = [
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
]
REGION = "us-east-1"
