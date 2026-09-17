"""src 패키지 전체가 공유하는 모델 폴백 후보 목록.

1순위 모델이 쓰로틀링(ThrottlingException 등)되면 다음 모델로 자동 전환한다.
같은 모델의 us./global. 추론 프로필은 별도 용량 풀이라 쓰로틀링 회피에 도움이 된다.

Bedrock(MODEL_CANDIDATES)은 AX 교육 기간에 쓰는 기본 제공자다. 교육이 끝나면 Bedrock 접근이
끊기므로, GOOGLE_MODEL_CANDIDATES를 대체 경로로 함께 둔다(.env의 MODEL_PROVIDER=google로 전환,
architectures/0014-google-ai-studio-fallback-provider.md 참고).
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

# client.models.list()로 실제 API 키에서 사용 가능한 모델명을 직접 확인했다(2026-09-17).
# gemini-2.5-flash는 목록엔 있지만 실제 호출 시 "no longer available to new users" 404가
# 나서(신규 키 정책으로 보임) 제외했다 - list_models()에 있다고 실제로 호출 가능하다는
# 보장은 아니다. 무료/저가 API 키 기준 쿼터가 넉넉하지 않아, 쿼터 여유가 상대적으로 큰
# flash/lite 계열을 먼저 둔다.
GOOGLE_MODEL_CANDIDATES: list[str] = [
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
]
GOOGLE_EMBEDDING_MODEL_ID = "models/gemini-embedding-001"
