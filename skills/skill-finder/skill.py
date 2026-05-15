"""
Skill Finder — meta-skill that searches the RAGdoll marketplace and auto-installs
skills and styles on demand.

Tools exposed:
  search_marketplace(query)          — find skills OR styles matching a description
  install_skill(plugin_id)           — download and install a skill by registry ID
  install_and_activate_style(plugin_id) — install a style (if needed) and activate it

The agent should call search_marketplace first to identify the right plugin ID,
then call the appropriate install tool.

Skills:  need a re-send to take effect (loaded at request start)
Styles:  take effect on the very next message after activation
"""
import json
import re
import urllib.request

SIDECAR_URL = "http://127.0.0.1:8765"

# ── Config helpers ────────────────────────────────────────────────────────────

def _get_plugins_config() -> dict:
    """
    Load the plugins section of ragdoll.config.json.
    Tries the sidecar config module first; falls back to a filesystem search.
    """
    try:
        from config import get_plugins_config
        return get_plugins_config()
    except ImportError:
        pass

    import os
    base = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        candidate = os.path.join(base, "ragdoll.config.json")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as f:
                return json.load(f).get("plugins", {})
        base = os.path.dirname(base)

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


# ── Shared: download plugin files from GitHub ────────────────────────────────

BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
               ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4"}

def _download_plugin_files(plugin: dict, api_base: str, raw_base: str) -> list[dict]:
    """Fetch all text files for a plugin from the GitHub Contents API."""
    file_list = _get(f"{api_base}/contents/{plugin['path']}")
    if not isinstance(file_list, list):
        return []
    files = []
    for file_info in file_list:
        name = file_info.get("name", "")
        if not name:
            continue
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext in BINARY_EXTS:
            continue
        try:
            req = urllib.request.Request(
                f"{raw_base}/{plugin['path']}/{name}",
                headers={"User-Agent": "RAGdoll-SkillFinder/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            files.append({"path": name, "content": content})
        except Exception:
            pass
    return files


def _fetch_registry_and_state():
    """Return (registry_plugins, installed_ids, active_style_id, cfg)."""
    cfg = _get_plugins_config()
    registry_url = cfg.get(
        "registry_url",
        "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main/registry.json",
    )
    registry = _get(registry_url)
    all_plugins = registry.get("plugins", [])

    try:
        state = _get(f"{SIDECAR_URL}/plugins")
        installed_ids = {p["id"] for p in state.get("plugins", [])}
        enabled_ids = {p["id"] for p in state.get("plugins", []) if p.get("is_enabled")}
        active_style = state.get("active_style")
    except Exception:
        installed_ids = set()
        enabled_ids = set()
        active_style = None

    return all_plugins, installed_ids, enabled_ids, active_style, cfg


# ── Tool implementations ──────────────────────────────────────────────────────

def _search_marketplace(query: str) -> str:
    """
    Search the RAGdoll plugin marketplace for skills AND styles matching a query.
    Use this when the current toolset lacks a required capability, or when the user
    asks to change the assistant's tone/persona/speaking style.

    Args:
        query: Natural-language description of what's needed.
               For skills: "read Excel file", "generate image", "fetch webpage"
               For styles: "speak like a pirate", "formal tone", "shakespearean"
    """
    try:
        all_plugins, installed_ids, enabled_ids, active_style, _ = _fetch_registry_and_state()

        scored = sorted(
            [(p, _score(p, query)) for p in all_plugins if _score(p, query) > 0],
            key=lambda x: -x[1],
        )

        if not scored:
            skill_ids = ", ".join(f"`{p['id']}`" for p in all_plugins if p.get("category") == "skill")
            style_ids = ", ".join(f"`{p['id']}`" for p in all_plugins if p.get("category") == "style")
            return (
                f"No plugins matched '{query}' in the marketplace.\n"
                f"Available skills: {skill_ids}\n"
                f"Available styles: {style_ids}"
            )

        lines = [f"Found {len(scored)} plugin(s) matching **'{query}'**:\n"]
        for plugin, _ in scored[:6]:
            pid = plugin["id"]
            category = plugin.get("category", "skill")
            needs_key = bool(plugin.get("config_fields"))

            if category == "style":
                if pid == active_style:
                    status = "✅ installed & active"
                elif pid in installed_ids:
                    status = "⚠️ installed but not active"
                else:
                    status = "📦 not installed"
                cat_label = "🎨 Style"
                action_hint = f"Call `install_and_activate_style` with id `{pid}` to install and activate it."
            else:
                if pid in enabled_ids:
                    status = "✅ installed & enabled"
                elif pid in installed_ids:
                    status = "⚠️ installed but disabled"
                else:
                    status = "📦 not installed"
                cat_label = "🔧 Skill"
                action_hint = f"Call `install_skill` with id `{pid}` to install it."

            key_note = "  ⚠️ *Requires API key after install*" if needs_key else ""
            lines.append(
                f"• [{cat_label}] **{plugin['name']}** (id: `{pid}`) — {status}\n"
                f"  {plugin['description']}{key_note}\n"
                f"  ↳ {action_hint}"
            )

        return "\n".join(lines)

    except Exception as exc:
        return f"Error searching marketplace: {exc}"


def _install_skill(plugin_id: str) -> str:
    """
    Download and install a skill from the RAGdoll marketplace by its plugin ID.
    Only use this for category=skill plugins.
    After a successful install, tell the user to re-send their message so the
    new skill becomes active — skills are loaded at request start, not mid-request.

    Args:
        plugin_id: Exact plugin ID, e.g. "image-viewer" or "youtube-transcript"
    """
    try:
        all_plugins, installed_ids, _, _, cfg = _fetch_registry_and_state()

        plugin = next((p for p in all_plugins if p["id"] == plugin_id), None)
        if not plugin:
            available = [p["id"] for p in all_plugins]
            return f"Plugin `{plugin_id}` not found. Available: {', '.join(available)}"

        if plugin.get("category") == "style":
            return (
                f"`{plugin_id}` is a **style**, not a skill. "
                f"Use `install_and_activate_style` instead."
            )

        if plugin_id in installed_ids:
            return (
                f"**{plugin['name']}** is already installed.\n"
                f"If it's disabled, enable it from the Plugin Picker (🧩) in the chat bar."
            )

        api_base = cfg.get("github_api_base", "https://api.github.com/repos/itz-mune/RAGdoll-plugins")
        raw_base = cfg.get("raw_base", "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main")

        files = _download_plugin_files(plugin, api_base, raw_base)
        if not files:
            return f"No downloadable files found for `{plugin_id}`."

        result = _post(f"{SIDECAR_URL}/plugins/install", {"id": plugin_id, "files": files})

        needs_key = bool(plugin.get("config_fields"))
        key_warning = (
            "\n\n⚠️ **This skill requires an API key.** Open Marketplace → Installed and configure it before use."
            if needs_key else ""
        )

        if result.get("success"):
            return (
                f"✅ **{plugin['name']}** installed successfully!{key_warning}\n\n"
                f"Please **send your message again** — the skill is now active and I'll use it automatically."
            )
        return f"Installation failed: {result.get('error', 'unknown error')}"

    except Exception as exc:
        return f"Error installing `{plugin_id}`: {exc}"


def _install_and_activate_style(plugin_id: str) -> str:
    """
    Install a style plugin (if not already installed) and immediately activate it.
    Only use this for category=style plugins.
    Styles affect how the assistant speaks — e.g. pirate, Shakespearean, formal.
    The new style takes effect starting from the NEXT message (not this one).

    Args:
        plugin_id: Exact style plugin ID, e.g. "style-pirate" or "style-shakespeare"
    """
    try:
        all_plugins, installed_ids, _, active_style, cfg = _fetch_registry_and_state()

        plugin = next((p for p in all_plugins if p["id"] == plugin_id), None)
        if not plugin:
            style_ids = [p["id"] for p in all_plugins if p.get("category") == "style"]
            return (
                f"Style `{plugin_id}` not found in the marketplace.\n"
                f"Available styles: {', '.join(style_ids)}"
            )

        if plugin.get("category") != "style":
            return (
                f"`{plugin_id}` is a **skill**, not a style. "
                f"Use `install_skill` instead."
            )

        # Install if not already present
        if plugin_id not in installed_ids:
            api_base = cfg.get("github_api_base", "https://api.github.com/repos/itz-mune/RAGdoll-plugins")
            raw_base = cfg.get("raw_base", "https://raw.githubusercontent.com/itz-mune/RAGdoll-plugins/main")

            files = _download_plugin_files(plugin, api_base, raw_base)
            if not files:
                return f"No downloadable files found for `{plugin_id}`."

            result = _post(f"{SIDECAR_URL}/plugins/install", {"id": plugin_id, "files": files})
            if not result.get("success"):
                return f"Installation failed: {result.get('error', 'unknown error')}"

        # Activate the style
        if active_style == plugin_id:
            return (
                f"**{plugin['name']}** is already the active style — "
                f"I'm already speaking in that style!"
            )

        _post(f"{SIDECAR_URL}/plugins/style/{plugin_id}/activate", {})

        return (
            f"✅ **{plugin['name']}** has been installed and activated!\n\n"
            f"Starting from your **next message**, I'll respond in that style. "
            f"You can deactivate it anytime from the Plugin Picker (🧩) in the chat bar."
        )

    except Exception as exc:
        return f"Error activating style `{plugin_id}`: {exc}"


# ── Register ──────────────────────────────────────────────────────────────────

def register():
    from langchain_core.tools import tool

    search_marketplace = tool(_search_marketplace)
    install_skill = tool(_install_skill)
    install_and_activate_style = tool(_install_and_activate_style)

    return [search_marketplace, install_skill, install_and_activate_style]
