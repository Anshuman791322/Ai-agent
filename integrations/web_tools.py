from __future__ import annotations

import ipaddress
import re
import threading
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx


_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_USER_AGENT = "JARVIS-Local/0.1 (+https://duckduckgo.com/)"
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CONTENT_TAGS = {"p", "li", "h1", "h2", "h3", "blockquote", "pre", "code"}
_IGNORED_TAGS = {"script", "style", "noscript", "svg", "canvas", "form", "footer", "nav"}
_BOILERPLATE_TOKENS = {"nav", "menu", "footer", "sidebar", "cookie", "consent", "share", "social", "ad"}
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]{2,}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _truncate(value: str, limit: int) -> str:
    cleaned = value.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _host_from_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _public_http_url(raw_target: str) -> str | None:
    candidate = raw_target.strip().strip('"').strip("'")
    if not candidate:
        return None
    if candidate.startswith("www."):
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS or host.endswith(".local") or "." not in host:
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return candidate
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return None
    return candidate


def _resolve_duckduckgo_href(href: str) -> str:
    if href.startswith("//"):
        href = f"https:{href}"
    elif href.startswith("/"):
        href = urljoin("https://duckduckgo.com", href)
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        redirect_target = parse_qs(parsed.query).get("uddg")
        if redirect_target:
            return redirect_target[0]
    return href


def _sentence_key(value: str) -> set[str]:
    return {word.lower() for word in _WORD_RE.findall(value) if len(word) >= 4}


def _sentences_overlap(left: str, right: str) -> bool:
    left_words = _sentence_key(left)
    right_words = _sentence_key(right)
    if not left_words or not right_words:
        return False
    overlap = len(left_words & right_words)
    return overlap >= max(4, min(len(left_words), len(right_words)) // 2)


class _DuckDuckGoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current_result: dict[str, str] | None = None
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        classes = set(attr_map.get("class", "").split())
        if tag == "a" and "result__a" in classes and attr_map.get("href"):
            url = _public_http_url(_resolve_duckduckgo_href(attr_map["href"]))
            if url is None:
                self._current_result = None
                self._capture_title = False
                return
            self._current_result = {"url": url, "title": "", "snippet": ""}
            self._title_parts = []
            self._capture_title = True
            return
        if self._current_result is not None and not self._capture_title and "result__snippet" in classes:
            self._snippet_parts = []
            self._capture_snippet = True
            self._snippet_tag = tag

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        elif self._capture_snippet:
            self._snippet_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_title and tag == "a":
            self._capture_title = False
            if self._current_result is None:
                return
            title = _clean_text("".join(self._title_parts))
            if title:
                self._current_result["title"] = title
                self.results.append(self._current_result)
            self._current_result = None
            self._title_parts = []
            return
        if self._capture_snippet and tag == self._snippet_tag:
            self._capture_snippet = False
            self._snippet_tag = None
            snippet = _clean_text("".join(self._snippet_parts))
            if snippet and self.results:
                self.results[-1]["snippet"] = snippet
            self._snippet_parts = []


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._title_parts: list[str] = []
        self._current_parts: list[str] = []
        self._chunks: list[str] = []
        self._ignored_tags: list[str] = []
        self._capture_text = False
        self._capture_tag: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        classes = " ".join(part for part in (attr_map.get("class", ""), attr_map.get("id", "")) if part).lower()
        if tag in _IGNORED_TAGS or any(token in classes for token in _BOILERPLATE_TOKENS):
            self._ignored_tags.append(tag)
        if tag == "title":
            self._in_title = True
        if tag == "meta" and not self.description:
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.description = _clean_text(attr_map.get("content", ""))
        if not self._ignored_tags and tag in _CONTENT_TAGS:
            self._capture_text = True
            self._capture_tag = tag
            self._current_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._capture_text and not self._ignored_tags:
            self._current_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            self.title = _clean_text("".join(self._title_parts))
            self._title_parts = []
            return
        if self._capture_text and tag == self._capture_tag:
            self._capture_text = False
            self._capture_tag = None
            chunk = _clean_text("".join(self._current_parts))
            self._current_parts = []
            if chunk:
                self._chunks.append(chunk)
        if self._ignored_tags and tag == self._ignored_tags[-1]:
            self._ignored_tags.pop()

    @property
    def body_text(self) -> str:
        chunks: list[str] = []
        for chunk in self._chunks:
            if len(chunk) >= 24 or not chunks:
                chunks.append(chunk)
            if len(chunks) >= 48:
                break
        return "\n".join(chunks)


@dataclass(slots=True)
class WebSearchResult:
    index: int
    title: str
    url: str
    snippet: str
    host: str


@dataclass(slots=True)
class WebPage:
    url: str
    final_url: str
    host: str
    title: str
    description: str
    text: str
    excerpt: str


@dataclass(slots=True)
class WebToolResult:
    success: bool
    message: str
    state: str
    detail: str
    payload: dict[str, Any] = field(default_factory=dict)


class ConstrainedWebTools:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._lock = threading.RLock()
        self._last_results: list[WebSearchResult] = []
        self._last_query = ""
        self._status_state = "ok"
        self._status_detail = "internet tools ready; use /search to check connectivity"

    def healthcheck(self) -> dict[str, str]:
        with self._lock:
            return {"state": self._status_state, "detail": self._status_detail}

    def resolve_result(self, token: str) -> WebSearchResult | None:
        try:
            index = int(token)
        except (TypeError, ValueError):
            return None
        with self._lock:
            if 1 <= index <= len(self._last_results):
                return self._last_results[index - 1]
        return None

    async def search(self, query: str, *, limit: int = 5) -> WebToolResult:
        cleaned_query = " ".join(query.split())
        if not cleaned_query:
            return WebToolResult(False, "Usage: /search <query>", "warn", "empty search query")

        try:
            response = await self._request("GET", _SEARCH_ENDPOINT, params={"q": cleaned_query})
        except httpx.HTTPError as exc:
            detail = f"internet offline: {self._network_error_detail(exc)}"
            self._set_status("error", detail)
            return WebToolResult(False, f"Internet search failed: {detail}.", "error", detail)

        parser = _DuckDuckGoHtmlParser()
        parser.feed(response.text)

        results: list[WebSearchResult] = []
        for index, item in enumerate(parser.results[: max(1, min(limit, 8))], start=1):
            results.append(
                WebSearchResult(
                    index=index,
                    title=item["title"],
                    url=item["url"],
                    snippet=item.get("snippet", ""),
                    host=_host_from_url(item["url"]),
                )
            )

        with self._lock:
            self._last_query = cleaned_query
            self._last_results = results

        if not results:
            detail = f'no search results for "{cleaned_query}"'
            self._set_status("warn", detail)
            return WebToolResult(False, f'No search results for "{cleaned_query}".', "warn", detail)

        detail = f'last search "{cleaned_query}" returned {len(results)} result(s)'
        self._set_status("ok", detail)
        lines = [f'Search results for "{cleaned_query}":']
        for result in results:
            lines.append(f"{result.index}. {result.title} ({result.host})")
            if result.snippet:
                lines.append(f"   {result.snippet}")
        lines.append("Use /open-result <n>, /fetch <n>, or /summarize <n>.")
        return WebToolResult(True, "\n".join(lines), "ok", detail, payload={"results": results, "query": cleaned_query})

    async def fetch(self, target: str) -> WebToolResult:
        page_or_error = await self._fetch_page(target)
        if isinstance(page_or_error, WebToolResult):
            return page_or_error

        page = page_or_error
        detail = f"last page {page.host} | {page.title or page.final_url}"
        self._set_status("ok", detail)
        title = page.title or page.final_url
        message = f"Page: {title} ({page.host})\n{_truncate(page.text or page.description or page.excerpt, 1600)}"
        return WebToolResult(True, message, "ok", detail, payload={"page": page})

    async def summarize(self, target: str) -> WebToolResult:
        page_or_error = await self._fetch_page(target)
        if isinstance(page_or_error, WebToolResult):
            return page_or_error

        page = page_or_error
        bullets = self._summarize_page(page)
        detail = f"last summary {page.host} | {page.title or page.final_url}"
        self._set_status("ok", detail)
        lines = [f"Summary: {page.title or page.final_url} ({page.host})"]
        lines.extend(f"- {bullet}" for bullet in bullets)
        lines.append(f"Source: {page.final_url}")
        return WebToolResult(True, "\n".join(lines), "ok", detail, payload={"page": page, "bullets": bullets})

    async def _fetch_page(self, target: str) -> WebPage | WebToolResult:
        resolved = self._resolve_target(target)
        if resolved is None:
            return WebToolResult(
                False,
                "Usage: /fetch <url-or-result-number> or /summarize <url-or-result-number>",
                "warn",
                "missing fetch target",
            )

        try:
            response = await self._request("GET", resolved)
        except httpx.HTTPError as exc:
            detail = f"internet offline: {self._network_error_detail(exc)}"
            self._set_status("error", detail)
            return WebToolResult(False, f"Page fetch failed: {detail}.", "error", detail)

        content_type = response.headers.get("content-type", "").lower()
        final_url = str(response.url)
        if "text/plain" in content_type:
            text = _clean_text(response.text)
            excerpt = _truncate(text, 320)
            page = WebPage(
                url=resolved,
                final_url=final_url,
                host=_host_from_url(final_url),
                title=final_url,
                description="",
                text=text,
                excerpt=excerpt,
            )
            return page

        if "html" not in content_type and "xml" not in content_type:
            detail = f"unsupported content type {content_type or 'unknown'}"
            self._set_status("warn", detail)
            return WebToolResult(False, f"Readable fetch only supports text and HTML pages. Got {content_type or 'unknown'}.", "warn", detail)

        parser = _ReadableHtmlParser()
        parser.feed(response.text)
        text = parser.body_text
        if not text and not parser.description and not parser.title:
            detail = f"page at {final_url} did not expose readable text"
            self._set_status("warn", detail)
            return WebToolResult(False, "The page loaded, but it did not expose readable text.", "warn", detail)

        excerpt_source = parser.description or text
        page = WebPage(
            url=resolved,
            final_url=final_url,
            host=_host_from_url(final_url),
            title=parser.title or final_url,
            description=parser.description,
            text=text,
            excerpt=_truncate(excerpt_source, 320),
        )
        return page

    def _resolve_target(self, target: str) -> str | None:
        cleaned = target.strip()
        if not cleaned:
            return None
        cached_result = self.resolve_result(cleaned)
        if cached_result is not None:
            return cached_result.url
        return _public_http_url(cleaned)

    async def _request(self, method: str, url: str, *, params: dict[str, str] | None = None) -> httpx.Response:
        timeout = httpx.Timeout(8.0, connect=4.0)
        headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.8"}
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            transport=self._transport,
        ) as client:
            response = await client.request(method, url, params=params)
            response.raise_for_status()
            return response

    def _set_status(self, state: str, detail: str) -> None:
        with self._lock:
            self._status_state = state
            self._status_detail = detail

    @staticmethod
    def _network_error_detail(exc: httpx.HTTPError) -> str:
        if isinstance(exc, httpx.TimeoutException):
            return "request timed out"
        return str(exc).strip() or exc.__class__.__name__

    def _summarize_page(self, page: WebPage) -> list[str]:
        candidates: list[str] = []
        if page.description:
            candidates.append(page.description)
        candidates.extend(
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_RE.split(page.text)
            if len(sentence.strip()) >= 40
        )

        keywords = _sentence_key(page.title)
        scored: list[tuple[float, int, str]] = []
        seen: list[str] = []
        for index, sentence in enumerate(candidates[:24]):
            cleaned = _clean_text(sentence)
            if not cleaned or any(_sentences_overlap(cleaned, prior) for prior in seen):
                continue
            seen.append(cleaned)
            score = 4.0 if index == 0 else 0.0
            score += max(0.0, 2.0 - (index * 0.08))
            sentence_words = _sentence_key(cleaned)
            score += sum(1.0 for word in keywords if word in sentence_words)
            if any(ch.isdigit() for ch in cleaned):
                score += 0.5
            scored.append((score, index, cleaned))

        selected: list[str] = []
        for _, _, sentence in sorted(scored, key=lambda item: (-item[0], item[1])):
            if any(_sentences_overlap(sentence, prior) for prior in selected):
                continue
            selected.append(_truncate(sentence, 220))
            if len(selected) == 3:
                break

        if selected:
            return selected
        fallback = page.excerpt or page.title or page.final_url
        return [_truncate(fallback, 220)]
