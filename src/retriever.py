"""data/raw/ 의 문서를 chroma_db로 임베딩하고 의미 검색을 제공하는 RAG 파이프라인."""

import json
from pathlib import Path

from botocore.exceptions import ClientError
from dotenv import load_dotenv
from langchain_aws import BedrockEmbeddings, ChatBedrockConverse
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .models import MODEL_CANDIDATES

load_dotenv()

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
REGION = "us-east-1"

TRANSLATE_PROMPT = (
    "Translate the text below. If it is written in Korean, translate it to English. "
    "If it is written in English, translate it to Korean. Reply with only the translated "
    "text and nothing else.\n\n{text}"
)
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PERSIST_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "confluence_onboarding"
SIMILARITY_THRESHOLD = 0.3
# 주의: 검색어는 반드시 영어여야 한다. 한국어 질의는 Titan Embed v2 cross-lingual 유사도가
# 크게 떨어져(실측 top1 ~0.13) 정답 문서도 임계값 미달로 걸러진다.
# evaluation/test_queries.csv 의 question_en 10건으로 실측: 정상 7건 top score 0.437~0.825
# (전부 expected_source_url 1위 적중), 범위밖 3건 top score 0.069~0.222. 0.3은 그 사이 값.

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def _load_documents(raw_dir: Path = RAW_DIR) -> list[Document]:
    """data/raw/ 의 JSON 파일들을 읽어 title/url 메타데이터가 붙은 청크 Document 목록으로 만든다."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    documents: list[Document] = []
    for json_path in sorted(raw_dir.glob("*.json")):
        page = json.loads(json_path.read_text(encoding="utf-8"))
        for chunk in splitter.split_text(page["content"]):
            documents.append(
                Document(
                    page_content=chunk,
                    metadata={"title": page["title"], "url": page["url"], "id": page["id"]},
                )
            )
    return documents


def _embeddings() -> BedrockEmbeddings:
    """BedrockEmbeddings 클라이언트를 만든다."""
    return BedrockEmbeddings(model_id=EMBEDDING_MODEL_ID, region_name=REGION)


def build_index(raw_dir: Path = RAW_DIR, persist_dir: Path = PERSIST_DIR) -> None:
    """data/raw/ 의 JSON 문서를 청크로 나누고 BedrockEmbeddings로 임베딩해 chroma_db를 생성한다."""
    documents = _load_documents(raw_dir)
    if not documents:
        raise ValueError(f"{raw_dir} 에 크롤링된 문서가 없습니다. crawl_confluence.py 를 먼저 실행하세요.")
    Chroma.from_documents(
        documents=documents,
        embedding=_embeddings(),
        collection_name=COLLECTION_NAME,
        persist_directory=str(persist_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )


def _translate(text: str) -> str:
    """text가 한국어면 영어로, 영어면 한국어로 번역한 결과만 돌려준다.

    쓰로틀링이 나면 MODEL_CANDIDATES 순서대로 다음 모델로 재시도한다.
    """
    prompt = TRANSLATE_PROMPT.format(text=text)
    last_error: Exception | None = None
    for model_id in MODEL_CANDIDATES:
        try:
            llm = ChatBedrockConverse(model=model_id, region_name=REGION, temperature=0)
            return llm.invoke(prompt).content.strip()
        except ClientError as exc:
            last_error = exc
            print(f"[번역 모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    raise RuntimeError(f"모든 번역 후보 모델이 실패했습니다: {last_error}") from last_error


def _vector_search(query: str, k: int) -> list[dict]:
    """번역 없이, 주어진 질의어 그대로 chroma_db를 검색해 title/url/content/score 목록을 반환한다."""
    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=_embeddings(),
        persist_directory=str(PERSIST_DIR),
    )
    results = vectorstore.similarity_search_with_score(query, k=k)
    return [
        {
            "title": doc.metadata["title"],
            "url": doc.metadata["url"],
            "content": doc.page_content,
            "score": 1 - distance,  # cosine distance(0=동일) -> 유사도(1=동일)
        }
        for doc, distance in results
    ]


def rag_search(query: str, k: int = 5) -> list[dict]:
    """질의어와 그 번역본(한국어<->영어) 둘 다로 검색해, 최상위 유사도가 더 높은 쪽 결과를 반환한다.

    문서가 전부 영어라 한국어 질의는 검색이 잘 안 되고(교차언어 유사도 저하), 반대로 영어
    질의를 한국어로 번역해봤자 더 낮은 점수가 나온다. 그래서 호출자가 질문 언어를 알려줄
    필요 없이, 두 버전을 다 검색해 이긴 쪽을 채택하는 방식으로 자동 처리한다.
    """
    translated = _translate(query)
    original_hits = _vector_search(query, k)
    translated_hits = _vector_search(translated, k)
    original_top = original_hits[0]["score"] if original_hits else -1.0
    translated_top = translated_hits[0]["score"] if translated_hits else -1.0
    return original_hits if original_top >= translated_top else translated_hits


def is_confident(results: list[dict], threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """검색 결과의 최고 유사도 점수가 임계값 이상인지 판단한다. 미달이면 에이전트가 실시간 검색으로 폴백해야 함."""
    if not results:
        return False
    return results[0]["score"] >= threshold


if __name__ == "__main__":
    build_index()
    print(f"인덱스 빌드 완료: {PERSIST_DIR}")
