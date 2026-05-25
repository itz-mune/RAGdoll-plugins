<div align="center">

# RAGdoll Plugins

**The official plugin registry for [RAGdoll](https://github.com/itz-mune/RAGdoll).**  
Add new skills, styles, and capabilities to your local AI without touching the core app.

[![RAGdoll](https://img.shields.io/badge/RAGdoll-%E2%89%A50.2.0-7c3aed?style=flat-square)](https://github.com/itz-mune/RAGdoll/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-7c3aed?style=flat-square)](LICENSE)

</div>

---

## Plugin types

| Type | What it does | Entry file |
|---|---|---|
| **Skill** | Adds a callable tool to the agent — web search, file operations, image search, etc. | `skill.py` |
| **Style** | Injects a system-prompt prefix that changes the agent's tone or persona | `style.json` |

---

## Available plugins

### Skills

| Plugin | Pre-installed | Description |
|---|---|---|
| 🔍 **Web Search** | ✅ | DuckDuckGo search — no API key needed |
| 📄 **File R/W** | ✅ | Read, write, diff, and create rich documents (DOCX / PDF / HTML) |
| 📁 **Universal File Access** | ✅ | Index and search files anywhere on disk |
| 🖼️ **Image Search** | ✅ | Freely-licensed images via DDG, Unsplash, Pexels, or Pixabay |
| 🧩 **Skill Finder** | ✅ | Auto-discovers and installs skills when the agent needs a missing capability |
| 🌐 **URL Fetcher** | ✅ | Extracts clean readable text from any webpage |
| ▶️ **YouTube Transcript** | ✅ | Pulls transcripts from any YouTube video |
| 🎨 **Image Gen (DALL-E)** | — | Generate images with OpenAI DALL-E 3 |
| 🌊 **Image Gen (Stability AI)** | — | Stable Diffusion via the Stability AI REST API |
| ⚙️ **Image Gen (ComfyUI)** | — | Generate images via a local ComfyUI server |

### Styles

| Plugin | Description |
|---|---|
| 🏴‍☠️ **Pirate Mode** | Arrr! Swashbuckling pirate persona |
| 🎭 **Shakespearean Mode** | Early Modern English — thou, thee, forsooth, and all |

---

## How the agent uses plugins

RAGdoll wraps all installed skills into LangGraph tool nodes. Here is the rough shape of the graph:

```
                    ┌─────────────────────────┐
                    │        __start__        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │       chat_agent        │  ← LLM decides which tool(s) to call
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │  tools_condition │                  │
              ▼                  ▼                  ▼
       (no tool call)     (tool call 1)      (tool call N)
              │                  │                  │
              │       ┌──────────▼──────────┐       │
              │       │     tools node      │       │
              │       │  ┌───────────────┐  │       │
              │       │  │  web_search   │  │       │
              │       │  │  search_images│  │       │
              │       │  │  file_read    │  │       │
              │       │  │  file_write   │  │       │
              │       │  │  …any skill…  │  │       │
              │       │  └───────────────┘  │       │
              │       └──────────┬──────────┘       │
              │                  │                  │
              └──────────────────▼──────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │        __end__          │
                    └─────────────────────────┘
```

Every installed **skill** becomes one tool in the tools node. The agent calls zero or more tools per turn, loops back through `chat_agent` to process results, and streams the final answer. **Styles** never appear in the graph — they prepend text to the system prompt before the first `chat_agent` call.

---

## Directory structure

```
RAGdoll-plugins/
├── registry.json            ← master plugin index (update this when adding/updating a plugin)
├── skills/
│   ├── web-search/
│   │   ├── manifest.json    ← plugin metadata and config field definitions
│   │   ├── skill.py         ← LangChain BaseTool subclass
│   │   ├── logo.png         ← 128×128 px icon shown in the marketplace
│   │   └── README.md        ← optional but encouraged
│   └── your-plugin/
│       └── …
└── styles/
    ├── shakespeare/
    │   ├── manifest.json
    │   ├── style.json       ← contains only { "system_prompt_prefix": "…" }
    │   └── logo.png
    └── your-style/
        └── …
```

---

## Contribution guidelines

### 1 — Fork and create your plugin folder

```
skills/your-plugin-id/   (for skills)
styles/your-style-id/    (for styles)
```

Use kebab-case. The folder name becomes the plugin's unique ID.

---

### 2 — `manifest.json` — required fields

Every plugin needs a `manifest.json`. Full schema:

```jsonc
{
  "id": "my-plugin",               // unique kebab-case ID — must match folder name
  "name": "My Plugin",             // display name shown in the marketplace
  "category": "skill",             // "skill" | "style"
  "author": "your-github-handle",
  "version": "1.0.0",              // semver — bump this on every update
  "description": "One-line summary shown in the marketplace card.",
  "icon": "🔧",                    // emoji shown next to the name
  "logo": "logo.png",              // 128×128 px, relative to this folder
  "entry": "skill.py",             // "skill.py" for skills, "style.json" for styles
  "min_ragdoll_version": "0.2.0",  // earliest RAGdoll release that supports this plugin
  "tags": ["tag1", "tag2"],        // used for search and filtering in the marketplace
  "preinstalled": false,           // true only for plugins bundled with RAGdoll itself
  "long_description": "Markdown-supported description shown on the detail page.",
  "changelog": {
    "1.0.0": "Initial release.",
    "1.1.0": "Added support for X."
  },
  "config_fields": [               // optional — see Config fields section below
    {
      "key": "api_key",
      "label": "API Key",
      "type": "password",
      "placeholder": "sk-…",
      "help": "Get your key at example.com/api"
    }
  ]
}
```

#### Config field types

| `type` | Renders as | Notes |
|---|---|---|
| `string` | Text input | |
| `password` | Masked input | Value stored encrypted |
| `number` | Numeric input | |
| `boolean` | Toggle switch | |
| `select` | Dropdown | Requires `"options": ["a", "b", "c"]` |
| `textarea` | Multi-line input | |

#### Conditional fields (`show_if`)

A field can be hidden unless another field has a specific value:

```jsonc
{
  "key": "api_key",
  "label": "API Key",
  "type": "password",
  "show_if": { "key": "provider", "value": "my-provider" }
}
```

The field only renders (and is only validated) when the `provider` setting equals `"my-provider"`. Useful for API key fields that only apply to one option in a select.

---

### 3 — `skill.py` — for skills only

Your skill must export a class that inherits from LangChain's `BaseTool`. RAGdoll imports it at runtime and registers it as a tool node in the agent graph.

```python
from langchain.tools import BaseTool
from pydantic import BaseModel, Field

class MyInput(BaseModel):
    query: str = Field(description="The thing to look up")

class MySkill(BaseTool):
    name: str = "my_tool"
    description: str = (
        "Use this tool when the user asks about X. "
        "Returns a JSON string with the results."
    )
    args_schema = MyInput

    # Config values injected by RAGdoll at install time
    api_key: str = ""
    max_results: int = 5

    def _run(self, query: str) -> str:
        # sync implementation
        ...

    async def _arun(self, query: str) -> str:
        # async implementation (preferred — keeps the sidecar non-blocking)
        ...
```

**Key rules:**
- Class name doesn't matter — RAGdoll discovers it by scanning for `BaseTool` subclasses.
- `name` must be unique across all installed skills (snake_case).
- `description` is what the LLM reads to decide when to call the tool — write it clearly and include trigger conditions.
- Config field keys in `manifest.json` are injected as class attributes. Always declare them with a default value.
- Use `async def _arun` whenever making network calls — synchronous blocking inside `_run` will stall the entire sidecar.

---

### 4 — `style.json` — for styles only

Styles are the simplest plugin type. The entire file is:

```json
{
  "system_prompt_prefix": "Your instruction text here."
}
```

This string is prepended to the system prompt **before every message** when the style is active. The LLM never sees it as a user message — it becomes part of its core instructions for that session.

**Example — Shakespearean Mode** (`styles/shakespeare/style.json`):

```json
{
  "system_prompt_prefix": "Thou shalt respond in the manner of William Shakespeare, employing Early Modern English throughout. Use 'thou', 'thee', 'thy', 'thine', 'doth', 'hath', 'forsooth', 'hark', 'prithee', 'methinks', 'verily', and other Elizabethan expressions. Structure responses with dramatic flair — as if delivering a soliloquy or addressing the Globe Theatre. All factual content must remain accurate; only the language and style change. Never break character, even when explaining technical topics."
}
```

**Tips for writing a good style prompt:**
- Be explicit about what changes (tone, vocabulary, format) and what must stay the same (accuracy, helpfulness).
- Add `Never break character` if you want it to hold even on dry technical questions.
- Keep it under ~200 tokens — it's prepended to every single message, so long prompts eat context budget fast.
- Avoid contradicting the user's explicit instructions — styles should enhance, not override.

---

### 5 — `registry.json` — how the marketplace detects updates

`registry.json` at the repo root is the **single source of truth** for the marketplace. RAGdoll polls it to discover new plugins and to notify users of updates. **You must update it whenever you add or update a plugin.**

```jsonc
{
  "version": "1",
  "updated_at": "2026-05-25",   // update this to today's date
  "plugins": [
    {
      "id": "my-plugin",
      "name": "My Plugin",
      "category": "skill",
      "author": "your-handle",
      "version": "1.1.0",       // must match manifest.json version exactly
      "description": "One-line summary.",
      "icon": "🔧",
      "logo": "logo.png",
      "entry": "skill.py",
      "path": "skills/my-plugin",
      "min_ragdoll_version": "0.2.0",
      "tags": ["tag1"],
      "preinstalled": false,
      "stars": 0,
      "downloads": 0
    }
  ]
}
```

**Update checklist — every plugin release:**

- [ ] Bump `version` in `manifest.json`
- [ ] Add an entry to `changelog` in `manifest.json`
- [ ] Bump the matching `version` in `registry.json` (must be identical)
- [ ] Update `updated_at` in `registry.json` to today's date
- [ ] Update `min_ragdoll_version` if you use a feature added in a newer RAGdoll release

RAGdoll compares the installed version against `registry.json`. If the registry version is higher, the marketplace shows an **Update available** badge and lets the user install the new version in one click.

---

### 6 — `logo.png`

- **128 × 128 px**, transparent or white background
- Shown in the marketplace card and the plugin settings drawer
- If omitted, a generic icon is shown — but please include one

---

### 7 — Open a pull request

1. Fork this repo
2. Create your plugin folder under `skills/` or `styles/`
3. Add your entry to `registry.json`
4. Open a PR — describe what the plugin does and any API keys / dependencies required
5. A maintainer will review and merge

> **Tip:** Check existing plugins (e.g. `skills/web-search`) as a reference before starting.

---

## License

[MIT](LICENSE)
