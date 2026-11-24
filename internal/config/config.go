package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	Provider string `json:"provider"`
	BaseURL  string `json:"base_url"`
	Model    string `json:"model"`
	Auth     string `json:"auth,omitempty"`
}

func Dir() (string, error) {
	d, e := os.UserConfigDir()
	if e != nil {
		return "", e
	}
	d = filepath.Join(d, "codez")
	if e = os.MkdirAll(d, 0700); e != nil {
		return "", e
	}
	return d, nil
}
func (c Config) Validate() error {
	switch c.Provider {
	case "openai", "anthropic", "compatible":
	default:
		return errors.New("invalid provider")
	}
	switch c.Auth {
	case "", "api_key":
	case "chatgpt":
		if c.Provider != "openai" || c.BaseURL != "https://api.openai.com/v1" {
			return errors.New("ChatGPT authorization requires the official OpenAI API endpoint")
		}
	case "openrouter":
		if c.Provider != "compatible" || c.BaseURL != "https://openrouter.ai/api/v1" {
			return errors.New("OpenRouter authorization requires the official OpenRouter API endpoint")
		}
	default:
		return errors.New("invalid authentication method")
	}
	if strings.TrimSpace(c.Model) == "" {
		return errors.New("model is required")
	}
	u, e := url.Parse(c.BaseURL)
	if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errors.New("invalid base URL")
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "localhost" || u.Hostname() == "127.0.0.1" || u.Hostname() == "::1")) {
		return errors.New("HTTPS required except on loopback")
	}
	return nil
}
func Load() (Config, error) {
	var c Config
	d, e := Dir()
	if e != nil {
		return c, e
	}
	b, e := os.ReadFile(filepath.Join(d, "config.json"))
	if e != nil {
		return c, e
	}
	if e = json.Unmarshal(b, &c); e != nil {
		return c, e
	}
	return c, c.Validate()
}
func Secret() (string, error) {
	d, e := Dir()
	if e != nil {
		return "", e
	}
	b, e := privateRead(d, "secret")
	if os.IsNotExist(e) {
		return "", nil
	}
	return strings.TrimSpace(string(b)), e
}

// APIKey prefers the saved provider credential, even when it is intentionally empty.
// The environment is a fallback only for externally provisioned configurations.
func APIKey() (string, error) {
	d, e := Dir()
	if e != nil {
		return "", e
	}
	b, e := privateRead(d, "secret")
	if os.IsNotExist(e) {
		return strings.TrimSpace(os.Getenv("CODEZ_API_KEY")), nil
	}
	return strings.TrimSpace(string(b)), e
}
func atomic(d, n string, b []byte) error {
	f, e := os.CreateTemp(d, ".codez-*")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	if _, e = f.Write(b); e != nil {
		f.Close()
		return e
	}
	if e = f.Sync(); e != nil {
		f.Close()
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	return os.Rename(f.Name(), filepath.Join(d, n))
}
func Save(c Config, key string) error {
	if c.Auth == "chatgpt" {
		return SaveSettings(c)
	}
	if e := c.Validate(); e != nil {
		return e
	}
	d, e := Dir()
	if e != nil {
		return e
	}
	b, e := json.MarshalIndent(c, "", "  ")
	if e != nil {
		return e
	}
	name := "secret"
	if c.Auth == "openrouter" {
		name = "openrouter-secret"
	}
	if e = atomic(d, name, []byte(key)); e != nil {
		return fmt.Errorf("save credentials: %w", e)
	}
	return atomic(d, "config.json", b)
}

func SaveSettings(c Config) error {
	if err := c.Validate(); err != nil {
		return err
	}
	d, err := Dir()
	if err != nil {
		return err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return atomic(d, "config.json", b)
}

func OpenRouterKey() (string, error) {
	d, err := Dir()
	if err != nil {
		return "", err
	}
	b, err := privateRead(d, "openrouter-secret")
	return string(b), err
}
