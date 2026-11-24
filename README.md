# CodEz

Terminal coding agent. One executable: `codez`.

## Install

Debian (amd64):

```bash
sudo apt install './codez#1c-1.deb'
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

Configure a provider and model on first launch. Supported protocols: OpenAI Responses, Anthropic Messages and OpenAI-compatible Chat Completions (including local endpoints). Press Enter at the model prompt to discover and select a model. `/models [filter]` discovers and filters exposed model IDs; `/model <id>` changes models; `/setup` reconfigures; `/resume` loads recent history; `/new` starts a fresh context. `/status` shows the current model and session; `/clear` redraws the terminal.

The terminal uses ANSI styling and live tool progress when attached to a TTY. Model responses stream via SSE by default; `CODEZ_NO_STREAM=1` selects non-streaming requests. `NO_COLOR=1` disables colors and animated progress; `CODEZ_NO_MOTION=1` disables animation only. Redirected output is free of ANSI formatting.

Repository tools: list, search, read, atomic write, exact text replacement, Git status/diff and shell execution. File mutations and shell execution require approval; shell commands run with the current user's OS permissions, not in a sandbox. Only known unsafe command patterns are additionally blocked. Credentials use a private `0600` file (not encrypted); `CODEZ_API_KEY` may also be supplied by the environment.

This is a release candidate, not a complete production-ready implementation. Live external provider credentials, MCP, Skills loading, automated deployment adapters, full context compaction and Arch installation are not verified or not implemented. Local tests cover SSE decoding for all three protocols; the smoke test exercises a deterministic HTTP provider and actual file changes, not a paid external API.
