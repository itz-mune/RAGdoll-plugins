# Skill Finder

A meta-skill that gives RAGdoll the ability to discover and install plugins from the marketplace on its own — no manual browsing required.

## What it does

When the assistant encounters something it can't handle — an unsupported file type, a missing API integration, a requested speaking style — it will automatically search the marketplace, find the right plugin, and install or activate it for you.

Three tools are added to the assistant's toolbox:

| Tool | Purpose |
|------|---------|
| `search_marketplace` | Search the plugin registry by natural-language query. Returns matching skills and styles with their install status. |
| `install_skill` | Download and install a skill plugin by ID. The skill becomes available on the next message. |
| `install_and_activate_style` | Install a style plugin (if needed) and activate it immediately. Takes effect from the next message onward. |

## How it works

```
User asks something the agent can't do
        ↓
Agent calls search_marketplace("what the user needs")
        ↓
Marketplace returns ranked matches with IDs and status
        ↓
Agent calls install_skill / install_and_activate_style
        ↓
Plugin is downloaded from GitHub and installed via the sidecar
        ↓
Agent tells the user the plugin is ready
```

## Example — missing skill

> **User:** Can you generate an image of a sunset?  
> **Assistant:** I don't have an image generation skill installed yet. Let me find one…  
> *(calls `search_marketplace("generate image from text")`)*  
> *(calls `install_skill("image-gen-dalle")`)*  
> ✅ **Image Gen (DALL-E)** has been installed! Please send your message again and I'll generate the image.

## Example — style request

> **User:** Can you talk like a pirate from now on?  
> **Assistant:** Arrr, let me set that up for ye!  
> *(calls `search_marketplace("pirate speaking style")`)*  
> *(calls `install_and_activate_style("style-pirate")`)*  
> ✅ **Pirate Mode** is now active. Starting from your next message, I'll respond like a proper swashbuckler. 🏴‍☠️

## Requirements

- No API key required.
- Requires an active internet connection to fetch plugins from GitHub.
- The sidecar must be running (it handles the actual installation).

## Notes

- **Skills** are loaded at the start of each request, so a newly installed skill takes effect when you re-send your message — not in the same response where it was installed.
- **Styles** are also loaded at request start, so the new style applies from your *next* message onward.
- If a skill requires an API key (e.g. DALL-E, Stability AI), the assistant will warn you and direct you to configure it in the Marketplace → Installed tab.
- This skill is pre-installed and always enabled — it cannot be disabled, as it is foundational to the self-extending capability of RAGdoll.
