import asyncio
import pytest

import main as main_mod


@pytest.mark.asyncio
async def test_can_handle_executes_lines_and_branches():
    handler = main_mod.SiteHandler()
    handler.domains = (".example.com",)
    # hostname None path and False branch
    assert handler.can_handle("notaurl") is False
    # True branch
    assert handler.can_handle("https://sub.example.com/path") is True
    # Exercise helper directly
    assert main_mod.SiteHandler._hostname_from_url("https://sub.example.com/path") == "sub.example.com"


@pytest.mark.asyncio
async def test_sitehandler_handle_raises_not_implemented():
    handler = main_mod.SiteHandler()
    with pytest.raises(NotImplementedError):
        await handler.handle(None, "https://example.com")


@pytest.mark.asyncio
async def test_parse_title_from_url_both_paths():
    h = main_mod.WikipediaHandler()
    # wiki URL path
    assert h.parse_title_from_url("https://en.wikipedia.org/wiki/Alan_Turing") == "Alan Turing"
    # non-wiki path
    assert h.parse_title_from_url("python") == "Python"


@pytest.mark.asyncio
async def test__fetch_extract_builds_expected_api_url(monkeypatch):
    t = main_mod.Tools()
    h = main_mod.WikipediaHandler()

    captured = {}

    async def fake__scrape(self, url: str, return_raw: bool = True, emitter=None, redirect=True):
        captured["url"] = url
        return "ok"

    monkeypatch.setattr(main_mod.Tools, "_scrape", fake__scrape, raising=True)

    # Also test helper builder directly
    built = h.build_api_url("Python", "en")
    assert built.startswith("https://en.wikipedia.org/w/api.php?") and "titles=Python" in built

    await h._fetch_extract(t, "Python")
    assert captured["url"].startswith("https://en.wikipedia.org/w/api.php?")
    assert "titles=Python" in captured["url"]
    await t.close()


@pytest.mark.asyncio
async def test_fetch_pages_html_and_extract_paths(monkeypatch):
    t = main_mod.Tools()
    h = main_mod.WikipediaHandler()

    seen_urls = []

    async def fake__scrape(self, url: str, return_raw: bool = True, emitter=None, redirect=True):
        seen_urls.append(url)
        return "ok"

    monkeypatch.setattr(main_mod.Tools, "_scrape", fake__scrape, raising=True)

    # return_html=True -> fetch HTML for both a full url and a built title
    # Ensure builder used for the title case
    assert h.build_page_url("Ruby", "en").endswith("/wiki/Ruby")
    out_html = await h.fetch_pages(t, ["https://en.wikipedia.org/wiki/Python", "Ruby"], return_html=True)
    assert out_html == "okok" and any("/wiki/Python" in u for u in seen_urls) and any("/wiki/Ruby" in u for u in seen_urls)

    seen_urls.clear()
    # return_html=False -> use API extract path
    out_text = await h.fetch_pages(t, ["Python"], return_html=False)
    assert out_text == "ok" and any("/w/api.php" in u for u in seen_urls)
    await t.close()


def test_tools_class_body_and_version():
    # Accessing VERSION ensures class body executed
    assert isinstance(main_mod.Tools.VERSION, str) and main_mod.Tools.VERSION
    assert main_mod.Tools._coverage_touch_class() == main_mod.Tools.VERSION
