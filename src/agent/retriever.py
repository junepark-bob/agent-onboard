"""data/raw/ 의 문서를 chroma_db로 임베딩하고 의미 검색을 제공하는 RAG 파이프라인."""

import json
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_aws import BedrockEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .llm_factory import MODEL_PROVIDER
from .models import GOOGLE_EMBEDDING_MODEL_ID
from .translator import is_korean, translate

load_dotenv()

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
REGION = "us-east-1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/agent -> src -> mini-pjt 루트
RAW_DIR = PROJECT_ROOT / "data" / "raw"
# 제공자(MODEL_PROVIDER)마다 임베딩 모델이 달라서 벡터 공간이 서로 호환되지 않는다 - 인덱스를
# 공유하면 다른 임베딩 공간에서 검색하게 돼 결과가 무의미해진다. 그래서 제공자별로 디렉터리를
# 분리해, 전환할 때 기존 인덱스를 실수로 덮어쓰거나 잘못된 임베딩으로 검색하는 사고를 막는다.
# google로 전환한 뒤에는 `python -m src.agent.retriever`로 chroma_db_google을 새로 만들어야 한다.
PERSIST_DIR = PROJECT_ROOT / ("chroma_db" if MODEL_PROVIDER == "bedrock" else f"chroma_db_{MODEL_PROVIDER}")
COLLECTION_NAME = "confluence_onboarding"
SIMILARITY_THRESHOLD = 0.3
# 대상 문서(HADOOP2)가 전부 영어라서, 검색어는 반드시 영어여야 한다. 한국어 질의는 Titan
# Embed v2 cross-lingual 유사도가 크게 떨어져(실측 top1 ~0.13) 정답 문서도 임계값 미달로
# 걸러진다. rag_search()가 한국어 질의를 영어로 번역해 이 조건을 항상 보장한다.
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


def _embeddings() -> Any:
    """현재 제공자(MODEL_PROVIDER)에 맞는 임베딩 클라이언트를 만든다."""
    if MODEL_PROVIDER == "google":
        import os

        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model=GOOGLE_EMBEDDING_MODEL_ID, google_api_key=os.environ["GOOGLE_API_KEY"])
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


_vectorstore_cache: Chroma | None = None
_vectorstore_lock = threading.Lock()


def _get_vectorstore() -> Chroma:
    """chroma_db 벡터스토어 클라이언트를 프로세스당 한 번만 만들어 재사용한다.

    매 호출마다 새 Chroma(PersistentClient) 인스턴스를 만들고 버리면, chromadb의
    SharedSystemClient 클래스 전역 캐시가 생성/해제를 빠르게 반복하면서 간헐적으로
    KeyError/AttributeError가 나는 걸 실측으로 확인했다(`data/documents/ISSUES.md`).
    `rag_search`는 LangChain이 스레드풀에서 동기 실행하므로, 락으로 동시 생성을 막는다.
    """
    global _vectorstore_cache
    if _vectorstore_cache is None:
        with _vectorstore_lock:
            if _vectorstore_cache is None:
                _vectorstore_cache = Chroma(
                    collection_name=COLLECTION_NAME,
                    embedding_function=_embeddings(),
                    persist_directory=str(PERSIST_DIR),
                )
    return _vectorstore_cache


def _vector_search(query: str, k: int) -> list[dict]:
    """번역 없이, 주어진 질의어 그대로 chroma_db를 검색해 title/url/content/score 목록을 반환한다."""
    vectorstore = _get_vectorstore()
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
    """질의어로 chroma_db를 검색한다. 대상 문서가 전부 영어이므로 검색은 항상 영어로만 한다.

    질의어가 한국어면 영어로 번역한 뒤 그 번역본으로 검색하고, 이미 영어면 번역 없이 그대로
    검색한다. 호출자는 질문 언어를 몰라도 된다. 예전에는 원문/번역본을 둘 다 검색해 더 높은
    점수를 채택했지만, 문서가 전부 영어인 이 도메인에서는 그 이중 검색이 불필요한 비용이었다
    (한국어 원문 검색은 교차언어 유사도 저하로 항상 지고, 영어 질의의 한국어 번역본 검색도
    이길 일이 없다) — `architectures/0009-english-only-domain-language-policy.md` 참고.
    """
    search_query = translate(query) if is_korean(query) else query
    return _vector_search(search_query, k)


def is_confident(results: list[dict], threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """검색 결과의 최고 유사도 점수가 임계값 이상인지 판단한다. 미달이면 에이전트가 실시간 검색으로 폴백해야 함."""
    if not results:
        return False
    return results[0]["score"] >= threshold


if __name__ == "__main__":
    build_index()
    print(f"인덱스 빌드 완료: {PERSIST_DIR}")
