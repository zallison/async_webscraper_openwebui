import asyncio
import importlib
import json
import pytest

from conftest import FakeSession


def with_fake_session(plan):
    import main as main_mod

    async def _fake_get_session(self):
        sess = FakeSession(plan)
        # mirror real behavior: cache on instance
        self._session = sess
        return sess

    main_mod = importlib.reload(importlib.import_module("main"))
    # Monkeypatch method directly on class
    main_mod.Tools._get_session = _fake_get_session
    return main_mod


@pytest.mark.asyncio
async def test_github_handler_can_handle():
    """Test GitHubHandler correctly identifies GitHub URLs."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    assert handler.can_handle("https://github.com/zallison/foghorn")
    assert handler.can_handle("https://api.github.com/repos/zallison/foghorn")
    assert not handler.can_handle("https://gitlab.com/user/project")
    assert not handler.can_handle("https://example.com/github")


@pytest.mark.asyncio
async def test_github_handler_parse_path():
    """Test GitHubHandler._parse_path extracts path segments."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # User/org page (single segment)
    segments, is_user = handler._parse_path("https://github.com/zallison")
    assert segments == ["zallison"]
    assert is_user is True

    # Basic repo
    segments, is_user = handler._parse_path("https://github.com/zallison/foghorn")
    assert segments == ["zallison", "foghorn"]
    assert is_user is False

    # With subresource
    segments, is_user = handler._parse_path(
        "https://github.com/zallison/foghorn/branches"
    )
    assert segments == ["zallison", "foghorn", "branches"]
    assert is_user is False

    # With nested subresource
    segments, is_user = handler._parse_path(
        "https://github.com/zallison/foghorn/tree/main"
    )
    assert segments == ["zallison", "foghorn", "tree", "main"]
    assert is_user is False

    # Invalid URL (empty path)
    with pytest.raises(ValueError):
        handler._parse_path("https://github.com/")


@pytest.mark.asyncio
async def test_github_handler_build_api_url_base():
    """Test GitHubHandler.build_api_url for base repository URL."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # Base repo URL
    api_url = handler.build_api_url("https://github.com/zallison/foghorn")
    assert api_url == "https://api.github.com/repos/zallison/foghorn"

    # Case preservation
    api_url = handler.build_api_url("https://github.com/zallison/Foghorn")
    assert api_url == "https://api.github.com/repos/zallison/Foghorn"


@pytest.mark.asyncio
async def test_github_handler_build_api_url_branches():
    """Test GitHubHandler.build_api_url for branches endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # Branches list
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/branches")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/branches"

    # Specific branch
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/branches/main"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/branches/main"

    # tree/{branch} -> branches/{branch} (template expansion)
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/tree/main")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/branches/main"

    # tree with feature/branch-name
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/tree/feature/test"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/branches/feature/test"
    )


@pytest.mark.asyncio
async def test_github_handler_build_api_url_subresources():
    """Test GitHubHandler.build_api_url for common subresources."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # Tags
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/tags")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/tags"

    # Commits
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/commits")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/commits"

    # Subscribers
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/subscribers")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/subscribers"

    # Stargazers
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/stargazers")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/stargazers"


@pytest.mark.asyncio
async def test_github_handler_build_api_url_fallback():
    """Test GitHubHandler.build_api_url fallback for unrecognized paths."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # Unknown subresource falls back to base repo
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/some/random/path"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn"


@pytest.mark.asyncio
async def test_github_handler_build_api_url_passthrough():
    """Test GitHubHandler.build_api_url passes through API URLs."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # API URL passthrough
    api_url = handler.build_api_url("https://api.github.com/repos/zallison/foghorn")
    assert api_url == "https://api.github.com/repos/zallison/foghorn"

    api_url = handler.build_api_url(
        "https://api.github.com/repos/zallison/foghorn/branches"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/branches"


@pytest.mark.asyncio
async def test_github_handler_handle_base_repo():
    """Test GitHubHandler.handle for base repository URL."""
    api_url = "https://api.github.com/repos/zallison/foghorn"
    plan = {
        api_url: [
            (
                200,
                json.dumps({"name": "foghorn", "owner": {"login": "zallison"}}),
                None,
            )
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.GitHubHandler()

    result = await handler.handle(t, "https://github.com/zallison/foghorn")
    assert isinstance(result, str)
    assert "foghorn" in result
    assert "Contents of url:" in result
    await t.close()


@pytest.mark.asyncio
async def test_github_handler_handle_branches():
    """Test GitHubHandler.handle for branches endpoint."""
    api_url = "https://api.github.com/repos/zallison/foghorn/branches"
    plan = {api_url: [(200, json.dumps([{"name": "main"}, {"name": "dev"}]), None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.GitHubHandler()

    result = await handler.handle(t, "https://github.com/zallison/foghorn/branches")
    assert isinstance(result, str)
    assert "main" in result
    assert "dev" in result
    await t.close()


@pytest.mark.asyncio
async def test_github_handler_handle_tree_expansion():
    """Test GitHubHandler.handle for tree/{branch} expansion."""
    api_url = "https://api.github.com/repos/zallison/foghorn/branches/main"
    plan = {
        api_url: [
            (
                200,
                json.dumps({"name": "main", "commit": {"sha": "abc123"}}),
                None,
            )
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.GitHubHandler()

    result = await handler.handle(t, "https://github.com/zallison/foghorn/tree/main")
    assert isinstance(result, str)
    assert "main" in result
    assert "abc123" in result
    await t.close()


@pytest.mark.asyncio
async def test_tools_scrape_with_github_redirect():
    """Test Tools.scrape with redirect=True routes GitHub URLs to handler."""
    api_url = "https://api.github.com/repos/zallison/foghorn"
    plan = {
        api_url: [
            (
                200,
                json.dumps({"name": "foghorn", "full_name": "zallison/foghorn"}),
                None,
            )
        ]
    }
    main = with_fake_session(plan)
    t = main.Tools()

    # With redirect=True (default), should use GitHubHandler
    result = await t.scrape(url="https://github.com/zallison/foghorn", redirect=True)
    assert isinstance(result, str)
    assert "foghorn" in result
    assert "Contents of url:" in result

    await t.close()


@pytest.mark.asyncio
async def test_tools_scrape_bypasses_github_handler_when_redirect_false():
    """Test Tools.scrape bypasses GitHubHandler when redirect=False."""
    web_url = "https://github.com/zallison/foghorn"
    plan = {
        web_url: [(200, "<html><body>Direct web fetch</body></html>", None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()

    # With redirect=False, should fetch web page directly
    result = await t.scrape(url=web_url, redirect=False)
    assert isinstance(result, str)
    assert "Direct web fetch" in result

    await t.close()


@pytest.mark.asyncio
async def test_tools_valves_github_token():
    """Test that Tools.Valves includes github_token field."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    t = main_mod.Tools()
    assert hasattr(t.valves, "github_token")
    assert t.valves.github_token is None

    # Set token
    t.valves.github_token = "ghp_test_token"
    assert t.valves.github_token == "ghp_test_token"


@pytest.mark.asyncio
async def test_github_handler_handle_api_url_passthrough():
    """Test GitHubHandler.handle passes through API URLs directly."""
    api_url = "https://api.github.com/repos/zallison/foghorn"
    plan = {api_url: [(200, json.dumps({"name": "foghorn"}), None)]}
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.GitHubHandler()

    # Pass API URL directly
    result = await handler.handle(t, api_url)
    assert isinstance(result, str)
    assert "foghorn" in result
    await t.close()


@pytest.mark.asyncio
async def test_github_handler_stateless():
    """Test GitHubHandler is stateless across multiple requests."""
    api_url1 = "https://api.github.com/repos/user1/repo1"
    api_url2 = "https://api.github.com/repos/user2/repo2"
    plan = {
        api_url1: [(200, json.dumps({"name": "repo1"}), None)],
        api_url2: [(200, json.dumps({"name": "repo2"}), None)],
    }
    main = with_fake_session(plan)
    t = main.Tools()
    handler = main.GitHubHandler()

    result1 = await handler.handle(t, "https://github.com/user1/repo1")
    result2 = await handler.handle(t, "https://github.com/user2/repo2")

    assert "repo1" in result1
    assert "repo2" in result2
    assert "repo1" not in result2  # No data leakage
    await t.close()


@pytest.mark.asyncio
async def test_github_handler_user_url():
    """Test GitHubHandler handles user/org pages."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))

    handler = main_mod.GitHubHandler()

    # User page
    api_url = handler.build_api_url("https://github.com/zallison")
    assert api_url == "https://api.github.com/users/zallison"

    # Org page
    api_url = handler.build_api_url("https://github.com/microsoft")
    assert api_url == "https://api.github.com/users/microsoft"


@pytest.mark.asyncio
async def test_github_handler_issues():
    """Test GitHubHandler handles issues endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Issues list
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/issues")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/issues"

    # Specific issue
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/issues/42")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/issues/42"


@pytest.mark.asyncio
async def test_github_handler_pulls():
    """Test GitHubHandler handles pull request endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # PRs list
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/pulls")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/pulls"

    # Specific PR (pull or pulls both work)
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/pull/123")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/pulls/123"


@pytest.mark.asyncio
async def test_github_handler_releases():
    """Test GitHubHandler handles releases endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Releases list
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/releases")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/releases"

    # Latest release
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/releases/latest"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/releases/latest"

    # Release by tag
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/releases/tag/v1.0.0"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/releases/tags/v1.0.0"
    )


@pytest.mark.asyncio
async def test_github_handler_commits_with_sha():
    """Test GitHubHandler handles commits with SHA."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Commits list
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/commits")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/commits"

    # Specific commit
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/commit/abc123"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/commits/abc123"


@pytest.mark.asyncio
async def test_github_handler_blob_to_contents():
    """Test GitHubHandler maps blob/{branch}/{path} to contents."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # File on specific branch
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/blob/main/README.md"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/contents/README.md?ref=main"
    )

    # Nested file path
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/blob/dev/src/main.py"
    )
    assert (
        api_url
        == "https://api.github.com/repos/zallison/foghorn/contents/src/main.py?ref=dev"
    )


@pytest.mark.asyncio
async def test_github_handler_repo_metadata():
    """Test GitHubHandler handles repo metadata endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Contributors
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/contributors"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/contributors"

    # Languages
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/languages")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/languages"

    # Topics
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/topics")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/topics"

    # License
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/license")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/license"

    # README
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/readme")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/readme"


@pytest.mark.asyncio
async def test_github_handler_actions():
    """Test GitHubHandler handles GitHub Actions endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Workflows list
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/actions/workflows"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/actions/workflows"
    )

    # Specific workflow
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/actions/workflows/ci.yml"
    )
    assert (
        api_url
        == "https://api.github.com/repos/zallison/foghorn/actions/workflows/ci.yml"
    )

    # Runs list
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/actions/runs"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/actions/runs"

    # Specific run
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/actions/runs/12345"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/actions/runs/12345"
    )


@pytest.mark.asyncio
async def test_github_handler_milestones():
    """Test GitHubHandler handles milestones."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Milestones list
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/milestones"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/milestones"

    # Specific milestone
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/milestones/7"
    )
    assert api_url == "https://api.github.com/repos/zallison/foghorn/milestones/7"


@pytest.mark.asyncio
async def test_github_handler_compare():
    """Test GitHubHandler handles compare endpoint."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Compare branches/commits
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/compare/main...dev"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/compare/main...dev"
    )


@pytest.mark.asyncio
async def test_github_handler_archive():
    """Test GitHubHandler handles archive/tarball endpoints."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Tarball download
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/archive/main")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/tarball/main"


@pytest.mark.asyncio
async def test_github_handler_contents():
    """Test GitHubHandler handles contents endpoint."""
    import main as main_mod

    main_mod = importlib.reload(importlib.import_module("main"))
    handler = main_mod.GitHubHandler()

    # Root contents
    api_url = handler.build_api_url("https://github.com/zallison/foghorn/contents")
    assert api_url == "https://api.github.com/repos/zallison/foghorn/contents"

    # Specific path
    api_url = handler.build_api_url(
        "https://github.com/zallison/foghorn/contents/src/lib.py"
    )
    assert (
        api_url == "https://api.github.com/repos/zallison/foghorn/contents/src/lib.py"
    )
