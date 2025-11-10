import pytest

from tests.test_main import with_fake_session


@pytest.mark.asyncio
async def test_scrape_raises_on_empty_string(monkeypatch):
    # Patch _scrape to simulate empty result
    main = with_fake_session({})
    t = main.Tools()

    async def empty_scrape(self, url: str, return_raw: bool = True, emitter=None, redirect=True):
        return ""

    monkeypatch.setattr(main.Tools, "_scrape", empty_scrape, raising=True)
    with pytest.raises(ValueError):
        await t.scrape(url="https://empty.example")
    await t.close()


@pytest.mark.asyncio
async def test_scrape_raises_on_none(monkeypatch):
    # Patch _scrape to simulate None result
    main = with_fake_session({})
    t = main.Tools()

    async def none_scrape(self, url: str, return_raw: bool = True, emitter=None, redirect=True):
        return None

    monkeypatch.setattr(main.Tools, "_scrape", none_scrape, raising=True)
    with pytest.raises(ValueError):
        await t.scrape(url="https://none.example")
    await t.close()
