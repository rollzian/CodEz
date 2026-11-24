package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"github.com/AuxiaCorp/CodEz/internal/config"
	"net/http"
	"net/http/httptest"
	"os"
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
	orig := append([]providerPreset(nil), providerPresets...)
	defer func() { providerPresets = orig }()
	for _, tc := range []struct {
		index                int
		kind, endpoint, path string
	}{{1, "openai", "https://api.openai.com/v1", "/models"}, {2, "anthropic", "https://api.anthropic.com", "/v1/models"}, {3, "compatible", "", "/models"}, {6, "compatible", "https://openrouter.ai/api/v1", "/models"}} {
		if providerPresets[tc.index-1].URL != tc.endpoint {
			t.Fatal("incorrect default endpoint", tc)
		}
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != tc.path {
				t.Error("incorrect model endpoint", r.URL.Path)
			}
			if tc.kind == "anthropic" {
				if r.Header.Get("x-api-key") != "secret-test" {
					t.Error("wrong key")
				}
			} else if r.Header.Get("Authorization") != "Bearer secret-test" {
				t.Error("wrong key")
			}
			fmt.Fprint(w, `{"data":[{"id":"test-model"}]}`)
		}))
		providerPresets[tc.index-1].URL = srv.URL
		input := fmt.Sprintf("%d\n", tc.index)
		if tc.index == 1 || tc.index == 2 || tc.index == 6 {
			input += "2\n"
		}
		input += "1\n"
		var out bytes.Buffer
		c := console{in: bufio.NewReader(strings.NewReader(input)), out: &out}
		cfg, key, e := c.setup()
		srv.Close()
		if e != nil || cfg.Provider != tc.kind || cfg.BaseURL != srv.URL || cfg.Model != "test-model" || key != "secret-test" || cfg.Auth != "api_key" {
			t.Fatal(cfg, e, out.String())
		}
		if strings.Contains(out.String(), key) {
			t.Fatal("key leaked")
		}
		providerPresets[tc.index-1] = orig[tc.index-1]
	}
}

func TestUnauthorizedSetupDoesNotPersist(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	t.Setenv("CODEZ_API_KEY", "wrong-secret")
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(401); fmt.Fprint(w, "wrong-secret") }))
	defer srv.Close()
	var out bytes.Buffer
	c := console{in: bufio.NewReader(strings.NewReader("3\n" + srv.URL + "\n")), out: &out}
	_, _, err := c.setup()
	if err == nil || !strings.Contains(err.Error(), "HTTP 401") || !strings.Contains(err.Error(), "CODEZ_API_KEY") {
		t.Fatalf("unexpected error %v", err)
	}
	if strings.Contains(err.Error(), "wrong-secret") || strings.Contains(out.String(), "wrong-secret") {
		t.Fatal("secret leaked")
	}
	if _, err = config.Load(); !os.IsNotExist(err) {
		t.Fatal("invalid configuration persisted", err)
	}
}

func TestModelPickerSearch(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { fmt.Fprint(w, `{"data":[{"id":"alpha"},{"id":"beta"}]}`) }))
	defer srv.Close()
	var out bytes.Buffer
	c := console{in: bufio.NewReader(strings.NewReader("/beta\n1\n")), out: &out}
	model, _, err := c.pickModel(config.Config{Provider: "compatible", BaseURL: srv.URL, Auth: "api_key"}, "", "")
	if err != nil || model != "beta" {
		t.Fatalf("%q %v %s", model, err, out.String())
	}
}

func TestInteractiveKeyOverridesStaleEnvironment(t *testing.T) {
	t.Setenv("CODEZ_API_KEY", "stale-key")
	var out bytes.Buffer
	c := console{in: bufio.NewReader(strings.NewReader("  new-provider-key  \n")), out: &out, interactive: true}
	key, err := c.secret()
	if err != nil || key != "new-provider-key" {
		t.Fatal("interactive input was ignored", err)
	}
	if strings.Contains(out.String(), key) || strings.Contains(out.String(), "stale-key") {
		t.Fatal("credential leaked")
	}
	c.in = bufio.NewReader(strings.NewReader(":env\n"))
	key, err = c.secret()
	if err != nil || key != "stale-key" {
		t.Fatal("explicit environment selection failed", err)
	}
}
