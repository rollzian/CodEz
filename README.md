<div align="center">

# C O D E Z

**Your terminal. Your models. Your code.**

An interactive AI coding agent for Linux, with a keyboard-first interface, local conversations and optional Auxia collaboration.

[![CI](https://github.com/rollzian/CodEz/actions/workflows/ci.yml/badge.svg)](https://github.com/rollzian/CodEz/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/rollzian/CodEz?include_prereleases&style=flat-square&color=8b5cf6)](https://github.com/rollzian/CodEz/releases)
[![License](https://img.shields.io/github/license/rollzian/CodEz?style=flat-square)](LICENSE)

[**Download**](https://github.com/rollzian/CodEz/releases) · [Quick start](#quick-start) · [Features](#features) · [Shortcuts](#keyboard-shortcuts) · [Cloud](#auxia-cloud)

</div>

---

## Quick start

<table>
<tr><th align="left">Arch Linux</th><th align="left">Debian / Ubuntu · amd64</th></tr>
<tr><td>

```bash
git clone https://github.com/rollzian/CodEz.git
cd CodEz
makepkg -si
codez
```

</td><td>

```bash
curl -fLO https://github.com/rollzian/CodEz/releases/download/1h-1/codez.1h-1.deb
sudo apt install ./codez.1h-1.deb
codez
```

</td></tr>
</table>

On first launch, select a provider, authenticate and choose a model from the discovered catalog. No separate configuration command is required.

> Current published release: **0.7.7 · #1h-1** (release candidate). Native Arch installation and live account authorization have not been independently verified.

## Features

| Code | Navigate | Collaborate |
| :--- | :--- | :--- |
| Read, search and edit repositories | Keyboard-first model selection | Personal and team workspaces |
| Stream AI responses | Independent local conversations | Seven server-enforced roles |
| Run approved shell commands | Command palette and history | Invitations and friend requests |
| Review Git changes | Local Skills library | Public project directory |

## A terminal built around your workflow

```text
  CODEZ                              workspace / main

  Model       Selected provider model
  Mode        Code

  › What would you like to build?

  ← Chats   Ctrl+K Menu   Ctrl+P Models   Shift+Tab Mode
```

*Illustrative layout, not a captured screenshot.*

### Choose your model

CodEz supports OpenAI Responses, Anthropic Messages and OpenAI-compatible chat APIs. Use a remote provider or a local server such as Ollama or LM Studio. The model catalog supports search and keyboard selection; pricing and ranking data depend on the provider.

### Choose your mode

| Mode | Access |
| :--- | :--- |
| Code | Repository tools and approved mutations |
| Ask | Read-only tools |
| Plan | Read-only tools |
| Review | Read-only tools |

## Keyboard shortcuts

| Keys | Action | Keys | Action |
| :--- | :--- | :--- | :--- |
| ← / → | Chats / return | Ctrl+K | Command palette |
| Ctrl+← | Workspaces | Ctrl+N | New chat |
| Ctrl+→ | Teams | Ctrl+P | Models |
| Ctrl+↑ | Friends | Ctrl+H | Prompt history |
| Ctrl+↓ | Public projects | Ctrl+F | Search chats |
| Ctrl+S | Save | Ctrl+L | Clear |
| Ctrl+R | Recall prompt | Shift+Tab | Switch mode |

Arrow keys edit nonempty input. Some shortcuts depend on terminal support. Use `CODEZ_SIMPLE_UI=1` for numbered menus and line input.

## Architecture

```mermaid
flowchart LR
    UI["Terminal UI"] --> Agent["Coding agent"]
    Agent --> Provider["Provider adapters"]
    Provider --> APIs["Remote / local models"]
    Agent --> Tools["Repository tools"]
    Tools --> Repo["Local workspace"]
    UI --> Sessions["Local chats"]
    UI --> Skills["Local Skills"]
    UI --> Cloud["Optional Auxia client"]
    Cloud --> Service["Cloud API"]
    Service --> DB["SQLite"]
```

The CLI remains usable without an Auxia account. Cloud sessions and provider credentials are separate.

## Usage and security

<details>
<summary>Provider authentication, model discovery and terminal settings</summary>

Configure a provider and model on first launch. OpenAI and OpenRouter offer account sign-in or API-key authentication. ChatGPT sign-in opens the default browser when available and prints the official authorization URL as a fallback; approval returns through a loopback callback. Use the browser on the same machine. It uses an eligible ChatGPT plan, not a free API entitlement. OpenRouter sign-in prints a PKCE authorization URL and accepts the one-time code. Claude Console sign-in is a browser link for creating an API key; Claude subscription OAuth is not implemented. Custom providers require an OpenAI-compatible base URL and API key (empty for unauthenticated local servers). ChatGPT credentials are stored separately in an owner-only file, with refresh before requests. Live account authorization has not been verified; OAuth protocol tests use deterministic local fixtures. Supported protocols: OpenAI Responses, Anthropic Messages and OpenAI-compatible Chat Completions (including local endpoints). The model library discovers available models and uses arrow keys, Enter, search (/), filters (Tab), pagination (left/right), and Escape. OpenRouter supplies actual price and benchmark ordering; other providers expose only their available metadata. `/models [filter]` and `/model` open the library; `/model <id>` remains an explicit command. HTTP 401 triggers a forced ChatGPT token refresh when possible; rejected API keys require reconfiguration. Model discovery is checked before saving setup; `/setup` reconfigures; `/resume` loads recent history; `/new` creates an independent chat. `/status` shows the current model and session; `/clear` redraws the terminal.

Set `CODEZ_SIMPLE_UI=1` for numbered line-based selection. The terminal uses ANSI styling and live tool progress when attached to a TTY. Model responses stream via SSE by default; `CODEZ_NO_STREAM=1` selects non-streaming requests. `NO_COLOR=1` disables colors and animated progress; `CODEZ_NO_MOTION=1` disables animation only. Redirected output is free of ANSI formatting.

Repository tools: list, search, read, atomic write, exact text replacement, Git status/diff and shell execution. File mutations and shell execution require approval; shell commands run with the current user's OS permissions, not in a sandbox. Only known unsafe command patterns are additionally blocked. Credentials use a private `0600` file (not encrypted); `CODEZ_API_KEY` is accepted in noninteractive setup or by typing `:env` at the interactive key prompt. Saved credentials take priority on restart.

This is a release candidate, not a complete production-ready implementation. Live external provider credentials, MCP, automated deployment adapters, full context compaction and Arch installation are not verified or not implemented. Local tests cover SSE decoding for all three protocols; the smoke test exercises a deterministic HTTP provider and actual file changes, not a paid external API.

## Navigation and local chats

The interactive terminal clears on startup and shows the current Git branch when available. It restores the active local conversation (up to 80 recent events). `←` on empty input opens Chats; `→` returns from the list. `Ctrl+←/→/↑/↓` open Workspaces, Teams, Friends and Public Projects. `Ctrl+K` opens the palette, `Ctrl+N` creates a chat, `Ctrl+P` opens models, `Ctrl+H` on empty input opens prompt history, `Ctrl+F` searches chat titles, `Ctrl+S` flushes the current chat, `Ctrl+L` clears, `Ctrl+R` recalls a previous prompt, and `Shift+Tab` cycles modes. Arrow keys edit nonempty input. Bracketed paste preserves newlines in the submitted prompt; the editor displays a single horizontally scrolling line. `/chats` lists up to 500 recent chats in the current workspace. Drafts survive panel switches during the running process; they are not synced or persisted across restarts. `CODEZ_SIMPLE_UI=1` retains line input and numbered menus.

`/mode` offers Code, Ask, Plan and Review. Ask, Plan and Review advertise only read-only tools and reject model-requested mutations and shell commands. `/doctor` reports local config and Git availability. The system prompt reflects the selected provider model ID. `/skills` discovers `SKILL.md` in `.codez/skills/<name>/` and `$XDG_CONFIG_HOME/codez/skills/<name>/`, previews contents and asks before enabling them. Up to four local skills per process, each limited to 32 KiB; no script execution or remote installation.

</details>

## Auxia Cloud

`/menu` opens the command palette. `/auxia` opens the collaboration hub; `/workspaces`, `/teams`, `/friends`, and `/projects` open individual collections. `codez --auxia` is available without configuring an AI provider. Cloud sign-in opens an Auxia device-confirmation page in the browser. It does not send AI provider API keys to Auxia. The separate revocable Cloud session is stored in an owner-only file.

Personal and team workspaces are persistent metadata, not remote execution environments or synchronized source trees. Teams use explicit invitations and acceptance. Roles are Owner, Admin, Maintainer, Developer, Reviewer, Viewer and Guest. Only owners assign roles. Owner/Admin manage invitations and members; Admin cannot remove another Admin. Owner/Admin/Maintainer manage team workspace metadata; Developer creates and deletes their own team workspaces while a member. Reviewer/Viewer are read-only; Guest also cannot list members. Legacy members migrate to Developer. Friend requests require acceptance. Public projects publish a name and HTTPS repository link, not local files. Lists are limited to 200 items in this release.

The included `cloud/app.py` is an independently deployable service backed by SQLite. It must be mounted at `https://auxia.space/codez-cloud`; the domain's existing authentication backend and OAuth client registration were unavailable for live integration. No new Auxia password database is created. The service uses the existing identity provider's authorization-code + PKCE and authenticated userinfo endpoints. Register the callback `https://auxia.space/codez-cloud/oauth/callback` in that provider and configure the following server-only environment variables:

- `CODEZ_CLOUD_DB`: absolute path to a private database outside the public web root.
- `AUXIA_OAUTH_AUTHORIZE`, `AUXIA_OAUTH_TOKEN`, `AUXIA_OAUTH_USERINFO`: actual HTTPS endpoints from the Auxia identity provider. The authorization URL defaults to `https://auxia.space/api/login` as requested; confirm that it implements OAuth authorization-code + PKCE before deployment. Token and userinfo endpoints and client registration are required; this live contract was not verified.
- `AUXIA_OAUTH_CLIENT_ID`, `AUXIA_OAUTH_CLIENT_SECRET` (if required), `AUXIA_OAUTH_SCOPE` (default `openid profile`).

Local smoke: `python3 cloud/app.py` binds to `127.0.0.1:8088`. For public deployment, serve `cloud.app:create_app()` with a production WSGI server, behind the existing HTTPS reverse proxy at `/codez-cloud/`. Rate-limit anonymous device-start and login requests at the reverse proxy; do not log query strings or authorization headers. Use a restricted OS account and back up the SQLite database. The built-in WSGI server is for local testing only.

Verify with `python3 -m unittest discover -s cloud` and `go test ./...`. Local tests simulate the identity provider; live Auxia sign-in requires server deployment and a registered client.

## Development

```bash
go vet ./...
go test ./...
go test -race ./...
CGO_ENABLED=0 go build -trimpath -o codez ./cmd/codez
python3 scripts/smoke.py ./codez
bash scripts/build-deb.sh
```

| Directory | Responsibility |
| :--- | :--- |
| [cmd/codez](cmd/codez) | Terminal UI and agent orchestration |
| [internal/provider](internal/provider) | Model discovery and API adapters |
| [internal/session](internal/session) | Local chat persistence |
| [internal/tools](internal/tools) | Repository and execution tools |
| [internal/skills](internal/skills) | Local skill discovery |
| [cloud](cloud) | Optional collaboration backend |
| [scripts](scripts) | Packaging and smoke tests |

## Roadmap

MCP execution, automated deployment adapters, full context compaction and production Auxia integration remain unfinished in this published version.

---

<div align="center">

**CodEz** · [Releases](https://github.com/rollzian/CodEz/releases) · [Issues](https://github.com/rollzian/CodEz/issues) · [MIT License](LICENSE)

</div>
