import json
import pytest

from tests.test_main import with_fake_session


@pytest.mark.asyncio
async def test_scrape_returns_nonempty_default_raw():
    plan = {"https://nonempty.com": [(200, "<html><body>Hi</body></html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.scrape(url="https://nonempty.com")
    assert isinstance(out, str) and len(out.strip()) > 0
    await t.close()


@pytest.mark.asyncio
async def test_summarize_returns_nonempty_when_content_present():
    long_content = "Hello " * 300
    plan = {"https://summary.me": [(200, f"<html><body>{long_content}</body></html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.summarize(url="https://summary.me")
    assert isinstance(out, str) and len(out.strip()) > 0
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_title_return_raw_json_nonempty():
    api_url = (
        "https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles=Alan%20Turing"
    )
    plan = {api_url: [(200, json.dumps({"query": {"pages": {"1": {"extract": "Alan"}}}}), None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.wikipedia(pages=["Alan Turing"], return_raw=True)
    assert isinstance(out, str) and len(out.strip()) > 0
    await t.close()


@pytest.mark.asyncio
async def test_wikipedia_url_return_raw_html_nonempty():
    wiki_page_url = "https://en.wikipedia.org/wiki/Alan_Turing"
    plan = {wiki_page_url: [(200, "<html>Alan Page</html>", None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    out = await t.wikipedia(url=wiki_page_url, return_raw=True)
    assert isinstance(out, str) and len(out.strip()) > 0
    await t.close()
