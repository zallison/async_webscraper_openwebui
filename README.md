### About

Scrape a web page using requests, and get either the html or a summary using html2text or lxml.  With support for wikipedia api, pages for wikipedia will be auto-rerouted to the API for much better results. Can scrape multiple urls.

Data of type XML or JSON will be parsed and returned as Python data structures (JSON -> dict/list; XML -> xml.etree.ElementTree.Element).

**Site Handlers**: The library now supports custom domain-specific handlers via the `SiteHandler` base class. Wikipedia and GitHub are implemented as handlers that use their respective APIs. You can register custom handlers for other sites. Public APIs remain unchanged.

**GitHub Handler**: Automatically redirects GitHub repository URLs to the GitHub REST API. Supports branches, tags, commits, subscribers, stargazers, and more. Always returns API responses as strings (JSON with "Contents of url:" header). Set `valves.github_token` for authenticated requests.

-----
## Features:
- Runs locally
- Uses standard, well known libraries
- Detects JSON and XML and returns it directly
- No API keys or subscriptions.
- No other services required
- Plenty of aliases to help even dumb models find the tools
- GitHub API integration for repository data
- Best of all: it actually works!


-----
## Example:

- scrape https://www.reddit.com/r/openwebui.rss and explain the results
- fetch the page at https://webscraper.io/test-sites/e-commerce/allinone and explain the html structure
- explain the contents of https://www.cs.utexas.edu/~mitra/csFall2010/cs329/lectures/xml/xslplanes.1.xml.txt
- https://openwebui.com/robots.txt is scraping allowed?
- get https://www.web-scraping.dev/product/2 and give me a summary
- get the wikipedia page for "Beer" and explain it to me
- scrape https://github.com/zallison/foghorn and show me the repository info
- fetch https://github.com/torvalds/linux/tree/master and show me the branch details

-----
### New in **v.0.2.2**:
- Bug fix for wikipedia handling.
- more test covering 99%

### New in **v.0.2.1**:
- Bug fix
- Better defaults set for valves

### New in **v.0.2.0**:
- Big overhaul
- All public APIs remain unchanged
- Introduced SiteHandler base class for custom domain-specific processing
- Migrated Wikipedia logic into WikipediaHandler
- Fixed Wikipedia URL redirect bug in scrape()

------
## Valves:

- user_agent: The agent to pretend to be.
- retries: Number of times to attempt the scrape
- min_summary_size: the minimum size of a page before a summary is allowed.
- concurrency: max parallel fetches for multi-URL scraping.
- allow_hosts: when set without deny_hosts, only these exact hostnames are allowed (strict allowlist).
- deny_hosts: exact hostnames to block. If both allow_hosts and deny_hosts are set, allow_hosts entries override denies; other hosts are permitted unless listed in deny_hosts.
- wiki_lang: language code for Wikipedia API (e.g., 'en', 'de').
- github_token: GitHub API token for authenticated requests (optional). When set, adds Bearer token to all requests.
- max_body_bytes: truncate large bodies to this many bytes.
-------

## Fine Tuning
```
You have the async_webscraper/scrape tool.
It allows you to retrieve either the html or an auto-generated summary.
The summary is much shorter and useful for quick overviews, the html is longer and better for deeper dives.

The Rules:

- Do not make anything up if the scrape fails.
- When calling this tools make sure to send only properly formatted complete urls.
- As we’re only making a single request per user input, the standards of robots.txt allow us to fetch from every site that doesn’t explicitly disallow it.

```

------

## GitHub Handler

GitHub repository URLs are automatically redirected to the GitHub REST API:

```python
from main import Tools
import asyncio

async def main():
    t = Tools()

    # Base repo info
    result = await t.scrape(url="https://github.com/zallison/foghorn", redirect=True)
    print(result)  # JSON string with repo metadata

    # Branch info (tree/{branch} maps to branches/{branch})
    result = await t.scrape(url="https://github.com/torvalds/linux/tree/master", redirect=True)
    print(result)  # JSON string with branch details

    # List all branches
    result = await t.scrape(url="https://github.com/zallison/foghorn/branches", redirect=True)
    print(result)  # JSON array of branches

    # Authenticated requests (higher rate limits)
    t.valves.github_token = "ghp_your_token_here"
    result = await t.scrape(url="https://github.com/zallison/foghorn", redirect=True)

    await t.close()

asyncio.run(main())
```

**Supported GitHub endpoints:**

*Users and Organizations:*
- User/org profile: `/{user}` → `api.github.com/users/{user}`

*Repository Info:*
- Base repository: `/{owner}/{repo}` → `api.github.com/repos/{owner}/{repo}`
- Contributors: `/{owner}/{repo}/contributors` → `api.github.com/repos/{owner}/{repo}/contributors`
- Languages: `/{owner}/{repo}/languages` → `api.github.com/repos/{owner}/{repo}/languages`
- Topics: `/{owner}/{repo}/topics` → `api.github.com/repos/{owner}/{repo}/topics`
- License: `/{owner}/{repo}/license` → `api.github.com/repos/{owner}/{repo}/license`
- README: `/{owner}/{repo}/readme` → `api.github.com/repos/{owner}/{repo}/readme`

*Branches and Code:*
- Branches list: `/{owner}/{repo}/branches` → `api.github.com/repos/{owner}/{repo}/branches`
- Specific branch: `/{owner}/{repo}/tree/{branch}` → `api.github.com/repos/{owner}/{repo}/branches/{branch}`
- File/directory: `/{owner}/{repo}/blob/{branch}/{path}` → `api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}`
- Contents: `/{owner}/{repo}/contents[/{path}]` → `api.github.com/repos/{owner}/{repo}/contents[/{path}]`

*Commits and Tags:*
- Commits list: `/{owner}/{repo}/commits` → `api.github.com/repos/{owner}/{repo}/commits`
- Specific commit: `/{owner}/{repo}/commit/{sha}` → `api.github.com/repos/{owner}/{repo}/commits/{sha}`
- Tags: `/{owner}/{repo}/tags` → `api.github.com/repos/{owner}/{repo}/tags`
- Compare: `/{owner}/{repo}/compare/{base}...{head}` → `api.github.com/repos/{owner}/{repo}/compare/{base}...{head}`

*Issues and Pull Requests:*
- Issues list: `/{owner}/{repo}/issues` → `api.github.com/repos/{owner}/{repo}/issues`
- Specific issue: `/{owner}/{repo}/issues/{number}` → `api.github.com/repos/{owner}/{repo}/issues/{number}`
- Pull requests: `/{owner}/{repo}/pulls` → `api.github.com/repos/{owner}/{repo}/pulls`
- Specific PR: `/{owner}/{repo}/pull/{number}` → `api.github.com/repos/{owner}/{repo}/pulls/{number}`
- Milestones: `/{owner}/{repo}/milestones[/{number}]` → `api.github.com/repos/{owner}/{repo}/milestones[/{number}]`

*Releases and Downloads:*
- Releases: `/{owner}/{repo}/releases` → `api.github.com/repos/{owner}/{repo}/releases`
- Latest release: `/{owner}/{repo}/releases/latest` → `api.github.com/repos/{owner}/{repo}/releases/latest`
- Release by tag: `/{owner}/{repo}/releases/tag/{tag}` → `api.github.com/repos/{owner}/{repo}/releases/tags/{tag}`
- Archive: `/{owner}/{repo}/archive/{ref}` → `api.github.com/repos/{owner}/{repo}/tarball/{ref}`

*Social:*
- Stargazers: `/{owner}/{repo}/stargazers` → `api.github.com/repos/{owner}/{repo}/stargazers`
- Subscribers (watchers): `/{owner}/{repo}/subscribers` → `api.github.com/repos/{owner}/{repo}/subscribers`

*Actions and Automation:*
- Workflows: `/{owner}/{repo}/actions/workflows[/{id}]` → `api.github.com/repos/{owner}/{repo}/actions/workflows[/{id}]`
- Runs: `/{owner}/{repo}/actions/runs[/{id}]` → `api.github.com/repos/{owner}/{repo}/actions/runs[/{id}]`

*Projects and Security:*
- Projects: `/{owner}/{repo}/projects[/{id}]` → `api.github.com/repos/{owner}/{repo}/projects[/{id}]`
- Security advisories: `/{owner}/{repo}/security/advisories` → `api.github.com/repos/{owner}/{repo}/security-advisories`

*Fallback:* Unrecognized paths fall back to the base repository endpoint.

------

## Custom Site Handlers

You can create custom handlers for specific domains:

```python
from main import Tools, SiteHandler

class MyHandler(SiteHandler):
    name = "mysite"
    domains = (".example.com",)

    async def handle(self, tools, url, return_html=None):
        # Custom processing for example.com
        return "custom result"

tools = Tools()
tools.register_handler(MyHandler())

# Will use MyHandler for example.com URLs
result = await tools.scrape("https://www.example.com/page")
```

------


Feedback more than welcome.
author: openwebui@zackallison.com
