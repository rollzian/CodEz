# CodEz

Terminal coding agent. One executable: `codez`.

## Install

Debian (amd64):

```bash
sudo apt install './codez#1f-1.deb'
codez
```

Arch (PKGBUILD included; native Arch installation not yet verified):

```bash
makepkg -si
codez
```

## Build and verify

```bash
go vet ./...
go test ./...
go test -race ./...
CGO_ENABLED=0 go build -trimpath -o codez ./cmd/codez
python3 scripts/smoke.py ./codez
bash scripts/build-deb.sh
```

## Usage

Configure a provider and model on first launch. OpenAI and OpenRouter offer account sign-in or API-key authentication. ChatGPT sign-in opens the default browser when available and prints the official authorization URL as a fallback; approval returns through a loopback callback. Use the browser on the same machine. It uses an eligible ChatGPT plan, not a free API entitlement. OpenRouter sign-in prints a PKCE authorization URL and accepts the one-time code. Claude Console sign-in is a browser link for creating an API key; Claude subscription OAuth is not implemented. Custom providers require an OpenAI-compatible base URL and API key (empty for unauthenticated local servers). ChatGPT credentials are stored separately in an owner-only file, with refresh before requests. Live account authorization has not been verified; OAuth protocol tests use deterministic local fixtures. Supported protocols: OpenAI Responses, Anthropic Messages and OpenAI-compatible Chat Completions (including local endpoints). The model library discovers available models and uses arrow keys, Enter, search (/), filters (Tab), pagination (left/right), and Escape. OpenRouter supplies actual price and benchmark ordering; other providers expose only their available metadata. `/models [filter]` and `/model` open the library; `/model <id>` remains an explicit command. HTTP 401 triggers a forced ChatGPT token refresh when possible; rejected API keys require reconfiguration. Model discovery is checked before saving setup; `/setup` reconfigures; `/resume` loads recent history; `/new` starts a fresh context. `/status` shows the current model and session; `/clear` redraws the terminal.

Set `CODEZ_SIMPLE_UI=1` for numbered line-based selection. The terminal uses ANSI styling and live tool progress when attached to a TTY. Model responses stream via SSE by default; `CODEZ_NO_STREAM=1` selects non-streaming requests. `NO_COLOR=1` disables colors and animated progress; `CODEZ_NO_MOTION=1` disables animation only. Redirected output is free of ANSI formatting.

Repository tools: list, search, read, atomic write, exact text replacement, Git status/diff and shell execution. File mutations and shell execution require approval; shell commands run with the current user's OS permissions, not in a sandbox. Only known unsafe command patterns are additionally blocked. Credentials use a private `0600` file (not encrypted); `CODEZ_API_KEY` is accepted in noninteractive setup or by typing `:env` at the interactive key prompt. Saved credentials take priority on restart.

This is a release candidate, not a complete production-ready implementation. Live external provider credentials, MCP, Skills loading, automated deployment adapters, full context compaction and Arch installation are not verified or not implemented. Local tests cover SSE decoding for all three protocols; the smoke test exercises a deterministic HTTP provider and actual file changes, not a paid external API.
