# main.py
import asyncio
import time
from typing import Optional, Dict, Any

import aiohttp
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


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


class Tools:
    class Valves(BaseModel):
        model_config = {"arbitrary_types_allowed": True}

        user_agent: str = Field(
            DEFAULT_USER_AGENT,
            description="User-Agent header to use for HTTP requests.",
        )
        use_advanced_main: bool = Field(
            False, description="If true, use advanced main-content extractor."
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

    def _valves_snapshot(self):
        v = self.valves
        return (v.user_agent, v.use_advanced_main, v.retries, v.cache_ttl, v.timeout)

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

        headers = {
            "User-Agent": str(self.valves.user_agent),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def _fetch(self, url: str, emitter=None) -> str:
        sess = await self._get_session()
        retries = max(0, int(self.valves.retries))
        backoff_base = 0.5
        last_exc = None

        for attempt in range(1, retries + 1):
            if emitter:
                await self._emit(
                    emitter, {"type": "fetch_attempt", "attempt": attempt, "url": url}
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

    async def run(self, input: Dict[str, Any], emitter=None) -> Dict[str, Any]:
        self._ensure_synced()
        url = input.get("url") if isinstance(input, dict) else None
        if not url:
            raise ValueError("Input must be a dict with a 'url' key.")

        cached = await self._cache.get(url)
        if cached:
            if emitter:
                await self._emit(emitter, {"type": "cache_hit", "url": url})
            return {**cached, "cached": True}

        if emitter:
            await self._emit(emitter, {"type": "start", "url": url})

        html = await self._fetch(url, emitter=emitter)

        if emitter:
            await self._emit(emitter, {"type": "parsing", "url": url})

        soup = BeautifulSoup(html, "html.parser")

        if emitter:
            await self._emit(emitter, {"type": "extract_title", "url": url})
        title = self.get_title(soup)

        if emitter:
            await self._emit(emitter, {"type": "extract_main_content", "url": url})
        main_content = (
            self.extract_advanced_main_content(soup)
            if self.valves.use_advanced_main
            else self.get_main_content(soup)
        )

        if emitter:
            await self._emit(emitter, {"type": "extract_all_content", "url": url})
        all_content = self.get_all_content(soup)

        if emitter:
            await self._emit(emitter, {"type": "cache_store", "url": url})

        await self._cache.set(
            url,
            {
                "title": title,
                "main_content": main_content,
                "all_content": all_content,
                "raw_html": html,
            },
        )

        if emitter:
            await self._emit(emitter, {"type": "done", "url": url})

        return {
            "title": title,
            "main_content": main_content,
            "all_content": all_content,
            "raw_html": html,
            "cached": False,
        }

    async def get_raw_html(self, url: str, emitter=None) -> str:
        """
        Fetch URL and return raw HTML, also emits progress events.
        """
        cached = await self._cache.get(url)
        if cached:
            if emitter:
                await self._emit(emitter, {"type": "cache_hit", "url": url})
            return cached.get("raw_html", "")

        html = await self._fetch(url, emitter=emitter)
        await self._cache.set(
            url, {"title": "", "main_content": "", "all_content": "", "raw_html": html}
        )
        return html

    # --- content helpers ---
    def get_title(self, soup) -> str:
        t = soup.find("title")
        return t.text.strip() if t and t.text else "No title found"

    def get_main_content(self, soup) -> str:
        main_tags = soup.find_all(["main", "article", "section", "div"])
        for tag in main_tags:
            text = tag.get_text(separator=" ", strip=True)
            if len(text) > 200:
                return text
        return self.get_all_content(soup)

    def extract_advanced_main_content(self, soup) -> str:
        for tag in soup(["nav", "footer", "aside", "script", "style", "noscript"]):
            tag.decompose()
        best_tag = None
        best_len = 0
        for tag in soup.find_all(["article", "div", "section"]):
            text = tag.get_text(separator=" ", strip=True)
            l = len(text)
            if l > best_len:
                best_tag = tag
                best_len = l
        if best_tag and best_len > 0:
            return best_tag.get_text(separator=" ", strip=True)
        return self.get_all_content(soup)

    def get_all_content(self, soup) -> str:
        for tag in soup(["script", "style"]):
            tag.decompose()
        return " ".join(soup.stripped_strings)

    # --- cache and session ---
    async def clear_cache(self) -> str:
        await self._cache.clear()
        return "Cache cleared"

    async def cache_info(self) -> Dict[str, Any]:
        return await self._cache.info()

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # --- emitter ---
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


# --- Simple emitter for testing ---
class SimpleEmitter:
    async def emit(self, event: Dict[str, Any]) -> None:
        print("[EVENT]", event)

