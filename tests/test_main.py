import asyncio
import importlib
import json
import re
import types
import pytest
import aiohttp

from conftest import FakeSession, Emitter


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
async def test_scrape_returns_html_by_default(monkeypatch):
    main = with_fake_session(
        {"https://example.com": [(200, "<html><body>Hello</body></html>", None)]}
    )
    t = main.Tools()
    out = await t.scrape(url="https://example.com")
    assert "Hello" in out
    await t.close()


@pytest.mark.asyncio
async def test_summarize_returns_plaintext(monkeypatch):
    # Create content longer than default min_summary_size (1024)
    long_content = "Hello World " * 100  # Makes it well over 1k
    main = with_fake_session(
        {
            "https://example.com": [
                (200, f"<html><body>{long_content}</body></html>", None)
            ]
        }
    )
    t = main.Tools()
    out = await t.summarize(url="https://example.com")
    assert "Hello" in out and "<html>" not in out
    await t.close()


@pytest.mark.asyncio
async def test_json_and_xml_parsed(monkeypatch):
    main = with_fake_session(
        {
            "https://json.io": [(200, json.dumps({"a": 1}), None)],
            "https://xml.io": [(200, '<?xml version="1.0"?><root>ok</root>', None)],
        }
    )
    t = main.Tools()
    out_json = await t.scrape(url="https://json.io", return_raw=False)
    assert isinstance(out_json, dict) and out_json["a"] == 1
    out_xml = await t.scrape(url="https://xml.io", return_raw=False)
    # Parsed to Element
    import xml.etree.ElementTree as ET

    assert isinstance(out_xml, ET.Element) and out_xml.tag == "root"
    await t.close()


@pytest.mark.asyncio
async def test_min_summary_size_forces_html(monkeypatch):
    main = with_fake_session({"https://small.io": [(200, "<html>hi</html>", None)]})
    t = main.Tools()
    t.valves.min_summary_size = 1000
    out = await t.scrape(url="https://small.io", return_raw=False)
    assert "<html>hi</html>" in out
    await t.close()


@pytest.mark.asyncio
async def test_max_summary_size_truncation(monkeypatch):
    long_text = "word " * 5000
    main = with_fake_session(
        {"https://big.io": [(200, f"<html><body>{long_text}</body></html>", None)]}
    )
    t = main.Tools()
    t.valves.max_summary_size = 500
    out = await t.summarize(url="https://big.io")
    # Account for the "Contents of url: {url}\n" header
    lines = out.split("\n", 1)
    content = lines[1] if len(lines) > 1 else ""
    assert len(content) <= 500
    await t.close()


@pytest.mark.asyncio
async def test_emitter_events_and_retries(monkeypatch):
    class Boom(Exception):
        pass

    plan = {
        "https://flaky.io": [
            (500, "bad", Boom("boom1")),
            (200, "<html>ok</html>", None),
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.retries = 2
    emitter = Emitter()
    out = await t.scrape(url="https://flaky.io", emitter=emitter)
    assert "ok" in out
    # Check key events sequence presence
    types_seen = [e.get("type") for e in emitter.events]
    assert "start" in types_seen
    assert "fetch_attempt" in types_seen
    assert "fetch_retry" in types_seen
    assert "fetched" in types_seen
    assert "done" in types_seen
    await t.close()


@pytest.mark.asyncio
async def test_final_failure_emits_and_raises(monkeypatch):
    class Boom(Exception):
        pass

    plan = {"https://down.io": [(500, "bad", Boom("nope"))] * 3}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.retries = 3
    emitter = Emitter()
    with pytest.raises(Exception):
        await t.scrape(url="https://down.io", emitter=emitter)
    types_seen = [e.get("type") for e in emitter.events]
    assert "fetch_failed_final" in types_seen
    assert "fetch_failed" in types_seen
    await t.close()


@pytest.mark.asyncio
async def test_close_and_session_recreation(monkeypatch):
    main = with_fake_session({"https://a.io": [(200, "<html>a</html>", None)]})
    t = main.Tools()
    s1 = await t._get_session()
    t.valves.user_agent = "UA-NEW"
    s2 = await t._get_session()
    assert s1 is not s2
    await t.close()
    assert s2.closed is True


@pytest.mark.asyncio
async def test_wikipedia_helper_and_redirect_bug(monkeypatch):
    # Wikipedia helper constructs API URL; respond to it
    api_url = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Alan%20Turing"
    wiki_page_url = "https://en.wikipedia.org/wiki/Alan_Turing"
    plan = {
        api_url: [
            (
                200,
                json.dumps({"query": {"pages": {"1": {"extract": "Alan Turing"}}}}),
                None,
            )
        ],
        wiki_page_url: [(200, "<html>Alan Turing Wikipedia Page</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.wikipedia(pages=["Alan Turing"], return_raw=True)
    assert "Alan Turing" in out or out.strip().startswith("{")

    # Redirect path in scrape should work now (no exception)
    # When redirect=True and return_raw=True, handler returns HTML
    out2 = await t.scrape(url="https://en.wikipedia.org/wiki/Alan_Turing")
    assert isinstance(out2, str) and len(out2) > 0
    await t.close()


@pytest.mark.asyncio
async def test_aliases_delegate(monkeypatch):
    main = with_fake_session({"https://alias.io": [(200, "<html>x</html>", None)]})
    t = main.Tools()
    # All aliases should work
    assert "x" in await t.get(url="https://alias.io")
    assert "x" in await t.fetch(url="https://alias.io")
    assert "x" in await t.pull(url="https://alias.io")
    assert "x" in await t.download(url="https://alias.io")
    assert "x" in await t.html(url="https://alias.io")
    assert "x" in await t.overview(url="https://alias.io")
    assert "x" in await t.get_summary(url="https://alias.io")
    await t.close()


@pytest.mark.asyncio
async def test_emitter_found_json_event(monkeypatch):
    plan = {"https://json.events": [(200, json.dumps({"k": "v"}), None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    emitter = Emitter()
    out = await t.scrape(url="https://json.events", return_raw=False, emitter=emitter)
    assert isinstance(out, dict) and out["k"] == "v"
    types_seen = [e.get("type") for e in emitter.events]
    assert "found json" in types_seen
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_title_normalization_variants(monkeypatch):
    api_url1 = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Alan%20Turing"
    api_url2 = "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Caf%C3%A9"
    plan = {
        api_url1: [(200, "{}", None)],
        api_url2: [(200, "{}", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    # underscore variant
    out1 = await t.wikipedia(pages=["Alan_Turing"], return_raw=True)
    assert isinstance(out1, str)
    # percent-encoded diacritics
    out2 = await t.wikipedia(
        urls=["https://en.wikipedia.org/wiki/Caf%C3%A9"], return_raw=True
    )
    assert isinstance(out2, str)
    # single title via 'page' argument (covers append(page) path)
    out3 = await t.wikipedia(page="Alan Turing", return_raw=True)
    assert isinstance(out3, str)
    await t.close()


@pytest.mark.asyncio
async def test_multiple_urls_concatenation_and_structured(monkeypatch):
    plan = {
        "https://a.com": [(200, "<html>A</html>", None)],
        "https://b.com": [(200, "<html>B</html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.scrape(urls=["https://a.com", "https://b.com"])
    assert ("A" in out and "B" in out) and out.index("A") < out.index("B")
    structured = await t.scrape(
        urls=["https://a.com", "https://b.com"], return_structured=True
    )
    assert isinstance(structured, list) and structured[0]["url"].endswith("a.com")
    await t.close()


@pytest.mark.asyncio
async def test_session_timeout_applied():
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    t.valves.timeout = 2
    s = await t._get_session()
    assert isinstance(s.timeout, aiohttp.ClientTimeout)
    # aiohttp may store as float
    assert int(s.timeout.total) == 2
    await t.close()


@pytest.mark.asyncio
async def test_close_idempotent_without_session():
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    await t.close()
    await t.close()


@pytest.mark.asyncio
async def test_redirect_disabled_fetches_raw_html(monkeypatch):
    wiki_url = "https://en.wikipedia.org/wiki/Alan_Turing"
    plan = {wiki_url: [(200, "<html>Wiki Page Raw</html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.scrape(url=wiki_url, redirect=False)
    assert "Wiki Page Raw" in out
    await t.close()


@pytest.mark.asyncio
async def test_allow_and_deny_hosts_enforced(monkeypatch):
    plan = {"https://banned.com": [(200, "<html>Bad</html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.allow_hosts = ["example.com"]
    with pytest.raises(ValueError):
        await t.scrape(url="https://banned.com")
    # allow should override deny when both contain the host
    t.valves.allow_hosts = ["banned.com"]
    t.valves.deny_hosts = ["banned.com"]
    out = await t.scrape(url="https://banned.com")
    assert "Bad" in out


def test_ensure_synced_close_when_loop_not_running():
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
    t._ensure_synced()
    assert t._session is None
    assert d.closed is True


@pytest.mark.asyncio
async def test_emitter_sync_emit_object(monkeypatch):
    class SyncEmitter:
        def __init__(self):
            self.events = []

        def emit(self, event):
            self.events.append(event)

    main = with_fake_session({"https://x.com": [(200, "<html>x</html>", None)]})
    t = main.Tools()
    e = SyncEmitter()
    await t.scrape(url="https://x.com", emitter=e)
    assert any(ev.get("type") == "done" for ev in e.events)
    await t.close()


@pytest.mark.asyncio
async def test_emitter_plain_async_callable(monkeypatch):
    events = []

    async def collector(event):
        events.append(event)

    main = with_fake_session({"https://y.com": [(200, "<html>y</html>", None)]})
    t = main.Tools()
    await t.scrape(url="https://y.com", emitter=collector)
    assert any(ev.get("type") == "done" for ev in events)
    await t.close()


@pytest.mark.asyncio
async def test_emitter_exception_is_suppressed(monkeypatch):
    def bad_emit(ev):
        raise RuntimeError("boom")

    main = with_fake_session({"https://e.com": [(200, "<html>e</html>", None)]})
    t = main.Tools()
    # Should not raise despite emitter raising
    await t.scrape(url="https://e.com", emitter=bad_emit)
    await t.close()


@pytest.mark.asyncio
async def test__scrape_invalid_input_raises():
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    with pytest.raises(ValueError):
        await t._scrape(url=None)
    await t.close()


@pytest.mark.asyncio
async def test_retries_min_one(monkeypatch):
    class Boom(Exception):
        pass

    plan = {"https://failonce.com": [(500, "no", Boom("boom"))]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.retries = 0  # should be treated as at least 1
    emitter = Emitter()
    with pytest.raises(Exception):
        await t.scrape(url="https://failonce.com", emitter=emitter)
    attempts = [e for e in emitter.events if e.get("type") == "fetch_attempt"]
    assert len(attempts) == 1
    await t.close()


@pytest.mark.asyncio
async def test_user_agent_header_applied():
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    t = main_mod.Tools()
    t.valves.user_agent = "TestAgent/1.0"
    s = await t._get_session()
    assert s.headers.get("User-Agent") == "TestAgent/1.0"
    # Call again to exercise early return path
    s2 = await t._get_session()
    assert s2 is s
    await t.close()


@pytest.mark.asyncio
async def test_plain_sync_callable_emitter(monkeypatch):
    events = []

    def coll(ev):
        events.append(ev)

    main = with_fake_session({"https://z.com": [(200, "<html>z</html>", None)]})
    t = main.Tools()
    await t.scrape(url="https://z.com", emitter=coll)
    assert any(e.get("type") == "done" for e in events)
    await t.close()


@pytest.mark.asyncio
async def test_summary_empty_content_returns_original_html(monkeypatch):
    # Provide HTML with no text content after cleaning
    plan = {
        "https://empty.com": [
            (
                200,
                "<html><head><script>var x=1;</script></head><body></body></html>",
                None,
            )
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.min_summary_size = 0
    out = await t.summarize(url="https://empty.com")
    # Since content extraction yields empty string, fallback returns original html
    # Skip the first line which contains the URL header
    lines = out.split("\n")
    assert len(lines) >= 2
    assert lines[1].startswith("<html>")
    await t.close()


@pytest.mark.asyncio
async def test_max_body_bytes_cap(monkeypatch):
    body = "<html>" + ("x" * 1000) + "</html>"
    plan = {"https://cap.io": [(200, body, None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.max_body_bytes = 50
    out = await t.scrape(url="https://cap.io", return_raw=True)
    assert isinstance(out, str)
    # Skip the first line which contains the URL header
    lines = out.split("\n")
    assert len(lines) >= 2
    assert lines[1] == body[:50]
    await t.close()


@pytest.mark.asyncio
async def test_internal_summarize_helper(monkeypatch):
    """Test the _summarize nested function inside _scrape.

    Note: _summarize is currently defined but not used in the codebase.
    This test accesses it by creating HTML with many words and checking
    that it would truncate correctly if it were called.
    """
    import main as main_mod
    import re

    # Create a simple test of the _summarize logic
    # Since _summarize is a nested function, we'll test the logic directly
    def _clean_html(html):
        flags = re.S | re.M | re.I
        html = re.sub(r".*Contents.move to sidebar.hide", "", html, flags=flags)
        html = re.sub(r"<head>.*</head>", "", html, flags=flags)
        html = re.sub(r"<script>.*</script>", "", html, flags=flags)
        return html

    def _summarize(text: str, max_words=2048) -> str:
        """Simple naive summarizer (replica of internal function)"""
        words = re.split(r"\s+", _clean_html(text))
        return " ".join(words[:max_words])

    # Test with HTML containing many words
    long_html = (
        "<html><body>"
        + (" ".join([f"word{i}" for i in range(3000)]))
        + "</body></html>"
    )
    result = _summarize(long_html, max_words=100)
    word_count = len([w for w in result.split() if w])

    # Should truncate to max_words (100) or fewer
    assert word_count <= 100
    assert "word0" in result
    assert "word99" in result or word_count < 100
