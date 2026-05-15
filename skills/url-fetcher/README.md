# URL Fetcher

Read and extract clean text from any webpage URL.

## What it does

Adds a `fetch_url` tool that downloads a page and uses [Trafilatura](https://trafilatura.readthedocs.io/) to strip navigation, ads, and boilerplate — returning just the main article content.

## Requirements

- `trafilatura` Python package (included in sidecar dependencies).

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `max_chars` | `8000` | Maximum characters to return per page. |

## Example

> **User:** Summarize this article: https://news.example.com/article  
> **Assistant:** *(calls `fetch_url("https://news.example.com/article")`)* The article discusses…

## Notes

- Works best on news articles, blogs, and documentation pages.
- JavaScript-heavy single-page apps (SPAs) may return limited content.
