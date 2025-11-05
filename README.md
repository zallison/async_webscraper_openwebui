### About

Scrape a web page using requests, and get either the html or a summary using html2text or lxml.  With support for wikipedia api, pages for wikipedia will be auto-rerouted to the API for much better results. Can scrape multiple urls.

Data of type XML or JSON will be parsed and returned as Python data structures (JSON -> dict/list; XML -> xml.etree.ElementTree.Element).

**Site Handlers**: The library now supports custom domain-specific handlers via the `SiteHandler` base class. Wikipedia is implemented as a handler that uses the MediaWiki API. You can register custom handlers for other sites. Public APIs remain unchanged.

-----
## Features:
- Runs locally
- Uses standard, well known libraries
- Detects JSON and XML and returns it directly
- No API keys or subscriptions.
- No other services required
- Plenty of aliases to help even dumb models find the tools
- Best of all: it actually works!


-----
## Example:

- scrape https://www.reddit.com/r/openwebui.rss and explain the results
- fetch the page at https://webscraper.io/test-sites/e-commerce/allinone and explain the html structure
- explain the contents of https://www.cs.utexas.edu/~mitra/csFall2010/cs329/lectures/xml/xslplanes.1.xml.txt
- https://openwebui.com/robots.txt is scraping allowed?
- get https://www.web-scraping.dev/product/2 and give me a summary
- get the wikipedia page for "Beer" and explain it to me

-----
### New in **v.0.2.1**:
- Bug fix
- Better defaults set for valves

### New in **v.0.2.0**:
- Big overhaul
- All public APIs remain unchanged
- Introduced SiteHandler base class for custom domain-specific processing
- Migrated Wikipedia logic into WikipediaHandler
- Fixed Wikipedia URL redirect bug in scrape()

----
### New in v.0.1.4:
- Scrape function now allow for multiple urls to be given
- Bugfixes, better aliases

### New in v0.1.3:
- added wikipedia helpers
- auto-redirect to wiki api

### New in v0.1.2:
- removed beautiful soup dependencies
- made html2text optional, with a lxml fallback function
- Caching changed to built in lru_cache
- uses fake_useragent if available, falls back to a static string

### New in v0.1.1:
- Automatically detect JSON and XML data and return it without parsing

----
### Notes:
- Your model may not like "scrape" so try "fetch", "get", or others if blocked.
- Sometimes blocked by "anti-scrape" mechanism
- Try the "Fine Tuning" section for an example system instruction.


------
## Valves:

- user_agent: The agent to pretend to be.
- retries: Number of times to attempt the scrape
- min_summary_size: the minimum size of a page before a summary is allowed.
- concurrency: max parallel fetches for multi-URL scraping.
- allow_hosts: when set without deny_hosts, only these exact hostnames are allowed (strict allowlist).
- deny_hosts: exact hostnames to block. If both allow_hosts and deny_hosts are set, allow_hosts entries override denies; other hosts are permitted unless listed in deny_hosts.
- wiki_lang: language code for Wikipedia API (e.g., 'en', 'de').
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
