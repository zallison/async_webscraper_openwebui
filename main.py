"""
Your LLM might need to be "fine tuned":

You have the async_webscraper/scrape tool.
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
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
import json
import re
try:
    import html2text
except ImportError as e:
    class html2text:
        def html2text(str):
            return str
DEF
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
    "Pragma": "no-cache"
}

try:
    from fake_useragent import UserAgent
    ua = UserAgent()
    HEADERS["user_agent"] = ua.random()
except ImportError as e:
    pass

class Tools:
    VERSION = "0.1.2"

    class Valves(BaseModel):
        model_config = {"arbitrary_types_allowed": True}

        user_agent: str = Field(
            DEFAULT_USER_AGENT,
            description="User-Agent header to use for HTTP requests.",
        )
        retries: int = Field(
            3, description="Number of retry attempts for HTTP requests."
        )
        cache_ttl: int = Field(
            300, description="TTL in seconds for the in-memory cache."
        )
        timeout: int = Field(10, description="Request timeout in seconds.")

    def __init__(self):
        self.valves = self.Valves()
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache = AsyncTTLCache(ttl=int(self.valves.cache_ttl))
        self._applied_snapshot = None
        self._ensure_synced()

    # ------------------------ Internal Utilities ------------------------

    def _valves_snapshot(self):
        v = self.valves
        return (v.user_agent, v.retries, v.cache_ttl, v.timeout)

    async def clear_cache(self) -> str:
        """Clear the LRU cache"""
        await self._cache.clear()
        return "Cache cleared"

    async def cache_info(self) -> Dict[str, Any]:
        """Return information about the cache"""
        return await self._cache.info()

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
        self._cache = AsyncTTLCache(ttl=int(self.valves.cache_ttl))
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

        headers = HEADERS.copy()
        if self.user_agent:
            headers["User-Agent"]=self.user_agent
        self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    # ------------------------ Main Scrape Logic ------------------------
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

    async def scrape(
        self, url: str, return_html: bool = False, emitter=None
    ) -> Dict[str, Any]:
        """
        Fetch, parse, and extract main page content
        use option: return_html = True to include the html for more detail.
        """

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

        def _get_title(soup, html) -> str:
            t = soup.find("title")
            return t

        def _get_main_content(soup, html) -> str:
            main_content = (
                soup.find("article")
                or soup.find("main")
                or soup.find("div", {"id": "content"})
                or soup.find("div", {"class": "post-content"})
            )
            if main_content:
                return main_content.get_text(separator=" ", strip=True)

            return html2text.html2text(html)

        def _get_all_content(soup, html) -> str:  # FIX: changed return type to str
            return html2text.html2text(html)

        def _extract_advanced_main_content(soup, html) -> str:
            for tag in soup(["nav", "footer", "aside", "script", "style", "noscript"]):
                tag.decompose()
            all_content = ""
            for tag in soup.find_all(["article", "div", "section"]):
                text = tag.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    all_content += text
            if all_content:
                return all_content
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

        cached = await self._cache.get(url)
        if cached:
            if emitter:
                await self._emit(emitter, {"type": "cache_hit", "url": url})
            # FIX: remove timestamp key before returning cached data
            cached_copy = {k: v for k, v in cached.items() if k != "timestamp"}
            return {**cached_copy, "cached": True}

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
            # We've found a json object.
            # TODO: Valve to cache this value. Default to yes for JSON or XML.
            await self._cache.set(url, json_obj)

            return json_obj
        except (json.JSONDecodeError, ValueError):
            pass

        xml_pattern = r"^\s*<\?xml\s"

        if re.match(xml_pattern, html):
            """We've found XML"""
            # TODO: Valve to cache this value. Default to yes for JSON or XML.
            return html

        soup = BeautifulSoup(html, "html.parser")
        if not soup or not html:
            raise Exception("no soup or html")

        title = _get_title(soup, html)

        main_content = (
            _extract_advanced_main_content(soup, html)
            if self.valves.use_advanced_main
            else _get_main_content(soup, html)
        )
        all_content = _get_all_content(soup, html)
        summary = _summarize(main_content)

        result = {
            "html": html,
            "all_content": all_content,
            "title": title,
            "main_content": main_content,
            "summary": summary,
            "cached": False,
        }
        cache_result = dict(result)
        if not return_html:
            result["html"] = "use scrape_url_include_html for html"

        await self._cache.set(url, cache_result)

        if emitter:
            await self._emit(emitter, {"result": result, "type": "done", "url": url})
        if not result:
            raise Exception("no results")
        return result


# ------------------------ Async Cache ------------------------


class AsyncTTLCache:
    def __init__(self, maxsize: int = 200, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            if time.time() - item["timestamp"] > self.ttl:
                del self._store[key]
                return None
            return item

    async def set(self, key: str, value: Dict[str, Any]) -> None:
        async with self._lock:
            if len(self._store) >= self.maxsize:
                oldest_key = min(
                    self._store.keys(), key=lambda k: self._store[k]["timestamp"]
                )
                del self._store[oldest_key]
            value["timestamp"] = time.time()
            self._store[key] = value

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def info(self) -> Dict[str, Any]:
        async with self._lock:
            return {"size": len(self._store), "ttl": self.ttl, "maxsize": self.maxsize}


# ------------------------ Example Emitter ------------------------


class SimpleEmitter:
    async def emit(self, event: Dict[str, Any]) -> None:
        print("[EVENT]", event)


# ------------------------ Example Usage ------------------------

if __name__ == "__main__":

    async def main():
        tools = Tools()
        emitter = SimpleEmitter()
        url = "https://example.com"
        result = await tools.scrape_url(url, emitter=emitter)
        print("\n=== SCRAPE RESULT ===")
        print(f"Title: {result['title']}")
        print(f"Summary: {result['summary']}")
        print(f"Main content snippet:\n{result['main_content'][:400]}...")

    asyncio.run(main())
