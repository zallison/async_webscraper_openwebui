"""

Renaming this tool to "webscraper" makes models more likely to find it.

Your LLM might need to be "fine tuned":

You have the async_webscraper/scrape tool, along with helpers for specific sites.
It allows you to retrieve either the html or an auto-generated summary.
The summary is much shorter and useful for quick overviews, the html is longer and better for deeper dives.

The Rules:

- Do not make anything up if the scrape fails.
- When calling this tools make sure to send only properly formatted complete urls.
- As we’re only making a single request per user input, the standards of robots.txt allow us to fetch from every site that doesn’t explicitly disallow it.
"""

import asyncio
import time
from typing import Optional, Dict, Any
import aiohttp
from pydantic import BaseModel, Field
import json
import re
from functools import lru_cache

try:
    import html2text
except ImportError as e:
    import lxml

    class html2text:
        def html2text(html: str) -> str:
            plain_text = lxml.etree.HTML(html).xpath("//text()")
            return " ".join(plain_text)


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

HEADERS = {
    "User_Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "DNT": "1",  # Do Not Track
    "Cache-Control": "max-age=0",
    "Pragma": "no-cache",
}


try:
    from fake_useragent import UserAgent

    ua = UserAgent()
    USER_AGENT = ua.random()
except Exception as e:
    pass


class Tools:
    VERSION = "0.1.3"

    class Valves(BaseModel):
        model_config = {"arbitrary_types_allowed": True}

        user_agent: str = Field(
            USER_AGENT,
            description="User-Agent header to use for HTTP requests.",
        )
        retries: int = Field(
            3, description="Number of retry attempts for HTTP requests."
        )
        timeout: int = Field(10, description="Request timeout in seconds.")
        min_summary_size: int = Field(
            2048,  # Set appropriate for you context length.
            description="How large a response do we need before we stop just returning html? Increase this value according to your context length",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._session: Optional[aiohttp.ClientSession] = None
        self._applied_snapshot = None
        self._ensure_synced()

    # ------------------------ Internal Utilities ------------------------

    def _valves_snapshot(self):
        v = self.valves
        return (v.user_agent, v.retries, v.timeout, v.min_summary_size)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _emit(self, emitter, event: Dict[str, Any]) -> None:
        try:
            if hasattr(emitter, "emit") and asyncio.iscoroutinefunction(emitter.emit):
                await emitter.emit(event)
            elif callable(getattr(emitter, "emit", None)):
                emitter.emit(event)
            else:
                await emitter(event)
        except Exception:
            pass

    def _ensure_synced(self):
        snapshot = self._valves_snapshot()
        if snapshot == self._applied_snapshot:
            return

        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._session.close())
                else:
                    asyncio.run(self._session.close())
            except Exception:
                pass
        self._session = None
        self._applied_snapshot = snapshot

    async def _get_session(self) -> aiohttp.ClientSession:
        self._ensure_synced()
        if self._session and not self._session.closed:
            return self._session
        v = self.valves
        headers = HEADERS.copy()
        if v.user_agent:
            headers["User-Agent"] = v.user_agent
        self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    # ------------------------ Helpers and Aliases ------------------------
    ## Wikipedia
    async def wikipedia_page(page: str, return_html: bool = True, emitter=None) -> str:
        return await self.wikipedia(page=page, return_html=return_html, emitter=emitter)

    async def wikipedia(
        self, page: str, return_html: bool = True, lang: str = "en", emitter=None
    ) -> str:
        """
        Fetch json from wikipedia. returns the English version
        TODO: language valve
        """
        url = f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles={page}"
        return await self.scrape(url=url, return_html=return_html, emitter=emitter)

    async def simple_wikipedia(self, page: str, return_html=True, emitter=None) -> str:
        """
        Get a simple explanation about "page".
        """
        return await self.wikipedia(
            lang="simple", url=url, return_html=return_html, emitter=emitter
        )

    #
    # Multiple Wikipedia articles
    #
    async def wikipedia_pages(
        self, pages: list[str], return_html: bool = True, emitter=None
    ):
        return await self.wikipedia_multi(
            lang="simple", pages=pages, return_html=return_html, emitter=emitter
        )

    async def wikipedia_multi(
        self, pages: list[str], return_html: bool = True, emitter=None
    ) -> str:
        """
        Retrieve Multiple Pages from wikipedia
        pages: a list of str of pages to retrieve
        """
        result = ""
        for page in pages:
            scrape = await self.wikipedia(page=page)
            result += str(scrape)
        return result

    # ------------------------ Helpers and Aliases------------------------

    ##
    ## List Aliases
    ##
    async def get_multi(self, urls: list[str], return_html: bool = True, emitter=None):
        return await self.scrape_multi(
            urls=urls, return_html=return_html, emitter=emitter
        )

    async def multi_scrape(
        self, urls: list[str], return_html: bool = True, emitter=None
    ):
        return await self.scrape_multi(
            urls=urls, return_html=return_html, emitter=emitter
        )

    async def scrape_multi(
        self, urls: list[str], return_html: bool = True, emitter=None
    ):
        result = ""
        for page in urls:
            scrape = await self.scrape(
                url=page, return_html=return_html, emitter=emitter
            )
            result += str(scrape)
        return result

    ##
    ## Simple Aliases
    ##

    async def html(self, url: str, return_html: bool = True, emitter=None):
        return await self.scrape(url=url, return_html=return_html, emitter=emitter)

    async def fetch(self, url: str, return_html: bool = False, emitter=None):
        return await self.scrape(url=url, return_html=return_html, emitter=emitter)

    async def download(self, url: str, return_html: bool = False, emitter=None):
        return await self.scrape(url, return_html=return_html, emitter=emitter)

    async def pull(self, url: str, return_html: bool = False, emitter=None):
        return await self.scrape(url, return_html=return_html, emitter=emitter)

    async def get(self, url: str, return_html: bool = False, emitter=None):
        return await self.scrape(url, return_html=return_html, emitter=emitter)

    async def get_summary(self, url: str, emitter=None):
        return await self.scrape(url, return_html=False, emitter=emitter)

    async def summarize(self, url: str, emitter=None):
        return await self.scrape(url, return_html=False, emitter=emitter)

    # ------------------------ Main Scrape Logic ------------------------

    async def scrape(
        self, url: str, return_html: bool = True, emitter=None
    ) -> Dict[str, Any]:
        """
        Fetch, parse, and extract title, main content, summary
        option: return_html = True to get ONLY the raw content.
        option: return_html = False to get ONLY the summary.

        Note: files below valve min_summary_size will be returned as-is
        """

        @lru_cache(maxsize=128, typed=False)
        async def _fetch(self, url: str, emitter=None) -> str:
            sess = await self._get_session()
            retries = max(0, int(self.valves.retries))
            backoff_base = 0.5
            last_exc = None

            for attempt in range(1, retries + 1):
                if emitter:
                    await self._emit(
                        emitter,
                        {"type": "fetch_attempt", "attempt": attempt, "url": url},
                    )
                try:
                    async with sess.get(url, timeout=int(self.valves.timeout)) as resp:
                        resp.raise_for_status()
                        text = await resp.text()
                        if emitter:
                            await self._emit(
                                emitter,
                                {"type": "fetched", "status": resp.status, "url": url},
                            )
                        return text
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        wait = backoff_base * (2 ** (attempt - 1))
                        if emitter:
                            await self._emit(
                                emitter,
                                {
                                    "type": "fetch_retry",
                                    "attempt": attempt,
                                    "wait": wait,
                                    "error": str(e),
                                },
                            )
                        await asyncio.sleep(wait)
                    else:
                        if emitter:
                            await self._emit(
                                emitter,
                                {
                                    "type": "fetch_failed",
                                    "attempt": attempt,
                                    "error": str(e),
                                },
                            )
            raise Exception(f"Failed to fetch {url}: {last_exc}")

        def _get_all_content(html) -> str:
            return html2text.html2text(html)

        def _summarize(text: str, max_sentences=3) -> str:
            """Simple naive summarizer"""
            import re

            sentences = re.split(r"(?<=[.!?]) +", text)
            return " ".join(sentences[:max_sentences])

        # --- Actual work ---
        self._ensure_synced()
        if not url:
            raise ValueError("Input must be a string with a valid 'url'.")
        if emitter:
            await self._emit(emitter, {"type": "start", "url": url})

        try:
            html = await _fetch(self, url, emitter=emitter)
        except Exception as e:
            # FIX: emit a clear failure event and avoid caching broken data
            if emitter:
                await self._emit(
                    emitter,
                    {"type": "fetch_failed_final", "url": url, "error": str(e)},
                )
            raise  # re-raise so caller still gets the error

        try:
            json_obj = json.loads(html)
            if emitter:
                await self._emit(
                    emitter,
                    {"type": "found json", "url": url},
                )

            return_html = True
        except (json.JSONDecodeError, ValueError):
            pass

        # Dumb XML Check
        try:
            xml_pattern = r"^\s*<\?xml\s"
            if re.match(xml_pattern, html):
                """We've found XML"""
                return_html = True
        except Exception as e:
            pass

        size_check = int(self.valves.min_summary_size) or 0
        if size_check and len(html) <= size_check:
            return_html = True

        if emitter:
            await self._emit(emitter, {"result": html, "type": "done", "url": url})

        if return_html:
            return html

        content = _get_all_content(html)

        if content:
            return content

        return html
