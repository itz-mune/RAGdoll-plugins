# Image Search

Search for freely-licensed images and return direct URLs — no API key required by default. Integrates automatically with the File R/W skill when creating rich documents.

## Requirements

- **RAGdoll ≥ 0.3.0**
- **ddgs** package (pre-installed with RAGdoll — used by the default DuckDuckGo provider)

## Providers

| Provider | API Key | Quality | Notes |
|----------|---------|---------|-------|
| **DuckDuckGo** *(default)* | None | Good | Works out of the box via `ddgs` |
| **Unsplash** | Free | Excellent | High-resolution curated photography |
| **Pexels** | Free | Excellent | Large library, consistent quality |
| **Pixabay** | Free | Good | Photos, illustrations, and vector art |

Switch providers and enter API keys in the plugin settings drawer. Only the key for the active provider is shown.

## Getting API keys

All keys are free with a standard account signup:

- **Unsplash** — [unsplash.com/developers](https://unsplash.com/developers)
- **Pexels** — [pexels.com/api](https://www.pexels.com/api/)
- **Pixabay** — [pixabay.com/api/docs](https://pixabay.com/api/docs/)

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Image provider | `duckduckgo` | Active search backend |
| Max results | `3` | Images returned per query (1–10) |
| Unsplash Access Key | — | Shown only when provider = Unsplash |
| Pexels API Key | — | Shown only when provider = Pexels |
| Pixabay API Key | — | Shown only when provider = Pixabay |

## Tool

### `search_images(query, count?)`

Returns a JSON array of image objects:

```json
[
  {
    "url":    "https://...",
    "title":  "Mountain landscape at sunrise",
    "source": "pexels.com",
    "width":  4000,
    "height": 2667
  }
]
```

**When this tool fires:**
- User explicitly asks to find, retrieve, or include images
- The `file_rw` skill is creating a `.docx`, `.pdf`, or `.html` document and needs image URLs to embed

**When it does NOT fire:**
- General web searches — use `web_search` for those

## File R/W integration

When the File R/W skill creates a rich document, it calls `search_images` first to get relevant image URLs, then embeds them using Markdown image syntax:

```
![Mount Everest at dawn|right](https://...)
```

The `|right` alignment hint is optional — see the [File R/W README](../file-rw/README.md#document-creation-docx--pdf--html) for the full placement syntax.

## Example prompts

```
Find me 5 photos of the Aurora Borealis
Search for an image of Albert Einstein
Create a PDF report on climate change with relevant images
Write a travel guide for Japan as a Word document — include photos
```
