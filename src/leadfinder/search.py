from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import time
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from leadfinder.models import SearchHit

DEFAULT_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SearchProvider:
    name: str

    def search(self, session: requests.Session, query: str, limit: int) -> list[SearchHit]:
        raise NotImplementedError


class DuckDuckGoProvider(SearchProvider):
    def __init__(self) -> None:
        super().__init__(name="duckduckgo")

    def search(self, session: requests.Session, query: str, limit: int) -> list[SearchHit]:
        response = session.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []
        for rank, result in enumerate(soup.select(".result"), start=1):
            if len(hits) >= limit:
                break
            link = result.select_one(".result__title a")
            if link is None:
                continue
            title = clean_text(link.get_text(" ", strip=True))
            snippet_node = result.select_one(".result__snippet")
            snippet = clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            url = normalize_result_url(link.get("href", ""))
            if not title or not url:
                continue
            hits.append(
                SearchHit(
                    provider=self.name,
                    query=query,
                    rank=rank,
                    title=title,
                    snippet=snippet,
                    url=url,
                )
            )
        return hits


class BraveProvider(SearchProvider):
    def __init__(self) -> None:
        super().__init__(name="brave")

    def search(self, session: requests.Session, query: str, limit: int) -> list[SearchHit]:
        response = None
        for attempt in range(2):
            response = session.get(
                "https://search.brave.com/search",
                params={"q": query, "source": "web"},
                timeout=DEFAULT_TIMEOUT,
            )
            if response.status_code != 429:
                break
            time.sleep(6 * (attempt + 1))
        if response is None:
            return []
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        hits: list[SearchHit] = []
        ignored_hosts = {
            "search.brave.com",
            "account.brave.com",
            "brave.com",
            "status.brave.app",
            "imgs.search.brave.com",
            "cdn.search.brave.com",
        }
        ignored_text = {
            "Ask",
            "All",
            "Images",
            "News",
            "Videos",
            "Goggles",
            "Brave Search Premium",
            "Transparency Report",
            "Report a security issue",
            "Status",
            "Brave Browser",
            "Brave Search",
            "Brave Wallet",
            "Google",
            "Bing",
        }
        seen_urls: set[str] = set()
        rank = 0
        for link in soup.select("a[href^='http']"):
            if len(hits) >= limit:
                break
            url = normalize_result_url(link.get("href", ""))
            parsed = urlparse(url)
            title = clean_text(link.get_text(" ", strip=True))
            if (
                not url
                or parsed.netloc in ignored_hosts
                or not title
                or title in ignored_text
                or len(title) < 8
                or url in seen_urls
            ):
                continue
            rank += 1
            seen_urls.add(url)
            container = link.find_parent(["div", "article", "section"]) or link
            snippet = clean_text(container.get_text(" ", strip=True))
            if snippet.startswith(title):
                snippet = snippet[len(title) :].strip()
            hits.append(
                SearchHit(
                    provider=self.name,
                    query=query,
                    rank=rank,
                    title=title,
                    snippet=snippet,
                    url=url,
                )
            )
        return hits


def clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def normalize_result_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"
    parsed = urlparse(raw_url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        encoded = parse_qs(parsed.query).get("uddg", [""])[0]
        if encoded:
            return encoded
    return raw_url


def search_web(query: str, limit_per_provider: int = 5) -> list[SearchHit]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    providers: list[SearchProvider] = [BraveProvider(), DuckDuckGoProvider()]
    unique_urls: set[str] = set()
    hits: list[SearchHit] = []
    for provider in providers:
        try:
            provider_hits = provider.search(session, query, limit_per_provider)
        except requests.RequestException:
            continue
        for hit in provider_hits:
            if hit.url in unique_urls:
                continue
            unique_urls.add(hit.url)
            hits.append(hit)
    return hits


# ---------------------------------------------------------------------------
# Query templates – focused on Stockholm tech companies
# ---------------------------------------------------------------------------

def linkedin_company_query(company_name: str) -> str:
    return f'"{company_name}" site:linkedin.com/company'


def allabolag_query(company_name: str) -> str:
    return f'"{company_name}" site:allabolag.se omsättning'


def recruitment_query(company_name: str) -> str:
    return (
        f'"{company_name}" '
        "(rekryterar OR hiring OR jobb OR careers OR talent acquisition OR growth)"
    )


def contact_query(company_name: str) -> str:
    """Search for key contacts (VD, HR-chef, CTO) at the company."""
    return (
        f'"{company_name}" Stockholm '
        "(VD OR CEO OR HR OR \"HR-chef\" OR CTO OR \"Head of People\" OR \"talent\") "
        "site:linkedin.com/in"
    )


def news_query(company_name: str) -> str:
    """Search for recent news about the company."""
    return f'"{company_name}" Stockholm (nyheter OR tillväxt OR investering OR expansion OR förvärv)'


def discovery_queries() -> list[str]:
    """Queries focused on Stockholm tech/IT companies matching target size."""
    return [
        # LinkedIn-focused discovery
        'Stockholm IT company LinkedIn 51-200 employees hiring',
        'Stockholm tech company LinkedIn 201-500 employees',
        'Stockholm SaaS company LinkedIn 501-1000 employees',
        'Stockholm technology company LinkedIn hiring 2024 2025',
        # Swedish tech hubs
        'Stockholm Kista tech company hiring rekryterar',
        'Stockholm fintech company growth LinkedIn',
        'Stockholm healthtech medtech company LinkedIn employees',
        # Growth signals
        'Stockholm tech startup scaleup hiring "series B" OR "series C"',
        'Stockholm IT konsult bolag tillväxt rekryterar',
        'Stockholm tech company "vi växer" OR "vi rekryterar" OR "join us"',
        # Allabolag for revenue/size data
        'Stockholm IT tech omsättning 100 mkr site:allabolag.se',
        'Stockholm tech bolag anställda 100-500 site:allabolag.se',
    ]


def enrichment_queries(company_name: str) -> list[str]:
    return [
        linkedin_company_query(company_name),
        allabolag_query(company_name),
        recruitment_query(company_name),
        contact_query(company_name),
        news_query(company_name),
    ]
