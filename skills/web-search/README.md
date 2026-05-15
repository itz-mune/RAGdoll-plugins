# Web Search

Search the web from inside RAGdoll using DuckDuckGo — no API key required.

## What it does

Adds a `web_search` tool that the LLM can call whenever it needs up-to-date information. Results include the page title, URL, and a short snippet.

## Requirements

- `duckduckgo-search` Python package (included in RAGdoll's sidecar dependencies).

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `max_results` | `5` | Number of results returned per query. |

## Example

> **User:** What happened in tech news today?  
> **Assistant:** *(calls `web_search("tech news today")*)* …

## Notes

- DuckDuckGo does not require an API key but rate-limits aggressive usage.
- Works best with models that have strong tool-use capabilities (GPT-4o, Claude 3.5+, Gemini 1.5+).
