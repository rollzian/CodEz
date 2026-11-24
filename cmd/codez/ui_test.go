package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/AuxiaCorp/CodEz/internal/provider"
)

func TestStreamRedactionAcrossChunks(t *testing.T) {
	r := streamRedactor{key: "secret-token"}
	var out strings.Builder
	for _, s := range []string{"before sec", "ret-", "token after s", "ec", "ret-token"} {
		out.WriteString(r.push(s, false))
	}
	out.WriteString(r.push("", true))
	if out.String() != "before [REDACTED] after [REDACTED]" {
		t.Fatalf("%q", out.String())
	}
}
func TestModelRequestDoesNotRepeatText(t *testing.T) {
	t.Setenv("CODEZ_NO_STREAM", "")
	var out bytes.Buffer
	c := console{out: &out}
	// A completed non-streaming response still renders once.
	_, err := c.modelRequest(context.Background(), "key", func(context.Context) (provider.Result, error) { return provider.Result{Text: "once"}, nil })
	if err != nil || out.String() != "once\n" {
		t.Fatalf("%v: %q", err, out.String())
	}
	out.Reset()
	_, err = c.modelRequest(context.Background(), "key", func(context.Context) (provider.Result, error) { return provider.Result{}, errors.New("failed") })
	if err == nil || out.Len() != 0 {
		t.Fatalf("%v: %q", err, out.String())
	}
}
func TestModelSelection(t *testing.T) {
	ids := []string{"alpha", "beta"}
	if got, err := modelSelection("2", ids); got != "beta" || err != nil {
		t.Fatal(got, err)
	}
	if _, err := modelSelection("3", ids); err == nil {
		t.Fatal("accepted invalid index")
	}
	if got, err := modelSelection("custom/model", ids); got != "custom/model" || err != nil {
		t.Fatal(got, err)
	}
}

func TestSetupAPIKeyAndCustom(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("CODEZ_API_KEY", "secret-test")
	for _, tc := range []struct{ input, provider, endpoint string }{{"1\n2\ntest-model\n", "openai", "https://api.openai.com/v1"}, {"2\n2\ntest-model\n", "anthropic", "https://api.anthropic.com"}, {"3\nhttps://example.invalid/v1\ntest-model\n", "compatible", "https://example.invalid/v1"}, {"6\n2\ntest-model\n", "compatible", "https://openrouter.ai/api/v1"}} {
		var out bytes.Buffer
		c := console{in: bufio.NewReader(strings.NewReader(tc.input)), out: &out}
		cfg, key, e := c.setup()
		if e != nil || cfg.Provider != tc.provider || cfg.BaseURL != tc.endpoint || key != "secret-test" || cfg.Auth != "api_key" {
			t.Fatal(cfg, e)
		}
		if strings.Contains(out.String(), key) {
			t.Fatal("key leaked")
		}
	}
}
