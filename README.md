## About

Scrape a web page using requests, and get either the html or a summary using html2text or lxml.

## Notes:
- Your model may not like "scrape" so try "fetch", "get", or others if blocked.
- Often blocked by "anti-scrape" mechanism.  (working on it)
- Try the "Fine Tuning" section for an example system instruction.

-----
### New in v0.1.2:
- removed beautiful soup dependencies
- made html2text optional, with a lxml fallback function
- Caching changed to built in lru_cache
- uses fake_useragent if available, falls back to a static string

### New in v0.1.1:
- Automatically detect JSON and XML data and return it without parsing

-----
## Features:
- Runs locally
- Uses standard, well known libraries
- Detects JSON and XML and returns it directly
- No API keys or subscriptions.
- No other services required
- Plenty of aliases to help even dumb models find the tools
- Best of all: it actually works!
- LRU Cache for holding each page so that repeated queries don't cause more network requests.
  Note: Depends on model and pipeline

-----
## Example:

- scrape https://www.reddit.com/.rss and explain the results
- fetch the page at https://webscraper.io/test-sites/e-commerce/allinone and explain the html structure
- explain the contents of https://www.cs.utexas.edu/~mitra/csFall2010/cs329/lectures/xml/xslplanes.1.xml.txt
- https://openwebui.com/robots.txt is scraping allowed?
- get https://www.web-scraping.dev/product/2 and give me a summary

------
## Valves:

- user_agent: The agent to pretend to be.
- retries: Number of times to attempt the scrape
- min_summary_size: the minimum size of a page before a summary is allowed. Set according to your model and context preferences.
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


Feedback more than welcome.
author: openwebui@zackallison.com

