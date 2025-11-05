import os
import sys
import subprocess
import importlib
import pytest


def run_py(code: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Ensure project root is importable
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )


@pytest.mark.asyncio
async def test_async_context_manager_calls_close(monkeypatch):
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    called = {"closed": False}

    async def fake_close(self):
        called["closed"] = True

    monkeypatch.setattr(main_mod.Tools, "close", fake_close, raising=True)

    async with main_mod.Tools() as t:
        assert isinstance(t, main_mod.Tools)
    assert called["closed"] is True


def test_fallback_html2text_inprocess(tmp_path, monkeypatch):
    import importlib.util, types, sys, os

    # Remove any existing html2text so ImportError triggers
    sys.modules.pop("html2text", None)
    # Provide a minimal lxml with etree.HTML(...).xpath returning list of strings
    lxml = types.ModuleType("lxml")

    class DummyEtree:
        @staticmethod
        def HTML(b):
            class Node:
                def __init__(self, b):
                    self.b = b

                def xpath(self, expr):
                    return ["Hello"]

            return Node(b)

    lxml.etree = DummyEtree
    sys.modules["lxml"] = lxml
    # Import main.py under an alternate name to re-execute module code
    main_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "main.py")
    )
    spec = importlib.util.spec_from_file_location("main_fallback", main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.html2text.html2text("<html><body>Hello</body></html>") == "Hello"


def test_fake_useragent_inprocess(monkeypatch):
    import importlib.util, types, sys, os

    # Provide a stub html2text so the first import succeeds (avoid lxml dependency)
    ht = types.ModuleType("html2text")
    ht.html2text = lambda s: s
    sys.modules["html2text"] = ht
    # Provide fake_useragent.UserAgent that returns a sentinel UA
    fua = types.ModuleType("fake_useragent")

    class UserAgent:
        def random(self):
            return "FAKE-UA-123"

    fua.UserAgent = UserAgent
    sys.modules["fake_useragent"] = fua
    # Import main.py under an alternate name to re-execute module code
    main_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "main.py")
    )
    spec = importlib.util.spec_from_file_location("main_fua", main_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.USER_AGENT == "FAKE-UA-123"
