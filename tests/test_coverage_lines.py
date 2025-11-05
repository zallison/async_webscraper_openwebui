import sys
import importlib.util
import pathlib
import pytest

from tests.test_main import with_fake_session


@pytest.mark.asyncio
async def test_xml_detection_sets_return_raw_and_returns_original_html():
    xml_body = "<?xml version=\"1.0\"?><root><x>y</x></root>"
    plan = {"https://xml.test": [(200, xml_body, None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.min_summary_size = 0
    out = await t.summarize(url="https://xml.test")
    lines = out.split("\n")
    assert len(lines) >= 2
    assert lines[1].startswith("<?xml")
    await t.close()


def _make_blocking_finder(block_names):
    class BlockingFinder:
        def find_spec(self, fullname, path, target=None):
            if fullname in block_names:
                raise ImportError(f"blocked {fullname}")
            return None
    return BlockingFinder()


def test_fallback_html2text_branch_executes_and_handles_error():
    # Temporarily block html2text and lxml to force fallback path (lines 54-63)
    blocked = {"html2text", "lxml"}
    finder = _make_blocking_finder(blocked)
    prev_html2text = sys.modules.pop("html2text", None)
    prev_lxml = sys.modules.pop("lxml", None)
    sys.meta_path.insert(0, finder)
    try:
        src = pathlib.Path("main.py").resolve()
        spec = importlib.util.spec_from_file_location("main_no_deps", src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Call the fallback html2text implementation; it is intentionally naive/buggy
        with pytest.raises(Exception):
            mod.html2text.html2text("<html><head><script>a</script></head><body>b</body></html>")
    finally:
        # Cleanup: restore meta_path and prior modules
        if sys.meta_path and sys.meta_path[0] is finder:
            sys.meta_path.pop(0)
        if prev_html2text is not None:
            sys.modules["html2text"] = prev_html2text
        if prev_lxml is not None:
            sys.modules["lxml"] = prev_lxml


@pytest.mark.asyncio
async def test_max_return_size_caps_summary_length_via_adjusted_limit():
    long_text = "word " * 500
    body = f"<html><body>{long_text}</body></html>"
    plan = {"https://limit.test": [(200, body, None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    t.valves.min_summary_size = 0
    t.valves.max_summary_size = 1000
    t.valves.max_return_size = 120  # smaller than max_summary_size -> line 848 branch
    out = await t.summarize(url="https://limit.test")
    lines = out.split("\n", 1)
    content = lines[1] if len(lines) > 1 else ""
    assert len(content) <= 120
    await t.close()
