"""
title: Async Webscraper
author: Zack Allison <zack@zackallison.com>
version: 0.1.5
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
from typing import Optional, Dict, Any, Union, List, Callable
import aiohttp
from pydantic import BaseModel, Field
import json
import re
import urllib.parse
import random

try:
    import html2text
except ImportError as e:  # pragma: no cover
    import lxml  # pragma: no cover

    class html2text:  # pragma: no cover
        @staticmethod
        def html2text(html: str) -> str:  # pragma: no cover
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
    from fake_useragent import UserAgent  # pragma: no cover

    ua = UserAgent()  # pragma: no cover
    USER_AGENT = ua.random()  # pragma: no cover
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self) -> None:
        """
        Close the underlying aiohttp session if open.

        Inputs: none
        Outputs: None
        """
        if self._session and not self._session.closed:
            await self._session.close()

    async def _emit(self, emitter: Callable[..., Any], event: Dict[str, Any]) -> None:
        """
        Send an event to an optional emitter, supporting sync/async callables.

        Inputs:
        - emitter: object with async/sync emit(event) or a callable
        - event: dict payload
        Outputs: None (errors suppressed)
        """
        try:
            emit_attr = getattr(emitter, "emit", None)
            if emit_attr is not None:
                if asyncio.iscoroutinefunction(emit_attr):
                    await emit_attr(event)
                else:
                    emit_attr(event)
                return
            # emitter itself is callable
            if asyncio.iscoroutinefunction(emitter):
                await emitter(event)
            else:
                emitter(event)
        except Exception:
            pass

    def _ensure_synced(self):
        """
        Recreate session when session-affecting valves change.

        Inputs: none
        Outputs: None (may schedule/perform session close)
        """
        snapshot = self._valves_snapshot()
        if snapshot == self._applied_snapshot:
            return

        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(self._session.close())
                else:
                    loop.run_until_complete(self._session.close())
            except Exception:
                # best-effort; ignore close errors
                pass
        self._session = None
        self._applied_snapshot = snapshot

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the shared aiohttp.ClientSession with current headers."""
        self._ensure_synced()
        if self._session and not self._session.closed:
            return self._session
        v = self.valves
        headers = HEADERS.copy()
        if v.user_agent:
            headers["User-Agent"] = v.user_agent
        timeout = aiohttp.ClientTimeout(total=float(v.timeout)) if v.timeout else None
        self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    # ------------------------ Helpers and Aliases ------------------------
    ## Wikipedia
    async def _do_not_call_me(  # Wiki Scrape
        self,
        page: str,
        return_html: bool = True,
        lang: Optional[str] = None,
        emitter=None,
    ) -> str:
        """
        Fetch json from wikipedia. returns the English version
        TODO: language valve
        """
        url = ""
        if "wikipedia" in page and "api" not in page:
            # Extract last path segment as title
            page = page.rsplit("/", 1)[-1]
            page = urllib.parse.unquote(page)
            page = page.replace("_", " ")

        page = page.title()  # Title Case for Wikipedia
        title_param = urllib.parse.quote(page)
        _lang = (lang or self.valves.wiki_lang or "en").strip()
        url = f"https://{_lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles={title_param}"
        return await self.scrape(url=url, return_html=return_html, emitter=emitter)

    async def wikipedia(
        self,
        pages: Optional[List[str]] = None,
        page: Optional[str] = None,
        url: Optional[str] = None,
        urls: Optional[List[str]] = None,
        return_html: bool = True,
        emitter=None,
    ) -> str:
        """Retrieve multiple pages from Wikipedia via the extracts API.

        Inputs:
        - pages/page: titles or page URLs; URLs are normalized to titles
        - url/urls: alternative URL inputs
        - return_html: True to get raw API JSON; False to summarize API response
        - emitter: optional event sink

        Output: concatenated string of results
        """
        pages = list(pages or [])
        if page:
            pages.append(page)
        if url:
            pages.append(url)
        if urls:
            pages.extend(urls)

        retval = ""
        for page in pages:
            scrape = await self._do_not_call_me(
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
    async def summarize(
        self, urls: Optional[List[str]] = None, url: Optional[str] = None, emitter=None
    ):
        """Fetch and return plaintext summary for one or more URLs.

        Inputs:
        - urls/url: one or many URLs to fetch
        - emitter: optional event sink
        Output: concatenated plaintext summaries
        """
        return await self.scrape(
            urls or [], url=url, return_html=False, emitter=emitter
        )

    get_summary = summarize
    overview = summarize

    # ------------------------ Main Scrape Logic ------------------------

    async def scrape(
        self,
        urls: Optional[List[str]] = None,
        url: Optional[str] = None,
        return_html: bool = True,
        emitter=None,
        redirect: bool = True,
        return_structured: bool = False,
    ) -> Union[Dict[str, Any], str, List[Dict[str, Any]]]:
        """Fetch content and optionally convert HTML to plaintext.

        Inputs:
        - urls/url: one or many URLs
        - return_html: True returns raw body; False returns plaintext summary
        - emitter: optional event sink receiving lifecycle events
        - redirect: if True, Wikipedia URLs are routed to the API helper

        Output: concatenated str of page results
        """
        items = list(urls or [])
        if url:
            items.append(url)
        # Validate allowlist
        allow = self.valves.allow_hosts
        if allow:
            for page in items:
                parsed = urllib.parse.urlparse(page)
                if (
                    not parsed.scheme
                    or not parsed.netloc
                    or parsed.hostname not in allow
                ):
                    raise ValueError(f"Host not allowed: {page}")

        sem = asyncio.Semaphore(max(1, int(self.valves.concurrency) or 1))

        async def process(page: str):
            async with sem:
                if redirect and ("wikipedia" in page and "api" not in page):
                    ret = await self.wikipedia(
                        url=page, return_html=return_html, emitter=emitter
                    )
                else:
                    ret = await self._scrape(
                        url=page, return_html=return_html, emitter=emitter
                    )
                if return_structured:
                    return {"url": page, "content": ret}
                return ret

        results = (
            [await process(p) for p in items]
            if len(items) <= 1
            else await asyncio.gather(*[process(p) for p in items])
        )
        if return_structured:
            return results
        return "".join(map(str, results))

    async def _scrape(
        self, url: str, return_html: bool = True, emitter=None, redirect=True
    ) -> str:
        """Low-level fetch + transform for a single URL.

        Inputs:
        - url: target URL
        - return_html: passthrough raw response when True; else plaintext summary
        - emitter: optional callback for progress events
        Outputs: str
        """

        async def _fetch(self, url: str, emitter=None) -> str:
            sess = await self._get_session()
            retries = max(1, int(self.valves.retries))
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
                        # Read with optional size cap
                        # Determine text vs bytes decoding later
                        body = await resp.read()
                        status = resp.status
                        if status >= 400:
                            raise aiohttp.ClientResponseError(
                                resp.request_info,
                                resp.history,
                                status=status,
                                message="bad status",
                            )
                        if emitter:
                            await self._emit(
                                emitter,
                                {"type": "fetched", "status": status, "url": url},
                            )
                        # apply max_body_bytes
                        max_bytes = self.valves.max_body_bytes
                        if (
                            isinstance(max_bytes, int)
                            and max_bytes > 0
                            and len(body) > max_bytes
                        ):
                            body = body[:max_bytes]
                        # Decode according to content-type
                        ctype = resp.headers.get("Content-Type", "")
                        charset = None
                        if "charset=" in ctype:
                            charset = (
                                ctype.split("charset=", 1)[-1].split(";")[0].strip()
                            )
                        text = body.decode(charset or "utf-8", errors="replace")
                        return text
                except Exception as e:
                    last_exc = e
                    if attempt < retries:
                        # status-based retry window
                        jitter = random.uniform(0, 0.25)
                        wait = backoff_base * (2 ** (attempt - 1)) + jitter
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

        def _summarize(self, text: str, max_words=2048) -> str:  # pragma: no cover
            """Simple naive summarizer"""
            words = re.split(r"\s+", _clean_html(text))
            return " ".join(words[:max_words])

        # / Helpers

        #######################
        # --- Actual work --- #
        #######################

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
            raise e  # re-raise so caller still gets the error

        try:
            # Prefer header detection if available via simplistic heuristic
            # Already decoded above; attempt JSON parse
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
        except Exception as e:  # pragma: no cover
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
