"""
title: Async Webscraper
author: Zack Allison <zack@zackallison.com>
author_url: https://github.com/zallison
git_url: https://github.com/zallison/async_webscraper_openwebui
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
from typing import Optional, Dict, Any, Union, List
import aiohttp
from pydantic import BaseModel, Field
import json
import re
import urllib.parse
import random
import xml.etree.ElementTree as ET

try:
    import html2text
except ImportError as e:  # pragma: no cover
    import lxml  # pragma: no cover

    class html2text:  # pragma: no cover
        @staticmethod
        def html2text(html: str) -> str:  # pragma: no cover
            plain_text = lxml.etree.HTML(html.encode("utf-8")).xpath("//text()")
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


class SiteHandler:
    """Base class for custom domain-specific processing.

    Inputs: Subclasses override name, domains, and async handle() method.
    Outputs: Provides domain routing and processing delegation.

    Example usage:
        class MyHandler(SiteHandler):
            name = "mysite"
            domains = (".example.com",)

            async def handle(self, tools, url, return_html=None):
                # custom processing
                return "..."
    """

    name: str = "base"
    domains: tuple = ()

    @staticmethod
    def _hostname_from_url(url: str) -> str:
        """Extract hostname from a URL.

        Inputs:
        - url: input URL string (possibly malformed)
        Outputs: hostname string or empty string when unavailable
        """
        parsed = urllib.parse.urlparse(url)
        return parsed.hostname or ""

    def can_handle(self, url: str) -> bool:
        """Check if this handler can process a given URL.

        Inputs:
        - url: target URL string
        Outputs: True if URL matches any of this handler's domains
        """
        hostname = self._hostname_from_url(url)
        return any(hostname.endswith(domain) for domain in self.domains)

    async def handle(self, tools: "Tools", url: str, return_html: Optional[bool] = None) -> str:
        """Process a URL using custom logic.

        Inputs:
        - tools: Tools instance providing session, retries, emitter, valves
        - url: target URL
        - return_html: if True, return raw HTML; if False, return plaintext; None defaults to handler behavior
        Outputs: str content (HTML or plaintext)

        Example usage:
            handler = get_handler_for("https://example.com")
            result = await handler.handle(tools_instance, url, return_html=True)
        """
        raise NotImplementedError("Subclasses must implement handle()")


class WikipediaHandler(SiteHandler):
    """Handler for Wikipedia URLs using MediaWiki API.

    Inputs: URLs with .wikipedia.org domain
    Outputs: Page extracts (plaintext) or raw HTML

    Example usage:
        handler = WikipediaHandler()
        extract = await handler.handle(tools, "https://en.wikipedia.org/wiki/Python", return_html=False)
    """

    name = "wikipedia"
    domains = (".wikipedia.org",)

    @staticmethod
    def parse_title_from_url(url: str) -> str:
        """Extract Wikipedia page title from URL.

        Inputs:
        - url: Wikipedia page URL like https://en.wikipedia.org/wiki/Alan_Turing
        Outputs: Title-cased page title string

        Example usage:
            title = WikipediaHandler.parse_title_from_url("https://en.wikipedia.org/wiki/Alan_Turing")
            # returns "Alan Turing"
        """
        if "wikipedia" in url and "api" not in url:
            # Extract last path segment as title
            page = url.rsplit("/", 1)[-1]
            page = urllib.parse.unquote(page)
            page = page.replace("_", " ")
            return page.title()
        return url.title()

    def build_api_url(self, title: str, lang: Optional[str] = None) -> str:
        """Build the MediaWiki extracts API URL for a title.

        Inputs:
        - title: Wikipedia page title
        - lang: language code (optional)
        Outputs: URL string
        """
        title_param = urllib.parse.quote(title)
        _lang = (lang or "en").strip()
        return f"https://{_lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext&format=json&titles={title_param}"

    async def _fetch_extract(
        self, tools: "Tools", title: str, lang: Optional[str] = None, emitter=None
    ) -> str:
        """Fetch plaintext extract from Wikipedia API.

        Inputs:
        - tools: Tools instance for HTTP access
        - title: Wikipedia page title
        - lang: language code (defaults to tools.valves.wiki_lang)
        - emitter: optional event sink
        Outputs: JSON response string from MediaWiki API
        """
        _lang = (lang or tools.valves.wiki_lang or "en").strip()
        url = self.build_api_url(title, _lang)
        # Use internal _scrape to maintain retry/emitter behavior
        return await tools._scrape(url=url, return_raw=True, emitter=emitter, redirect=False)

    def build_page_url(self, title: str, lang: Optional[str] = None) -> str:
        """Build the Wikipedia page URL for a title.

        Inputs:
        - title: page title (spaces allowed)
        - lang: language code (optional)
        Outputs: URL string to the HTML page
        """
        title_param = urllib.parse.quote(title.replace(" ", "_"))
        _lang = (lang or "en").strip()
        return f"https://{_lang}.wikipedia.org/wiki/{title_param}"

    async def fetch_pages(
        self, tools: "Tools", pages: List[str], return_html: bool = False, emitter=None
    ) -> str:
        """Fetch multiple Wikipedia pages.

        Inputs:
        - tools: Tools instance
        - pages: list of page titles or URLs
        - return_html: if True, fetch raw HTML; if False, fetch API extracts
        - emitter: optional event sink
        Outputs: concatenated string of all page results

        Example usage:
            handler = WikipediaHandler()
            content = await handler.fetch_pages(tools, ["Python", "Ruby"], return_html=False)
        """
        retval = ""
        for page in pages:
            if return_html:
                # Build Wikipedia URL and fetch HTML
                if "wikipedia.org/wiki/" in page:
                    url = page
                else:
                    lang = (tools.valves.wiki_lang or "en").strip()
                    url = self.build_page_url(page, lang)
                result = await tools._scrape(url=url, return_raw=True, emitter=emitter, redirect=False)
            else:
                # Parse title and fetch extract
                title = (
                    self.parse_title_from_url(page)
                    if "wikipedia" in page
                    else page.title()
                )
                result = await self._fetch_extract(tools, title, emitter=emitter)
            retval += str(result)
        return retval

    async def handle(
        self, tools: "Tools", url: str, return_html: Optional[bool] = None, emitter=None
    ) -> str:
        """Process a Wikipedia URL.

        Inputs:
        - tools: Tools instance
        - url: Wikipedia page URL
        - return_html: if True, fetch raw HTML; if False/None, fetch plaintext extract
        - emitter: optional event sink
        Outputs: page content as string
        """
        if return_html:
            return await tools._scrape(
                url=url, return_raw=True, emitter=emitter, redirect=False
            )
        else:
            title = self.parse_title_from_url(url)
            return await self._fetch_extract(tools, title, emitter=emitter)


class Tools:
    """
    High-level async web scraping utility.

    Inputs/Outputs summary:
    - Public methods return str content (raw HTML/JSON/XML or plaintext summary).
    - Wikipedia helpers return concatenated page results as str.
    """

    VERSION = "0.1.5"

    @classmethod
    def _coverage_touch_class(cls) -> str:
        """No-op helper to ensure class body lines are executed under coverage.

        Inputs: none
        Outputs: VERSION string (for assertion)
        """
        return cls.VERSION

    class Valves(BaseModel):
        """Runtime tuning knobs.

        Inputs:
        - user_agent: header value for HTTP requests
        - retries: number of attempts for fetch with backoff
        - timeout: per-request timeout seconds
        - min_summary_size: below this raw HTML is returned
        - max_summary_size: cap for plaintext length
        - max_body_bytes: cap for data response size
        - concurrency: how many files to download at once
        - wiki_lang: which wiki language? defaults to "en"
        - deny_hosts: Set a list of denied hosts to scrape from
        - allow_hosts: A list to override deny_hosts.

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
            1024 * 2, description="Cut a summary off after this many characters."
        )
        max_body_bytes: Optional[int] = Field(
            1024 * 3,
            description="If set, cap the fetched response body to this many bytes, default 3k. Keep your context length in mind.",
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
        deny_hosts: Optional[List[str]] = Field(
            None,
            description="If set, disallow requests to these hostnames (exact match).",
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
        self._handlers: List[SiteHandler] = []
        self._ensure_synced()
        # Register default handlers
        self.register_handler(WikipediaHandler())

    # ------------------------ Internal Utilities ------------------------

    def _valves_snapshot(self):
        v = self.valves
        return (
            v.user_agent,
            v.retries,
            v.timeout,
            v.min_summary_size,
            v.max_summary_size,
            v.max_body_bytes,
            v.concurrency,
            v.wiki_lang,
            v.allow_hosts,
            v.deny_hosts,
        )

    async def __aenter__(self):
        return self  # pragma: nocover

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()  # pragma: nocover

    async def close(self) -> None:
        """
        Close the underlying aiohttp session if open.

        Inputs: none
        Outputs: None
        """
        if self._session and not self._session.closed:
            await self._session.close()

    async def _emit(self, emitter: Any, event: Dict[str, Any]) -> None:
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
            except Exception:  # pragma: nocover
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

    def register_handler(self, handler: SiteHandler) -> None:
        """Register a custom site handler.

        Inputs:
        - handler: SiteHandler instance
        Outputs: None

        Example usage:
            tools = Tools()
            tools.register_handler(MyCustomHandler())
        """
        self._handlers.append(handler)

    def get_handler_for(self, url: str) -> Optional[SiteHandler]:
        """Find registered handler for a URL.

        Inputs:
        - url: target URL string
        Outputs: matching SiteHandler or None

        Example usage:
            handler = tools.get_handler_for("https://en.wikipedia.org/wiki/Python")
            if handler:
                result = await handler.handle(tools, url)
        """
        for handler in self._handlers:
            if handler.can_handle(url):
                return handler
        return None

    # ------------------------ Helpers and Aliases ------------------------
    ## Wikipedia
    async def wikipedia(
        self,
        pages: Optional[List[str]] = None,
        page: Optional[str] = None,
        url: Optional[str] = None,
        urls: Optional[List[str]] = None,
        return_raw: bool = True,
        emitter=None,
    ) -> str:
        """Retrieve multiple pages from Wikipedia via the extracts API.

        Inputs:
        - pages/page: titles or page URLs; URLs are normalized to titles
        - url/urls: alternative URL inputs
        - return_raw: True to get raw API JSON; False to summarize API response
        - emitter: optional event sink

        Output: concatenated string of results

        Example usage:
            tools = Tools()
            content = await tools.wikipedia(pages=["Python", "Ruby"], return_raw=False)
        """
        pages_list = list(pages or [])
        if page:
            pages_list.append(page)
        if url:
            pages_list.append(url)
        if urls:
            pages_list.extend(urls)

        # Get Wikipedia handler from registry
        handler = None
        for h in self._handlers:
            if isinstance(h, WikipediaHandler):
                handler = h
                break
        if not handler:
            raise RuntimeError("WikipediaHandler not registered")

        return await handler.fetch_pages(
            self, pages_list, return_html=return_raw, emitter=emitter
        )

    wikipedia_multi = wikipedia
    wikipedia_pages = wikipedia
    wikipedia_page = wikipedia
    get_wiki = wikipedia

    # ------------------------ Helpers and Aliases------------------------
    ## Summarize
    async def summarize(
        self, urls: Optional[List[str]] = None, url: Optional[str] = None, emitter=None
    ):
        """
        Fetch and return plaintext summary for one or more URLs.

        Inputs:
        - urls/url: one or many URLs to fetch
        - emitter: optional event sink
        Output: concatenated plaintext summaries
        """
        return await self.scrape(urls or [], url=url, return_raw=False, emitter=emitter)

    get_summary = summarize
    overview = summarize

    # ------------------------ Main Scrape Logic ------------------------

    async def scrape(
        self,
        urls: Optional[List[str]] = None,
        url: Optional[str] = None,
        return_raw: bool = True,
        emitter=None,
        redirect: bool = True,
        return_structured: bool = False,
    ) -> str:
        """Fetch content and optionally convert HTML to plaintext.

        Inputs:
        - urls/url: one or many URLs
        - return_raw: True returns raw body; False returns plaintext summary
        - emitter: optional event sink receiving lifecycle events
        - redirect: if True, Wikipedia URLs are routed to the API helper

        Output: concatenated str of page results
        """
        items = list(urls or [])
        if url:
            items.append(url)

        # Validate allow/block lists
        allow = self.valves.allow_hosts
        deny = self.valves.deny_hosts
        if allow or deny:
            for page in items:
                parsed = urllib.parse.urlparse(page)
                host = parsed.hostname
                if not parsed.scheme or not parsed.netloc:
                    raise ValueError(f"Invalid URL: {page}")
                # allowlist takes precedence over blocklist
                if allow:
                    if host not in allow:
                        raise ValueError(f"Host not allowed: {page}")
                    # host in allow: permitted regardless of deny
                    continue
                if deny and host in deny:
                    raise ValueError(f"Host blocked: {page}")

        sem = asyncio.Semaphore(max(1, int(self.valves.concurrency) or 1))

        async def process(page: str):
            async with sem:
                if emitter:
                    await self._emit(emitter, {"type": "start", "url": page})
                if redirect and ("wikipedia" in page and "api" not in page):
                    # Use handler for Wikipedia URLs
                    handler = self.get_handler_for(page)
                    if handler and isinstance(handler, WikipediaHandler):
                        ret = await handler.handle(
                            self, page, return_html=return_raw, emitter=emitter
                        )
                    else:
                        ret = await self._scrape(
                            url=page, return_raw=return_raw, emitter=emitter
                        )
                else:
                    ret = await self._scrape(
                        url=page, return_raw=return_raw, emitter=emitter
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
        if len(results) == 1:
            return results[0]
        return "\n\n".join(map(str, results))

    async def _scrape(
        self, url: str, return_raw: bool = True, emitter=None, redirect=True
    ) -> str:
        """
        Low-level fetch + transform for a single URL.

        Inputs:
        - url: target URL
        - return_raw: passthrough raw response when True; else plaintext summary
        - emitter: optional callback for progress events
        Outputs: str
        """
        if url is None:
            raise ValueError("URL cannot be None")

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
                        max_bytes: int = int(self.valves.max_body_bytes)
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
                        return text, ctype
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
            # Wikipedia page
            html = re.sub(r".*Contents.move to sidebar.hide", "", html, flags=flags)
            # Scripts and headers
            html = re.sub(r"<head>.*</head>", "", html, flags=flags)
            html = re.sub(r"<script>.*</script>", "", html, flags=flags)
            return html

        def _get_all_content(html) -> str:
            return html2text.html2text(_clean_html(html))

        # / Helpers

        ####################################
        # --- Actual work for scrape() --- #
        ####################################

        self._ensure_synced()

        try:
            page_data, content_type = await _fetch(self, url, emitter=emitter)
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
            json_obj = json.loads(page_data)
            if emitter:
                await self._emit(
                    emitter,
                    {"type": "found json", "url": url},
                )
            if not return_raw:
                # Return parsed JSON when plaintext is requested
                return json_obj
            # Otherwise return_raw = True means return as-is
        except (json.JSONDecodeError, ValueError):
            pass

        # Simple XML check via header
        try:
            xml_pattern = r"^\s*<\?xml\s"
            xml_elem = (
                ET.fromstring(page_data) if re.match(xml_pattern, page_data) else None
            )
            if xml_elem is not None:
                if not return_raw:
                    # Return parsed XML element when plaintext is requested
                    return xml_elem
                    # Otherwise return_raw = True means return as-is
        except Exception as e:  # pragma: no cover
            pass

        min_size_check = int(self.valves.min_summary_size) or 0
        if min_size_check and len(page_data) <= min_size_check:
            return_raw = True

        if emitter:
            await self._emit(emitter, {"type": "done", "url": url})

        content = _get_all_content(page_data)

        # Add header to identify which url this was.
        page_data_with_header = "\n".join([f"Contents of url: {url}", page_data])
        content_with_header = (
            "\n".join([f"Contents of url: {url}", content, "\n"])
            if content and content.strip()
            else ""
        )

        if return_raw:
            return page_data_with_header

        max_size_check = int(self.valves.max_summary_size) or 0
        if max_size_check and len(content) >= max_size_check:
            content = content[:max_size_check]
            content_with_header = "\n".join([f"Contents of url: {url}", content])

        if content and content.strip():
            return content_with_header

        # If no content extracted, return the raw page_data with header
        return page_data_with_header

    get = scrape
    fetch = scrape
    pull = scrape
    download = scrape
    html = scrape


