"""Confluence REST API를 감싸는 MCP 서버. 특정 페이지 조회와 CQL 실시간 검색 도구를 제공한다.

CONFLUENCE_BASE_URL / CONFLUENCE_AUTH_TOKEN 을 .env 로 바꾸면 다른 컨플루언스 인스턴스로 교체 가능하다.
search_confluence 는 1.5일 개발의 후순위(스트레치) 항목이며, 시간이 부족하면 가장 먼저 제외한다.
"""

import os
import re
from urllib.parse import unquote_plus

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from markdownify import markdownify

load_dotenv()

CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "https://cwiki.apache.org/confluence")
CONFLUENCE_AUTH_TOKEN = os.environ.get("CONFLUENCE_AUTH_TOKEN")  # ASF 공개 스페이스는 비워둬도 됨

DISPLAY_URL_PATTERN = re.compile(r"/display/([^/]+)/([^/]+)/?$")

mcp = FastMCP("confluence-tools")


def _headers() -> dict[str, str]:
    """인증 토큰이 있으면 Authorization 헤더를 만들고, 없으면 빈 헤더를 반환한다."""
    return {"Authorization": f"Bearer {CONFLUENCE_AUTH_TOKEN}"} if CONFLUENCE_AUTH_TOKEN else {}


def _page_to_dict(page: dict, url: str) -> dict:
    """Confluence API 응답(단일 페이지)을 title/url/content 형태로 변환한다."""
    html = page["body"]["storage"]["value"]
    return {
        "title": page["title"],
        "url": url,
        "content": markdownify(html, heading_style="ATX").strip(),
    }


@mcp.tool()
def get_page(url_or_id: str) -> dict:
    """페이지 URL 또는 ID로 컨플루언스 원문을 실시간 조회해 title/url/content 를 반환한다."""
    if url_or_id.isdigit():
        response = requests.get(
            f"{CONFLUENCE_BASE_URL}/rest/api/content/{url_or_id}",
            params={"expand": "body.storage"},
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()
        page = response.json()
        return _page_to_dict(page, f"{CONFLUENCE_BASE_URL}{page['_links']['webui']}")

    match = DISPLAY_URL_PATTERN.search(url_or_id)
    if not match:
        raise ValueError(f"지원하지 않는 URL/ID 형식입니다: {url_or_id}")
    space_key, title = match.groups()
    title = unquote_plus(title)
    response = requests.get(
        f"{CONFLUENCE_BASE_URL}/rest/api/content",
        params={"spaceKey": space_key, "title": title, "expand": "body.storage"},
        headers=_headers(),
        timeout=15,
    )
    response.raise_for_status()
    results = response.json()["results"]
    if not results:
        raise ValueError(f"페이지를 찾을 수 없습니다: {url_or_id}")
    return _page_to_dict(results[0], url_or_id)


@mcp.tool()
def search_confluence(cql: str) -> list[dict]:
    """CQL 질의로 컨플루언스를 실시간 검색해 후보 페이지 목록(id, title, url)을 반환한다.

    반환된 id는 get_page(id) 로 바로 전달해 전체 본문을 조회할 수 있다.
    RAG 검색(rag_search)이 부족할 때의 폴백으로만 사용한다.
    """
    response = requests.get(
        f"{CONFLUENCE_BASE_URL}/rest/api/content/search",
        params={"cql": cql, "limit": 5},
        headers=_headers(),
        timeout=15,
    )
    response.raise_for_status()
    results = response.json()["results"]
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "url": f"{CONFLUENCE_BASE_URL}{item['_links']['webui']}",
        }
        for item in results
    ]


if __name__ == "__main__":
    mcp.run()
