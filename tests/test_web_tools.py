from __future__ import annotations

import asyncio

import httpx

from integrations.web_tools import ConstrainedWebTools


def test_web_tools_search_fetch_and_summarize_use_cached_results():
    search_html = """
    <html><body>
      <a class="result__a" href="https://docs.python.org/3/library/asyncio.html">asyncio — docs</a>
      <div class="result__snippet">Python standard library documentation for asyncio.</div>
      <a class="result__a" href="https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html">Qt tray docs</a>
      <div class="result__snippet">PySide6 QSystemTrayIcon reference.</div>
    </body></html>
    """
    page_html = """
    <html>
      <head>
        <title>asyncio — Asynchronous I/O</title>
        <meta name="description" content="asyncio provides infrastructure for asynchronous I/O, networking, and subprocess support." />
      </head>
      <body>
        <main>
          <p>asyncio is a library to write concurrent code using the async and await syntax.</p>
          <p>It is often used for network services, subprocess orchestration, and structured asynchronous workflows.</p>
          <p>The high-level APIs cover running coroutines, tasks, and queues.</p>
        </main>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text=search_html, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(200, text=page_html, headers={"content-type": "text/html; charset=utf-8"})

    tools = ConstrainedWebTools(transport=httpx.MockTransport(handler))

    search_result = asyncio.run(tools.search("python asyncio"))
    assert search_result.success
    assert 'Search results for "python asyncio"' in search_result.message
    assert "Use /open-result <n>, /fetch <n>, or /summarize <n>." in search_result.message

    fetch_result = asyncio.run(tools.fetch("1"))
    assert fetch_result.success
    assert "Page: asyncio" in fetch_result.message
    assert "async and await syntax" in fetch_result.message

    summary_result = asyncio.run(tools.summarize("1"))
    assert summary_result.success
    assert "Summary: asyncio" in summary_result.message
    assert "Source: https://docs.python.org/3/library/asyncio.html" in summary_result.message
    assert tools.healthcheck()["state"] == "ok"


def test_web_tools_fail_cleanly_when_network_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    tools = ConstrainedWebTools(transport=httpx.MockTransport(handler))

    result = asyncio.run(tools.search("offline test"))
    assert not result.success
    assert result.state == "error"
    assert "Internet search failed" in result.message
    assert tools.healthcheck()["state"] == "error"
