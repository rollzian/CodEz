package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConfigAndSecret(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	c := Config{Provider: "compatible", BaseURL: "http://127.0.0.1:1234/v1", Model: "test"}
	if e := Save(c, "private-key"); e != nil {
		t.Fatal(e)
	}
	got, e := Load()
	if e != nil || got != c {
		t.Fatalf("load: %#v %v", got, e)
	}
	k, e := Secret()
	if e != nil || k != "private-key" {
		t.Fatal("secret mismatch")
	}
	d, _ := Dir()
	b, _ := os.ReadFile(filepath.Join(d, "config.json"))
	if strings.Contains(string(b), k) {
		t.Fatal("key leaked")
	}
	st, _ := os.Stat(filepath.Join(d, "secret"))
	if st.Mode().Perm() != 0600 {
		t.Fatal(st.Mode())
	}
	if e = os.Chmod(filepath.Join(d, "secret"), 0644); e != nil {
		t.Fatal(e)
	}
	if _, e = Secret(); e == nil {
		t.Fatal("insecure secret accepted")
	}
}
func TestValidate(t *testing.T) {
	for _, u := range []string{"http://example.com", "https://user:password@example.com", "https://example.com/?key=secret"} {
		c := Config{Provider: "compatible", BaseURL: u, Model: "m"}
		if c.Validate() == nil {
			t.Fatalf("accepted %s", u)
		}
	}
}
