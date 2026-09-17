"""data/urls.txt 에 적힌 컨플루언스 페이지를 REST API로 수집해 data/raw/ 에 저장하는 준비 스크립트.

페이지에 첨부 이미지가 있으면 다운로드 -> 축소 -> 비전 모델 1회 호출로 텍스트 설명을 만들어
본문에 끼워 넣는다. 토큰 비용을 낮추기 위해 (1) 이미지를 작게 리사이즈해서 보내고,
(2) 분류와 설명을 한 번의 호출로 같이 받고, (3) 저비용 모델(Haiku)을 우선 사용한다.
"""

import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote_plus

import requests
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from markdownify import markdownify
from PIL import Image

from ..agent import REGION

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/crawler -> src -> mini-pjt 루트

CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://cwiki.apache.org/confluence")
CONFLUENCE_AUTH_TOKEN = os.environ.get("CONFLUENCE_AUTH_TOKEN")  # ASF 공개 스페이스는 비워둬도 됨
URL_LIST_PATH = PROJECT_ROOT / "data" / "urls.txt"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

DISPLAY_URL_PATTERN = re.compile(r"/display/([^/]+)/([^/]+)/?$")
IMAGE_TAG_PATTERN = re.compile(r'<ac:image[^>]*>\s*<ri:attachment ri:filename="([^"]+)"\s*/>\s*</ac:image>')

# 비전 모델은 저비용 모델(Haiku)을 우선 쓴다. 실패하면 다음 후보로 넘어간다.
VISION_MODEL_CANDIDATES = [
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
]
MAX_IMAGE_DIMENSION = 768  # 긴 변 기준 픽셀 수. 작을수록 비전 모델 입력 토큰이 준다.
IMAGE_PROMPT = (
    "Look at this image and reply with exactly one of the following, and nothing else:\n"
    "- If it is a photo or illustration: a one or two sentence description in Korean.\n"
    "- If it is a diagram, flowchart, or architecture drawing: a Mermaid code block "
    "capturing its structure.\n"
    "- If it is a screenshot of text/a table/a document: transcribe the visible text as-is."
)


def load_url_list(path: Path = URL_LIST_PATH) -> list[str]:
    """URL 리스트 파일을 읽어 빈 줄과 주석(#)을 제외한 URL 목록을 반환한다."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def parse_space_and_title(url: str) -> tuple[str, str]:
    """컨플루언스 display URL에서 스페이스 키와 페이지 타이틀을 분리한다."""
    match = DISPLAY_URL_PATTERN.search(url)
    if not match:
        raise ValueError(f"컨플루언스 display URL 형식이 아닙니다: {url}")
    space_key, raw_title = match.groups()
    return space_key, unquote_plus(raw_title)


def fetch_page_by_title(space_key: str, title: str) -> dict:
    """Confluence REST API(/rest/api/content)로 제목 기준 페이지 본문(storage format)을 조회한다."""
    headers = {"Authorization": f"Bearer {CONFLUENCE_AUTH_TOKEN}"} if CONFLUENCE_AUTH_TOKEN else {}
    response = requests.get(
        f"{CONFLUENCE_BASE_URL}/rest/api/content",
        params={"spaceKey": space_key, "title": title, "expand": "body.storage"},
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    results = response.json()["results"]
    if not results:
        raise ValueError(f"페이지를 찾을 수 없습니다: {space_key}/{title}")
    return results[0]


def find_image_filenames(html: str) -> list[str]:
    """storage HTML에서 첨부 이미지(ac:image/ri:attachment) 파일명을 모두 찾는다."""
    return IMAGE_TAG_PATTERN.findall(html)


def get_attachment_download_url(page_id: str, filename: str) -> str | None:
    """페이지의 첨부파일 목록에서 filename과 일치하는 항목의 다운로드 URL을 찾는다."""
    headers = {"Authorization": f"Bearer {CONFLUENCE_AUTH_TOKEN}"} if CONFLUENCE_AUTH_TOKEN else {}
    response = requests.get(
        f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/attachment",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    for item in response.json()["results"]:
        if item["title"] == filename:
            return CONFLUENCE_BASE_URL + item["_links"]["download"]
    return None


def download_and_resize_image(url: str, max_dimension: int = MAX_IMAGE_DIMENSION) -> bytes:
    """이미지를 다운로드하고, 긴 변이 max_dimension을 넘으면 비율을 유지해 축소한 JPEG로 반환한다."""
    headers = {"Authorization": f"Bearer {CONFLUENCE_AUTH_TOKEN}"} if CONFLUENCE_AUTH_TOKEN else {}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    image = Image.open(BytesIO(response.content)).convert("RGB")
    if max(image.size) > max_dimension:
        image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def describe_image(image_bytes: bytes) -> str:
    """이미지 하나를 저비용 비전 모델에 한 번만 보내 분류와 설명(또는 Mermaid/OCR)을 함께 받는다.

    VISION_MODEL_CANDIDATES 순서대로 시도해 쓰로틀링 시 다음 모델로 재시도한다.
    """
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": IMAGE_PROMPT},
            {
                "type": "image",
                "source_type": "base64",
                "data": encoded,
                "mime_type": "image/jpeg",
            },
        ],
    }
    last_error: Exception | None = None
    for model_id in VISION_MODEL_CANDIDATES:
        try:
            llm = ChatBedrockConverse(model=model_id, region_name=REGION, temperature=0)
            return llm.invoke([message]).content.strip()
        except Exception as exc:  # noqa: BLE001 - 쓰로틀링/모델 미지원 등 이유와 무관하게 다음 후보로 넘어간다
            last_error = exc
            print(f"[이미지 설명 모델 폴백] {model_id} 실패({exc}), 다음 모델로 재시도합니다.")
    raise RuntimeError(f"모든 비전 모델 후보가 실패했습니다: {last_error}") from last_error


def embed_image_descriptions(html: str, page_id: str) -> str:
    """storage HTML 안의 첨부 이미지를 찾아 텍스트 설명으로 바꿔 넣은 HTML을 반환한다.

    이미지를 찾지 못하거나 설명 생성이 실패해도 크롤링 전체가 죽지 않도록, 실패한 이미지는
    실패 사유만 본문에 남기고 다음 이미지/페이지로 넘어간다.
    """

    def replace(match: re.Match) -> str:
        filename = match.group(1)
        download_url = get_attachment_download_url(page_id, filename)
        if download_url is None:
            return f"<p>[이미지 {filename}: 첨부파일을 찾을 수 없음]</p>"
        try:
            description = describe_image(download_and_resize_image(download_url))
        except Exception as exc:  # noqa: BLE001 - 이미지 하나 실패로 전체 크롤링을 멈추지 않는다
            description = f"(이미지 설명 생성 실패: {exc})"
        return f"<p><strong>[이미지: {filename}]</strong><br/>{description}</p>"

    return IMAGE_TAG_PATTERN.sub(replace, html)


def save_raw_page(page: dict, out_dir: Path = RAW_DIR) -> Path:
    """조회한 페이지를 JSON으로 data/raw/ 에 저장하고 저장 경로를 반환한다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = page["title"].replace("/", "_")
    path = out_dir / f"{safe_name}.json"
    path.write_text(json.dumps(page, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    """URL 리스트를 순회하며 전체 페이지를 수집해 data/raw/ 에 저장한다."""
    urls = load_url_list()
    for url in urls:
        space_key, title = parse_space_and_title(url)
        raw_page = fetch_page_by_title(space_key, title)
        html = raw_page["body"]["storage"]["value"]
        if find_image_filenames(html):
            html = embed_image_descriptions(html, raw_page["id"])
        page = {
            "id": raw_page["id"],
            "title": raw_page["title"],
            "url": url,
            "content": markdownify(html, heading_style="ATX").strip(),
        }
        saved_path = save_raw_page(page)
        print(f"저장 완료: {page['title']} -> {saved_path}")


if __name__ == "__main__":
    main()
