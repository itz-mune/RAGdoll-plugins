"""
Skill Finder — meta-skill that searches the RAGdoll marketplace and auto-installs
skills on demand.

Tools exposed:
  search_marketplace(query)  — find skills in the registry matching a description
  install_skill(plugin_id)   — download and install a skill by its registry ID

The agent should call search_marketplace first to identify the right plugin ID,
then call install_skill to install it.  After installation the agent must ask the
user to re-send their message so the newly-installed skill becomes active.
"""
import json
import re
import urllib.error
import urllib.request
from typing import Optional

SIDECAR_URL = "http://127.0.0.1:8765"

# ── Config helpers ────────────────────────────────────────────────────────────

def _get_plugins_config() -> dict:
    """
    Load the plugins section of ragdoll.config.json.
    Tries the sidecar's config module first (works when running inside the sidecar);
    falls back to a filesystem search.
    """
    try:
        from config import get_plugins_config
        return get_plugins_config()
    except ImportError:
        pass

    import os
    # Walk up from this file looking for ragdoll.config.json
    base = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(base, "ragdoll.config.json")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                return json.load(f).get("plugins", {})
        base = os.path.dirname(base)

    # Hard-coded fallback so the skill still works after distribution
    return {
        "registry_url": "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main/registry.json",
        "github_api_base": "https://api.github.com/repos/itz-mune/RAGdoll-plugins",
        "raw_base": "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main",
    }


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "RAGdoll-SkillFinder/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _post(url: str, payload: dict, timeout: int = 30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "RAGdoll-SkillFinder/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _score(plugin: dict, query: str) -> int:
    words = re.findall(r"\w+", query.lower())
    score = 0
    name = plugin.get("name", "").lower()
    desc = plugin.get("description", "").lower()
    tags = " ".join(plugin.get("tags", [])).lower()
    for word in words:
        if len(word) < 3:
            continue
        if word in name:
            score += 4
        if word in tags:
            score += 3
        if word in desc:
            score += 2
    return score


# ── Tool implementations ──────────────────────────────────────────────────────

def _search_marketplace(query: str) -> str:
    """
    Search the RAGdoll plugin marketplace for skills that match a query.
    Use this when the current toolset lacks a required capability — e.g. reading
    a particular file format, generating images, or fetching web content.

    Args:
        query: Natural-language description of the capability needed,
               e.g. "read Excel spreadsheet", "generate image from text", "parse CSV"
    """
    try:
        cfg = _get_plugins_config()
        registry_url = cfg.get(
            "registry_url",
            "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main/registry.json",
        )
        registry = _get(registry_url)
        all_plugins = [p for p in registry.get("plugins", []) if p.get("category") != "style"]

        # Fetch currently installed plugins so we can show status
        try:
            installed_data = _get(f"{SIDECAR_URL}/plugins")
            installed_ids = {p["id"] for p in installed_data.get("plugins", [])}
            enabled_ids = {p["id"] for p in installed_data.get("plugins", []) if p.get("is_enabled")}
        except Exception:
            installed_ids = set()
            enabled_ids = set()

        # Score and rank
        scored = sorted(
            [(p, _score(p, query)) for p in all_plugins if _score(p, query) > 0],
            key=lambda x: -x[1],
        )

        if not scored:
            names = ", ".join(f"`{p['id']}`" for p in all_plugins)
            return (
                f"No skills matched '{query}' in the marketplace.\n"
                f"All available skills: {names}"
            )

        lines = [f"Found {len(scored)} skill(s) matching **'{query}'**:\n"]
        for plugin, _ in scored[:6]:
            pid = plugin["id"]
            needs_key = bool(plugin.get("config_fields"))
            if pid in enabled_ids:
                status = "✅ installed & enabled"
            elif pid in installed_ids:
                status = "⚠️ installed but disabled"
            else:
                status = "📦 not installed"
            key_note = "  ⚠️ *Requires API key after install*" if needs_key else ""
            lines.append(
                f"• **{plugin['name']}** (id: `{pid}`) — {status}\n"
                f"  {plugin['description']}{key_note}"
            )

        lines.append(
            "\nTo install one of these, call `install_skill` with the exact plugin id."
        )
        return "\n".join(lines)

    except Exception as exc:
        return f"Error searching marketplace: {exc}"


def _install_skill(plugin_id: str) -> str:
    """
    Download and install a skill from the RAGdoll marketplace by its plugin ID.
    After a successful install, always tell the user to re-send their message so
    the new skill becomes active — it cannot be used within the same request.

    Args:
        plugin_id: Exact plugin ID from the marketplace, e.g. "image-viewer"
    """
    try:
        cfg = _get_plugins_config()
        registry_url = cfg.get(
            "registry_url",
            "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main/registry.json",
        )
        api_base = cfg.get(
            "github_api_base",
            "https://api.github.com/repos/itz-mune/RAGdoll-plugins",
        )
        raw_base = cfg.get(
            "raw_base",
            "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main",
        )

        # Find plugin in registry
        registry = _get(registry_url)
        plugin = next(
            (p for p in registry.get("plugins", []) if p["id"] == plugin_id), None
        )
        if not plugin:
            available = [p["id"] for p in registry.get("plugins", [])]
            return (
                f"Plugin `{plugin_id}` not found in the marketplace.\n"
                f"Available plugin IDs: {', '.join(available)}"
            )

        # Check if already installed
        try:
            installed_data = _get(f"{SIDECAR_URL}/plugins")
            installed = {p["id"] for p in installed_data.get("plugins", [])}
            if plugin_id in installed:
                return (
                    f"**{plugin['name']}** is already installed.\n"
                    f"If it's disabled, enable it from the Plugin Picker (🧩) in the chat bar."
                )
        except Exception:
            pass

        # Warn if API key is required
        needs_key = bool(plugin.get("config_fields"))
        key_warning = (
            "\n\n⚠️ **This skill requires an API key.** After installation, open the "
            "Marketplace → Installed tab and configure it before use."
            if needs_key else ""
        )

        # Fetch file list from GitHub Contents API
        file_list = _get(f"{api_base}/contents/{plugin['path']}")
        if not isinstance(file_list, list):
            return f"Could not list files for `{plugin_id}` (GitHub API error)."

        # Binary extensions to skip — we only need text files for the sidecar
        BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
                       ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4"}

        files = []
        for file_info in file_list:
            name = file_info.get("name", "")
            if not name:
                continue
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in BINARY_EXTS:
                continue  # Skip images / fonts — not needed for skill execution
            file_url = f"{raw_base}/{plugin['path']}/{name}"
            try:
                req = urllib.request.Request(
                    file_url, headers={"User-Agent": "RAGdoll-SkillFinder/1.0"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    content = resp.read().decode("utf-8", errors="replace")
                files.append({"path": name, "content": content})
            except Exception:
                pass  # Skip any file that fails to download

        if not files:
            return f"No downloadable files found for `{plugin_id}`."

        # POST to the sidecar install endpoint
        result = _post(f"{SIDECAR_URL}/plugins/install", {"id": plugin_id, "files": files})

        if result.get("success"):
            return (
                f"✅ **{plugin['name']}** has been installed and enabled successfully!{key_warning}\n\n"
                f"Please **send your message again** — the skill is now active and I'll use it automatically."
            )
        else:
            return f"Installation failed: {result.get('error', 'unknown error')}"

    except Exception as exc:
        return f"Error installing `{plugin_id}`: {exc}"


# ── Register ──────────────────────────────────────────────────────────────────

def register():
    from langchain_core.tools import tool

    search_marketplace = tool(_search_marketplace)
    install_skill = tool(_install_skill)

    return [search_marketplace, install_skill]
