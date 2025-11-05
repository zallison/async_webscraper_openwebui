import importlib
import json
import pytest

from conftest import FakeSession


def with_fake_session(plan):
    import main as main_mod

    async def _fake_get_session(self):
        sess = FakeSession(plan)
        self._session = sess
        return sess

    main_mod = importlib.reload(importlib.import_module("main"))
    main_mod.Tools._get_session = _fake_get_session
    return main_mod


@pytest.mark.asyncio
async def test_sitehandler_can_handle_no_hostname():
    """Exercise SiteHandler.can_handle with malformed URL (hostname None)."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.SiteHandler()
    handler.domains = (".example.com",)
    assert handler.can_handle("notaurl") is False


@pytest.mark.asyncio
async def test_wikipedia_fetch_pages_mixed_inputs_hits_both_branches():
    """Exercise WikipediaHandler.fetch_pages both branches of URL handling."""
    wiki_url = "https://en.wikipedia.org/wiki/Python"
    built_url = "https://en.wikipedia.org/wiki/Ruby"
    plan = {
        wiki_url: [(200, "<html>Python HTML</html>", None)],
        built_url: [(200, "<html>Ruby HTML</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    out = await main.WikipediaHandler().fetch_pages(
        t, [wiki_url, "Ruby"], return_html=True
    )
    assert "Python HTML" in out and "Ruby HTML" in out
    await t.close()


def test_tools_version_triggers_class_body():
    """Import Tools and access VERSION to trigger class body execution (docstring lines)."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    assert isinstance(main_mod.Tools.VERSION, str) and len(main_mod.Tools.VERSION) > 0
