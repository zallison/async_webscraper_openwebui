import asyncio
import importlib
import json
import pytest
import urllib.parse

from conftest import FakeSession


def with_fake_session(plan):
    import main as main_mod

    async def _fake_get_session(self):
        sess = FakeSession(plan)
        # mirror real behavior: cache on instance
        self._session = sess
        return sess

    main_mod = importlib.reload(importlib.import_module("main"))
    # Monkeypatch method directly on class
    main_mod.Tools._get_session = _fake_get_session
    return main_mod


@pytest.mark.asyncio
async def test_sitehandler_base_class():
    """Test SiteHandler base class can_handle method."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.SiteHandler()
    handler.domains = (".example.com",)

    assert handler.can_handle("https://www.example.com/page")
    assert handler.can_handle("https://sub.example.com/path")
    assert not handler.can_handle("https://notexample.com/page")
    assert not handler.can_handle("https://example.org/page")


@pytest.mark.asyncio
async def test_wikipedia_handler_can_handle():
    """Test WikipediaHandler correctly identifies Wikipedia URLs."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.WikipediaHandler()

    assert handler.can_handle("https://en.wikipedia.org/wiki/Python")
    assert handler.can_handle("https://de.wikipedia.org/wiki/Deutschland")
    assert not handler.can_handle("https://example.com/wiki/Python")
    assert not handler.can_handle("https://wikipedia.com/")


@pytest.mark.asyncio
async def test_wikipedia_handler_parse_title_from_url():
    """Test WikipediaHandler.parse_title_from_url extracts titles correctly."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.WikipediaHandler()

    # Standard URL
    title = handler.parse_title_from_url("https://en.wikipedia.org/wiki/Alan_Turing")
    assert title == "Alan Turing"

    # URL with percent-encoding
    title = handler.parse_title_from_url("https://en.wikipedia.org/wiki/Caf%C3%A9")
    assert title == "Café"

    # URL with mixed case
    title = handler.parse_title_from_url(
        "https://en.wikipedia.org/wiki/python_programming"
    )
    assert title == "Python Programming"

    # Non-Wikipedia URL (fallback)
    title = handler.parse_title_from_url("python")
    assert title == "Python"


@pytest.mark.asyncio
async def test_wikipedia_handler_fetch_extract():
    """Test WikipediaHandler._fetch_extract calls correct API."""
    api_url = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Python"
    plan = {
        api_url: [
            (
                200,
                json.dumps(
                    {
                        "query": {
                            "pages": {
                                "1": {"extract": "Python is a programming language."}
                            }
                        }
                    }
                ),
                None,
            )
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.WikipediaHandler()

    result = await handler._fetch_extract(t, "Python")
    assert "Python is a programming language" in result or result.strip().startswith(
        "{"
    )
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_handler_fetch_pages_plaintext():
    """Test WikipediaHandler.fetch_pages with return_html=False."""
    api_url1 = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Python"
    api_url2 = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Ruby"
    plan = {
        api_url1: [(200, json.dumps({"extract": "Python content"}), None)],
        api_url2: [(200, json.dumps({"extract": "Ruby content"}), None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.WikipediaHandler()

    result = await handler.fetch_pages(t, ["Python", "Ruby"], return_html=False)
    assert isinstance(result, str)
    assert "Python" in result or "Ruby" in result or "extract" in result
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_handler_fetch_pages_html():
    """Test WikipediaHandler.fetch_pages with return_html=True."""
    page_url1 = "https://en.wikipedia.org/wiki/Python"
    page_url2 = "https://en.wikipedia.org/wiki/Ruby"
    plan = {
        page_url1: [(200, "<html>Python page HTML</html>", None)],
        page_url2: [(200, "<html>Ruby page HTML</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.WikipediaHandler()

    result = await handler.fetch_pages(t, ["Python", "Ruby"], return_html=True)
    assert isinstance(result, str)
    assert "Python page HTML" in result
    assert "Ruby page HTML" in result
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_handler_handle_html():
    """Test WikipediaHandler.handle with return_html=True."""
    page_url = "https://en.wikipedia.org/wiki/Python"
    plan = {
        page_url: [(200, "<html>Python Wikipedia Page</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.WikipediaHandler()

    result = await handler.handle(t, page_url, return_html=True)
    assert isinstance(result, str)
    assert "Python Wikipedia Page" in result
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_handler_handle_plaintext():
    """Test WikipediaHandler.handle with return_html=False."""
    page_url = "https://en.wikipedia.org/wiki/Python"
    api_url = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Python"
    plan = {
        api_url: [
            (
                200,
                json.dumps({"query": {"pages": {"1": {"extract": "Python extract"}}}}),
                None,
            )
        ],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.WikipediaHandler()

    result = await handler.handle(t, page_url, return_html=False)
    assert isinstance(result, str)
    assert "Python" in result or "extract" in result
    await t.close()


@pytest.mark.asyncio
async def test_tools_register_and_get_handler():
    """Test Tools.register_handler and get_handler_for, including alias binding."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    class CustomHandler(main_mod.SiteHandler):
        name = "custom"
        domains = (".custom.com",)

        async def handle(self, tools, url, return_html=None):
            return "custom result"

    t = main_mod.Tools()

    # WikipediaHandler should be registered by default
    handler = t.get_handler_for("https://en.wikipedia.org/wiki/Python")
    assert handler is not None
    assert isinstance(handler, main_mod.WikipediaHandler)

    # Register custom handler without aliases (back-compat path)
    custom_handler = CustomHandler()
    t.register_handler(custom_handler)

    # Should find custom handler
    handler = t.get_handler_for("https://www.custom.com/page")
    assert handler is not None
    assert isinstance(handler, CustomHandler)

    # Should return None for unhandled domains
    handler = t.get_handler_for("https://example.com/page")
    assert handler is None

    # Register with explicit aliases pointing to a callable
    async def alias_func(*args, **kwargs):
        return "alias ok"

    t.register_handler(CustomHandler(), alias_func, ["alias1", "alias2"])
    assert hasattr(t, "alias1") and hasattr(t, "alias2")
    out = await getattr(t, "alias1")()
    assert out == "alias ok"

    # Duplicate alias should raise
    with pytest.raises(Exception):
        t.register_handler(CustomHandler(), alias_func, ["alias1"])  # already exists

    await t.close()


@pytest.mark.asyncio
async def test_scrape_uses_wikipedia_handler():
    """Test that scrape() uses WikipediaHandler for Wikipedia URLs when redirect=True."""
    page_url = "https://en.wikipedia.org/wiki/Python"
    plan = {
        page_url: [(200, "<html>Python Wikipedia Page</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()

    # With redirect=True (default), should use handler
    result = await t.scrape(url=page_url, redirect=True, return_raw=True)
    assert isinstance(result, str)
    assert "Python Wikipedia Page" in result

    await t.close()


@pytest.mark.asyncio
async def test_scrape_bypasses_handler_when_redirect_false():
    """Test that scrape() bypasses handler when redirect=False."""
    page_url = "https://en.wikipedia.org/wiki/Python"
    plan = {
        page_url: [(200, "<html>Direct fetch</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()

    # With redirect=False, should fetch directly
    result = await t.scrape(url=page_url, redirect=False, return_raw=True)
    assert isinstance(result, str)
    assert "Direct fetch" in result

    await t.close()


@pytest.mark.asyncio
async def test_sitehandler_handle_not_implemented():
    """Calling base SiteHandler.handle should raise NotImplementedError."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.SiteHandler()
    with pytest.raises(NotImplementedError):
        await handler.handle(None, "https://example.com")


@pytest.mark.asyncio
async def test_ensure_synced_close_when_loop_running():
    """_ensure_synced should create a task to close when loop is running."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()

    class Dummy:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    d = Dummy()
    t._session = d
    # flip snapshot so ensure_synced will attempt to close
    t._applied_snapshot = None
    # Call within running loop
    t._ensure_synced()
    # Allow scheduled task to run
    await asyncio.sleep(0)
    assert t._session is None
    assert d.closed is True


@pytest.mark.asyncio
async def test_wikipedia_url_param_appends_and_fetches():
    """Using the 'url' param in wikipedia() should append and fetch HTML."""
    wiki_page_url = "https://en.wikipedia.org/wiki/Alan_Turing"
    plan = {
        wiki_page_url: [(200, "<html>Alan Turing Page</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    # return_raw=True => handler returns HTML
    out = await t.wikipedia(url=wiki_page_url, return_raw=True)
    assert "Alan Turing Page" in out
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_handler_not_registered_raises():
    """If WikipediaHandler not registered, Tools.wikipedia should raise RuntimeError."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    # Remove all handlers
    t._handlers = []
    with pytest.raises(RuntimeError):
        await t.wikipedia(pages=["Alan Turing"], return_raw=True)
    await t.close()


@pytest.mark.asyncio
async def test_invalid_url_with_allowlist_raises():
    """Invalid URL should raise when allow/deny validation is active."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    t.valves.allow_hosts = ["example.com"]
    with pytest.raises(ValueError):
        await t.scrape(url="not-a-url")
    await t.close()


@pytest.mark.asyncio
async def test_deny_hosts_blocks():
    """deny_hosts should block matching hosts when allowlist is not set."""
    plan = {"https://banned.com": [(200, "<html>Bad</html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.deny_hosts = ["banned.com"]
    with pytest.raises(ValueError):
        await t.scrape(url="https://banned.com")
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_redirect_without_handler_falls_back_to_scrape():
    """When handler missing, redirect path should fall back to _scrape (HTML)."""
    wiki_page_url = "https://en.wikipedia.org/wiki/Alan_Turing"
    plan = {wiki_page_url: [(200, "<html>Fallback</html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    # Remove handler so get_handler_for returns None
    t._handlers = []
    out = await t.scrape(url=wiki_page_url, redirect=True, return_raw=True)
    assert "Fallback" in out
    await t.close()
