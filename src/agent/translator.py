"""translator.py - 한국어<->영어 번역. Bedrock LLM과 로컬 전용 모델(NLLB-200) 두 백엔드를
`TRANSLATION_BACKEND` 환경 변수로 고른다 (기본값 bedrock).

라우터 패턴: 번역처럼 규칙이 명확한 단순 작업은 에이전트 본체가 쓰는 무거운 범용 LLM 호출
경로와 분리해서 처리한다는 게 이 모듈의 원래 취지다. 로컬 모델(local)은 Bedrock 쿼터/네트워크와
완전히 무관하다는 장점이 있지만, 실측해보니 (1) 도메인 고유명사를 이따금 오역하고(글로서리로
일부 완화), (2) 프로세스 재시작 후 첫 추론 호출의 콜드스타트 지연이 불규칙하다는 단점이
있었다. 그래서 기본값은 지금까지 검증된 bedrock으로 두고, local은 옵션으로만 제공한다
(architectures/0010-router-pattern-for-translation.md 참고).
"""

import os
import re

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse

from .models import MODEL_CANDIDATES

load_dotenv()

REGION = "us-east-1"

# "bedrock" 또는 "local". 기본값은 MODEL_PROVIDER를 따른다 - MODEL_PROVIDER=google(Bedrock
# 접근이 없는 상황)이면 번역도 자동으로 local(NLLB-200)을 기본값으로 삼는다. TRANSLATION_BACKEND를
# 명시적으로 지정하면 그 값이 항상 우선한다.
_MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "bedrock")
_DEFAULT_TRANSLATION_BACKEND = "bedrock" if _MODEL_PROVIDER == "bedrock" else "local"
TRANSLATION_BACKEND = os.environ.get("TRANSLATION_BACKEND", _DEFAULT_TRANSLATION_BACKEND)

_HANGUL_PATTERN = re.compile(r"[가-힣]")

TRANSLATE_PROMPT = (
    "Translate the text below. If it is written in Korean, translate it to English. "
    "If it is written in English, translate it to Korean. Reply with only the translated "
    "text and nothing else.\n\n{text}"
)

# local 백엔드에서만 쓴다. 이 도메인(Apache Hadoop 생태계)에서 실제로 오역이 확인됐거나 자주
# 쓰이는 한글 음차 외래어 -> 영문 원어. 한국어->영어 번역 전에 그대로 치환해 오역을 막는다
# (예: '커미터'->'comic book artist', '우분투'->'Wrestling' 오역을 실측으로 확인함).
GLOSSARY: dict[str, str] = {
    "하둡": "Hadoop",
    "커미터": "committer",
    "우분투": "Ubuntu",
    "지라": "JIRA",
    "컨플루언스": "Confluence",
    "카프카": "Kafka",
    "스파크": "Spark",
    "자바": "Java",
    "메이븐": "Maven",
    "깃허브": "GitHub",
}

NLLB_MODEL_ID = "facebook/nllb-200-distilled-600M"
MAX_NEW_TOKENS = 200

# local 백엔드를 실제로 쓸 때만 torch/transformers를 임포트하고 모델을 로드한다(지연 로딩).
# 기본 백엔드는 bedrock이라, 대부분의 실행에서는 이 무거운 의존성을 아예 건드리지 않는다.
_local_tokenizer = None
_local_model = None


def _get_local_model():
    """로컬 NLLB-200 모델을 처음 쓰는 시점에 한 번만 로드해 재사용한다."""
    global _local_tokenizer, _local_model
    if _local_model is None:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        _local_tokenizer = AutoTokenizer.from_pretrained(NLLB_MODEL_ID)
        _local_model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL_ID)
    return _local_tokenizer, _local_model


def is_korean(text: str) -> bool:
    """텍스트에 한글 음절이 하나라도 있으면 한국어로 판단한다."""
    return bool(_HANGUL_PATTERN.search(text))


def _apply_glossary(text: str) -> str:
    """알려진 한글 음차 외래어를 영문 원어로 미리 치환한다(한국어->영어 번역 direction 전용)."""
    for korean, english in GLOSSARY.items():
        text = text.replace(korean, english)
    return text


def _translate_bedrock(text: str) -> str:
    """Bedrock LLM으로 번역한다. 쓰로틀링이 나면 MODEL_CANDIDATES 순서대로 재시도한다."""
    prompt = TRANSLATE_PROMPT.format(text=text)
    last_error: Exception | None = None
    for model_id in MODEL_CANDIDATES:
        try:
            llm = ChatBedrockConverse(model=model_id, region_name=REGION, temperature=0, max_retries=1)
            return llm.invoke(prompt).content.strip()
        except ClientError as exc:
            last_error = exc
            print(f"[번역 모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    raise RuntimeError(f"모든 번역 후보 모델이 실패했습니다: {last_error}") from last_error


def _translate_local(text: str) -> str:
    """로컬 NLLB-200 모델로 번역한다. 한국어->영어 방향만 도메인 용어집을 먼저 적용한다."""
    tokenizer, model = _get_local_model()
    korean = is_korean(text)
    src_lang, tgt_lang = ("kor_Hang", "eng_Latn") if korean else ("eng_Latn", "kor_Hang")
    source_text = _apply_glossary(text) if korean else text

    tokenizer.src_lang = src_lang
    batch = tokenizer(source_text, return_tensors="pt")
    target_token_id = tokenizer.convert_tokens_to_ids(tgt_lang)
    output = model.generate(**batch, forced_bos_token_id=target_token_id, max_new_tokens=MAX_NEW_TOKENS)
    return tokenizer.batch_decode(output, skip_special_tokens=True)[0]


def translate(text: str) -> str:
    """text가 한국어면 영어로, 영어면 한국어로 번역한 결과만 돌려준다.

    TRANSLATION_BACKEND 환경 변수로 bedrock(기본값)/local 중 백엔드를 고른다. rag_search의
    한국어 질의어 번역과, 채팅 UI의 답변 번역 요청(POST /translate) 양쪽에서 재사용한다.
    """
    if TRANSLATION_BACKEND == "local":
        return _translate_local(text)
    return _translate_bedrock(text)
