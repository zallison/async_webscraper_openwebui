import asyncio
import os
import re
import sys
import types
from typing import Callable, Dict, List, Tuple, Optional

# Ensure project root is on sys.path for `import main`
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure main.py can import html2text even if it's not installed
mod = types.ModuleType("html2text")
mod.html2text = lambda s: re.sub(r"<[^>]+>", "", s)  # naive strip tags for plaintext
sys.modules.setdefault("html2text", mod)


class FakeResponse:
    def __init__(
        self,
        url: str,
        status: int,
        text: str,
        raise_for_status_exc: Optional[Exception] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.url = url
        self.status = status
        self._text = text
        self._exc = raise_for_status_exc
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.history = []
        self.request_info = types.SimpleNamespace(real_url=url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self._exc:
            raise self._exc

    async def text(self):
        return self._text

    async def read(self):
        return self._text.encode("utf-8")


class FakeSession:
    def __init__(self, plan: Dict[str, List[Tuple[int, str, Optional[Exception]]]]):
        """plan: url -> list of (status, text, exc) per call."""
        self._plan = {k: list(v) for k, v in plan.items()}
        self.closed = False
        self.headers = {}
        self.seen_urls: List[str] = []

    async def close(self):
        self.closed = True

    def get(self, url: str, timeout: int = 10):
        self.seen_urls.append(url)
        steps = self._plan.get(url, None)
        if steps is None or len(steps) == 0:
            # default successful response
            return FakeResponse(url, 200, f"<html>OK for {url}</html>")
        status, body, exc = steps.pop(0)
        return FakeResponse(url, status, body, exc)


class Emitter:
    def __init__(self):
        self.events: List[dict] = []

    async def __call__(self, event: dict):
        self.events.append(event)

    async def emit(self, event: dict):
        self.events.append(event)
