package tools

import (
	"context"
	"github.com/AuxiaCorp/CodEz/internal/provider"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWriteAndReadInsideWorkspace(t *testing.T) {
	d := t.TempDir()
	r, err := New(d)
	if err != nil {
		t.Fatal(err)
	}
	_, err = r.Execute(context.Background(), provider.ToolCall{Name: "write_file", Arguments: map[string]any{"path": "a/b.txt", "content": "hello"}})
	if err != nil {
		t.Fatal(err)
	}
	got, err := r.Execute(context.Background(), provider.ToolCall{Name: "read_file", Arguments: map[string]any{"path": "a/b.txt"}})
	if err != nil {
		t.Fatal(err)
	}
	if got != "hello" {
		t.Fatalf("got %q", got)
	}
}

func TestTraversalRejected(t *testing.T) {
	r, _ := New(t.TempDir())
	_, err := r.Execute(context.Background(), provider.ToolCall{Name: "write_file", Arguments: map[string]any{"path": "../x", "content": "x"}})
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestSymlinkEscapeRejected(t *testing.T) {
	d := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(d, "link")); err != nil {
		t.Fatal(err)
	}
	r, _ := New(d)
	_, err := r.Execute(context.Background(), provider.ToolCall{Name: "write_file", Arguments: map[string]any{"path": "link/pwn", "content": "x"}})
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestDangerousShellRejected(t *testing.T) {
	r, _ := New(t.TempDir())
	_, err := r.Execute(context.Background(), provider.ToolCall{Name: "shell", Arguments: map[string]any{"command": "sudo rm -rf /"}})
	if err == nil || !strings.Contains(err.Error(), "manual approval") {
		t.Fatalf("unexpected: %v", err)
	}
}

func TestNestedSymlinkEscapeRejected(t *testing.T) {
	d := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(d, "link")); err != nil {
		t.Fatal(err)
	}
	r, _ := New(d)
	_, err := r.Execute(context.Background(), provider.ToolCall{Name: "write_file", Arguments: map[string]any{"path": "link/newdir/pwn", "content": "x"}})
	if err == nil {
		t.Fatal("expected nested symlink escape error")
	}
}

func TestGrepDoesNotFollowSymlinks(t *testing.T) {
	d := t.TempDir()
	outside := filepath.Join(t.TempDir(), "secret.txt")
	if err := os.WriteFile(outside, []byte("unique-private-marker"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(d, "link")); err != nil {
		t.Fatal(err)
	}
	r, _ := New(d)
	out, err := r.Execute(context.Background(), provider.ToolCall{Name: "grep", Arguments: map[string]any{"query": "unique-private-marker"}})
	if err != nil || out != "" {
		t.Fatalf("leaked: %q, %v", out, err)
	}
}
func TestExactReadLimit(t *testing.T) {
	d := t.TempDir()
	r, _ := New(d)
	if err := os.WriteFile(filepath.Join(d, "file"), []byte(strings.Repeat("a", 1<<20)), 0600); err != nil {
		t.Fatal(err)
	}
	out, err := r.Execute(context.Background(), provider.ToolCall{Name: "read_file", Arguments: map[string]any{"path": "file"}})
	if err != nil || len(out) != 1<<20 {
		t.Fatalf("len=%d, err=%v", len(out), err)
	}
}
func TestShellSecretEnvironment(t *testing.T) {
	t.Setenv("CODEZ_API_KEY", "private-key")
	r, _ := New(t.TempDir())
	out, err := r.Execute(context.Background(), provider.ToolCall{Name: "shell", Arguments: map[string]any{"command": "printf '%s' \"$CODEZ_API_KEY\""}})
	if err != nil || out != "" {
		t.Fatalf("secret exposed: %q, %v", out, err)
	}
}

func TestReplaceTextExact(t *testing.T) {
	d := t.TempDir()
	r, _ := New(d)
	p := filepath.Join(d, "file")
	os.WriteFile(p, []byte("user-change\nold\n"), 0600)
	_, e := r.Execute(context.Background(), provider.ToolCall{Name: "replace_text", Arguments: map[string]any{"path": "file", "old": "old", "new": "new"}})
	if e != nil {
		t.Fatal(e)
	}
	b, _ := os.ReadFile(p)
	if string(b) != "user-change\nnew\n" {
		t.Fatal(string(b))
	}
	if _, e = r.Execute(context.Background(), provider.ToolCall{Name: "replace_text", Arguments: map[string]any{"path": "file", "old": "old", "new": "bad"}}); e == nil {
		t.Fatal("missing match accepted")
	}
}

func TestMissingWriteContentCannotEraseFile(t *testing.T) {
	d := t.TempDir()
	r, _ := New(d)
	p := filepath.Join(d, "file")
	if e := os.WriteFile(p, []byte("existing"), 0600); e != nil {
		t.Fatal(e)
	}
	_, e := r.Execute(context.Background(), provider.ToolCall{Name: "write_file", Arguments: map[string]any{"path": "file"}})
	if e == nil {
		t.Fatal("missing content accepted")
	}
	b, _ := os.ReadFile(p)
	if string(b) != "existing" {
		t.Fatal("file changed")
	}
}
