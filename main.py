"""
title: Async Webscraper
author: Zack Allison <zack@zackallison.com>
version: 0.1.4
"""

"""
NOTES:

Renaming this tool to "webscraper" makes models more likely to find it.

Your LLM might need to be "fine tuned", an example:

You have the [async_webscraper/scrape] tool, along with helpers for specific sites.
Call the scrape tool with a list or urls to fetch.
Call the wikipedia tool with a list of urls or titles.
It allows you to retrieve either the html or an auto-generated summary.
The summary is much shorter and useful for quick overviews, the html is longer and better for deeper dives.

The Rules:

- Do not make anything up if the scrape fails.
- When calling these scrape tools make sure to send only properly formatted complete urls.
- When calling the wikipedia tools pass only the name of the page you want, not the url.
- As we’re only making a single request per user input, the standards of robots.txt allow us to fetch from every site that doesn’t explicitly disallow it.
"""

import asyncio
import time
from typing import Optional, Dict, Any, Union
import aiohttp
from pydantic import BaseModel, Field
import json
import re

try:
    import html2text
except ImportError as e:
    import lxml

    class html2text:
        @staticmethod
        def html2text(html: str) -> str:
            plain_text = lxml.etree.HTML(html).xpath("//text()")
            return " ".join(plain_text)


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

HEADERS = {
    "User-Agent": USER_AGENT,
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
    """
    High-level async web scraping utility.

    Inputs/Outputs summary:
    - Public methods return str content (raw HTML/JSON/XML or plaintext summary).
    - Wikipedia helpers return concatenated page results as str.
    """

    VERSION = "0.1.4"

    class Valves(BaseModel):
        """Runtime tuning knobs.

        Inputs:
        - user_agent: header value for HTTP requests
        - retries: number of attempts for fetch with backoff
        - timeout: per-request timeout seconds
        - min_summary_size: below this raw HTML is returned
        - max_summary_size: cap for plaintext length

        Outputs: N/A (configuration container)
        """
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
            1024,
            description="Minimum response size to consider summarizing.",
        )
        max_summary_size: int = Field(
            1024 * 10, description="Cut a summary off after this many characters."
        )
        max_body_bytes: Optional[int] = Field(
            None,
            description="If set, cap the fetched response body to this many bytes.",
        )
        concurrency: int = Field(
            5, description="Max concurrent requests when passing multiple URLs."
        )
        wiki_lang: str = Field(
            "en", description="Wikipedia language code for API requests."
        )
        allow_hosts: Optional[List[str]] = Field(
            None,
            description="If set, only allow requests to these hostnames (exact match).",
        )

    def __init__(self):
        """
        Initialize with default valves and prepare session management.

        Inputs: none
        Outputs: Tools instance with lazy ClientSession creation
        """
        self.valves = self.Valves()
        self._session: Optional[aiohttp.ClientSession] = None
        self._applied_snapshot: Optional[tuple] = None
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
    async def _wiki_do_not_call_me(  # stupid LLMs calling internal functions.
        self, page: str, return_html: bool = True, lang: str = "en", emitter=None
    ) -> str:
        """
        Fetch json from wikipedia. returns the English version
        TODO: language valve
        """
        url = ""
        if "http" in page or "wikipedia.com" in page:
            page = page.rsplit("/", 1)[-1]
        page = page.title()  # Title Case for Wikipedia
        url = f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles={page}"
        return await self.scrape(url=url, return_html=return_html, emitter=emitter)

    async def wikipedia(
        self,
        pages: list[str] = [],
        page: str = None,
        url: str = None,
        urls: list[str] = [],
        return_html: bool = True,
        emitter=None,
    ) -> str:
        """
        Retrieve Multiple Pages from wikipedia
        pages: a list of str of pages to retrieve
        """
        if page:
            pages.append(page)
        if url:
            pages.append(url)
        if urls:
            pages.append(urls)

        retval = ""
        for page in pages:
            scrape = await self._wiki_do_not_call_me(
                page=page, return_html=return_html, emitter=emitter
            )
            retval += str(scrape)
        return retval

    wikipedia_multi = wikipedia
    wikipedia_pages = wikipedia
    wikipedia_page = wikipedia
    get_wiki = wikipedia

    # ------------------------ Helpers and Aliases------------------------
    ## Summarize
    async def summarize(self, urls: list[str] = [], url: str = None, emitter=None):
        return await self.scrape(urls, url=url, return_html=False, emitter=emitter)

    get_summary = summarize
    overview = summarize

    # ------------------------ Main Scrape Logic ------------------------

    async def scrape(
        self,
        urls: list[str] = [],
        url: str = None,
        return_html: bool = True,
        emitter=None,
    ) -> Union[Dict[str, Any], str]:  # Fixed typing here
        """
        Fetch, parse, and extract title, main content, summary
        option: return_html = True to get ONLY the raw content.
        option: return_html = False to get ONLY the summary.

        Note: files below valve min_summary_size will be returned as-is
        """
        if url:
            urls.append(url)
        result = ""
        for page in urls:
            val = await self._scrape(url=page, return_html=return_html, emitter=emitter)
            result += str(val)
        return result

    async def _scrape(self, url: str, return_html: bool = True, emitter=None) -> str:
        """Internal Method: Do not call"""

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

        def _clean_html(html):
            flags = re.S | re.M | re.I
            html = re.sub(r".*Contents.move to sidebar.hide", "", html, flags=flags)
            html = re.sub(r"<head>.*</head>", "", html, flags=flags)
            html = re.sub(r"<script>.*</script>", "", html, flags=flags)
            return html

        def _get_all_content(html) -> str:
            return html2text.html2text(_clean_html(html))

        def _summarize(self, text: str, max_words=2048) -> str:
            """Simple naive summarizer"""
            words = re.split(r"\s+", _clean_html(text))
            return " ".join(words[:max_words])

        # --- Actual work ---
        self._ensure_synced()
        if not url:
            raise ValueError("Input must be a string with a valid 'url'.")
        if emitter:
            await self._emit(emitter, {"type": "start", "url": url})

        try:
            html = await _fetch(self, url, emitter=emitter)
        except Exception as e:
            # Emit a clear failure event and avoid caching broken data
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

        min_size_check = int(self.valves.min_summary_size) or 0
        if min_size_check and len(html) <= min_size_check:
            return_html = True

        if emitter:
            await self._emit(emitter, {"type": "done", "url": url})

        if return_html:
            return html

        content = _get_all_content(html)
        max_size_check = int(self.valves.max_summary_size) or 0
        if max_size_check and len(content) >= max_size_check:
            content = content[:max_size_check]

        if content:
            return content

        return html

    get = scrape
    fetch = scrape
    pull = scrape
    download = scrape
    html = scrape
