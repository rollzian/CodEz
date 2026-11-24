package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/AuxiaCorp/CodEz/internal/config"
	"github.com/AuxiaCorp/CodEz/internal/provider"
)

type providerPreset struct {
	Name, Kind, URL string
	Local           bool
}

var providerPresets = []providerPreset{
	{"OpenAI", "openai", "https://api.openai.com/v1", false},
	{"Anthropic / Claude", "anthropic", "https://api.anthropic.com", false},
	{"Custom endpoint", "compatible", "", false},
	{"Ollama", "compatible", "http://127.0.0.1:11434/v1", true},
	{"LM Studio", "compatible", "http://127.0.0.1:1234/v1", true},
	{"OpenRouter", "compatible", "https://openrouter.ai/api/v1", false},
	{"Google Gemini", "compatible", "https://generativelanguage.googleapis.com/v1beta/openai", false},
	{"DeepSeek", "compatible", "https://api.deepseek.com", false},
	{"Groq", "compatible", "https://api.groq.com/openai/v1", false},
	{"xAI / Grok", "compatible", "https://api.x.ai/v1", false},
	{"Mistral AI", "compatible", "https://api.mistral.ai/v1", false},
	{"Cerebras", "compatible", "https://api.cerebras.ai/v1", false},
}

func (c console) browser(link string) {
	fmt.Fprintf(c.out, "\n  Open in your browser:\n  %s\n\n", link)
	if !c.rich || (os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "") {
		return
	}
	if bin, e := exec.LookPath("xdg-open"); e == nil {
		cmd := exec.Command(bin, link)
		if cmd.Start() == nil {
			go func() { _ = cmd.Wait() }()
		}
	}
}

func authMessage(err error, cfg config.Config, key string) string {
	detail := redact(err.Error(), key)
	if !provider.IsUnauthorized(err) {
		return detail
	}
	switch cfg.Auth {
	case "chatgpt":
		return detail + " - ChatGPT rejected this session. Reconnect with /setup and grant plan usage."
	case "openrouter":
		return detail + " - OpenRouter rejected the issued key. Sign in again with /setup."
	}
	if os.Getenv("CODEZ_API_KEY") != "" {
		return detail + " - provider rejected CODEZ_API_KEY. Update or unset it, then use /setup."
	}
	return detail + " - API key missing, invalid, expired, or for a different provider. Use /setup."
}

func (c console) catalog(cfg config.Config, key, mode string) ([]provider.ModelInfo, string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	stop := c.progress("Loading available models")
	defer stop()
	rows, e := provider.Catalog(ctx, createProvider(cfg, key), mode)
	if provider.IsUnauthorized(e) && cfg.Auth == "chatgpt" {
		fresh, err := config.RecoverChatGPTKey(ctx, key)
		if err != nil {
			return nil, key, fmt.Errorf("ChatGPT session rejected; reconnect with /setup: %w", err)
		}
		key = fresh
		rows, e = provider.Catalog(ctx, createProvider(cfg, key), mode)
	}
	return rows, key, e
}

func matchesModel(m provider.ModelInfo, q string) bool {
	return strings.Contains(strings.ToLower(m.ID+" "+m.Label()), strings.ToLower(q))
}

// A bounded, searchable catalog; each displayed number selects an actual ID.
func (c console) pickModel(cfg config.Config, key, query string) (string, string, error) {
	const pageSize = 10
	mode := "all"
	page := 0
	rows, key, e := c.catalog(cfg, key, mode)
	if e != nil {
		return "", key, errors.New(authMessage(e, cfg, key))
	}
	if len(rows) == 0 {
		return "", key, errors.New("No models available. Check provider account or install a local model.")
	}
	router := provider.IsOpenRouter(createProvider(cfg, key))
	local := strings.HasPrefix(cfg.BaseURL, "http://127.0.0.1:") || strings.HasPrefix(cfg.BaseURL, "http://localhost:")
	for {
		filtered := make([]provider.ModelInfo, 0, len(rows))
		for _, m := range rows {
			if matchesModel(m, query) && (mode != "free" || m.Free() || local) {
				filtered = append(filtered, m)
			}
		}
		pages := max(1, (len(filtered)+pageSize-1)/pageSize)
		page = min(page, pages-1)
		start := page * pageSize
		end := min(start+pageSize, len(filtered))
		subtitle := fmt.Sprintf("%d available · page %d/%d · %s", len(filtered), page+1, pages, strings.ToUpper(mode))
		items := make([]string, 0, end-start)
		for _, m := range filtered[start:end] {
			label := strings.Join(strings.Fields(clean(m.Label())), " ")
			price := "price unavailable"
			if cfg.Auth == "chatgpt" {
				price = "ChatGPT plan"
			} else if local {
				price = "local"
			} else if in, out, ok := m.Prices(); ok {
				price = fmt.Sprintf("$%.4g / $%.4g per M", in, out)
				if m.Free() {
					price = "FREE"
				}
			}
			line := label + "  ·  " + price
			if m.Context > 0 {
				line += fmt.Sprintf("  ·  %dk ctx", m.Context/1000)
			}
			items = append(items, line)
		}
		if !c.rich || os.Getenv("CODEZ_SIMPLE_UI") != "" {
			if router {
				c.note("Filters: all / free / best / cheap / expensive / smart")
			} else {
				c.note("Filters: all / free")
			}
		}
		choice, err := c.selectMenu("03  /  Model library", subtitle, items, true)
		if err != nil {
			return "", key, err
		}
		if choice == "filter" {
			labels := []string{"All", "Free"}
			values := []string{"all", "free"}
			if router {
				labels = append(labels, "Best · coding benchmark", "Cheap · low to high", "Expensive · high to low", "Smart · intelligence benchmark")
				values = append(values, "best", "cheap", "expensive", "smart")
			}
			selected, err := c.selectMenu("Model filter", "Source: provider catalog", labels, false)
			if err != nil {
				continue
			}
			n, err := strconv.Atoi(selected)
			if err != nil || n < 1 || n > len(values) {
				continue
			}
			choice = values[n-1]
		}
		if choice == "/" && c.rich {
			value, err := c.ask("  Search model: ")
			if err != nil {
				return "", key, err
			}
			choice = "/" + value
		}
		switch choice {
		case "q", "cancel":
			return "", key, errors.New("model selection cancelled")
		case "next", "n":
			page = min(page+1, pages-1)
			continue
		case "prev", "p":
			page = max(0, page-1)
			continue
		case "all", "free", "best", "cheap", "expensive", "smart":
			if choice != "all" && choice != "free" && !router {
				c.note("This provider does not expose comparable prices or benchmark rankings. Use OpenRouter for ranked views.")
				continue
			}
			if choice != mode {
				next, fresh, err := c.catalog(cfg, key, choice)
				key = fresh
				if err != nil {
					c.failure(authMessage(err, cfg, key))
					continue
				}
				rows = next
				mode = choice
				page = 0
			}
			continue
		}
		if strings.HasPrefix(choice, "/") {
			query = strings.TrimSpace(strings.TrimPrefix(choice, "/"))
			page = 0
			continue
		}
		n, err := strconv.Atoi(choice)
		if err == nil && n > 0 && n <= end-start {
			return filtered[start+n-1].ID, key, nil
		}
		c.note("Choose a displayed number or change the filter.")
	}
}
