package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"github.com/AuxiaCorp/CodEz/internal/provider"
)

type Registry struct{ Root string }

func New(root string) (*Registry, error) {
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	real, err := filepath.EvalSymlinks(abs)
	if err != nil {
		return nil, err
	}
	return &Registry{Root: real}, nil
}

func (r *Registry) Definitions() []provider.ToolDef {
	return []provider.ToolDef{
		{Name: "list_files", Description: "List repository files", Schema: obj(map[string]any{"path": str()}, []string{})},
		{Name: "read_file", Description: "Read a UTF-8 text file in the repository", Schema: obj(map[string]any{"path": str()}, []string{"path"})},
		{Name: "write_file", Description: "Atomically create or replace a text file in the repository", Schema: obj(map[string]any{"path": str(), "content": str()}, []string{"path", "content"})},
		{Name: "replace_text", Description: "Replace one exact occurrence of old text with new text in an existing file; rejects missing or ambiguous matches", Schema: obj(map[string]any{"path": str(), "old": str(), "new": str()}, []string{"path", "old", "new"})},
		{Name: "grep", Description: "Search text in repository files", Schema: obj(map[string]any{"query": str(), "path": str()}, []string{"query"})},
		{Name: "shell", Description: "Run a shell command in the repository", Schema: obj(map[string]any{"command": str()}, []string{"command"})},
		{Name: "git_status", Description: "Show git status", Schema: obj(map[string]any{}, []string{})},
		{Name: "git_diff", Description: "Show git diff", Schema: obj(map[string]any{}, []string{})},
	}
}

func str() map[string]any { return map[string]any{"type": "string"} }
func obj(props map[string]any, req []string) map[string]any {
	return map[string]any{"type": "object", "properties": props, "required": req, "additionalProperties": false}
}

func (r *Registry) Execute(ctx context.Context, c provider.ToolCall) (string, error) {
	for _, def := range r.Definitions() {
		if def.Name != c.Name {
			continue
		}
		props, _ := def.Schema["properties"].(map[string]any)
		required, _ := def.Schema["required"].([]string)
		for _, name := range required {
			if _, ok := c.Arguments[name]; !ok {
				return "", fmt.Errorf("missing required argument %q", name)
			}
		}
		for name, value := range c.Arguments {
			if _, ok := props[name]; !ok {
				return "", fmt.Errorf("unknown argument %q", name)
			}
			if _, ok := value.(string); !ok {
				return "", fmt.Errorf("argument %q must be a string", name)
			}
		}
		break
	}
	switch c.Name {
	case "list_files":
		return r.listFiles(asString(c.Arguments["path"]))
	case "read_file":
		return r.readFile(asString(c.Arguments["path"]))
	case "write_file":
		return r.writeFile(asString(c.Arguments["path"]), asString(c.Arguments["content"]))
	case "replace_text":
		return r.replaceText(asString(c.Arguments["path"]), asString(c.Arguments["old"]), asString(c.Arguments["new"]))
	case "grep":
		return r.grep(asString(c.Arguments["query"]), asString(c.Arguments["path"]))
	case "shell":
		return r.shell(ctx, asString(c.Arguments["command"]))
	case "git_status":
		return r.cmd(ctx, 15*time.Second, "git", "status", "--short", "--branch")
	case "git_diff":
		return r.cmd(ctx, 20*time.Second, "git", "diff", "--no-ext-diff", "--no-textconv", "--")
	default:
		return "", fmt.Errorf("unknown tool %q", c.Name)
	}
}

func asString(v any) string { s, _ := v.(string); return s }

func (r *Registry) resolve(path string, mustExist bool) (string, error) {
	if path == "" {
		path = "."
	}
	if filepath.IsAbs(path) {
		return "", errors.New("absolute paths are not allowed")
	}
	clean := filepath.Clean(path)
	if clean == ".." || strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
		return "", errors.New("path escapes workspace")
	}
	joined := filepath.Join(r.Root, clean)
	check := joined
	if !mustExist {
		check = filepath.Dir(joined)
	}
	ancestor := check
	for {
		_, err := os.Lstat(ancestor)
		if err == nil {
			break
		}
		if !errors.Is(err, fs.ErrNotExist) {
			return "", err
		}
		next := filepath.Dir(ancestor)
		if next == ancestor {
			return "", errors.New("no existing workspace ancestor")
		}
		ancestor = next
	}
	realAncestor, err := filepath.EvalSymlinks(ancestor)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(r.Root, realAncestor)
	if err != nil {
		return "", err
	}
	if rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return "", errors.New("symlink escapes workspace")
	}
	if mustExist {
		real, err := filepath.EvalSymlinks(joined)
		if err != nil {
			return "", err
		}
		rel, err = filepath.Rel(r.Root, real)
		if err != nil {
			return "", err
		}
		if rel == ".." || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
			return "", errors.New("path escapes workspace")
		}
		return real, nil
	}
	return joined, nil
}

func (r *Registry) listFiles(path string) (string, error) {
	start, err := r.resolve(path, true)
	if err != nil {
		return "", err
	}
	var out []string
	err = filepath.WalkDir(start, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		rel, _ := filepath.Rel(r.Root, p)
		if d.IsDir() {
			if d.Name() == ".git" || d.Name() == "node_modules" || d.Name() == "target" || d.Name() == "dist" || d.Name() == "build" || d.Name() == "vendor" {
				return filepath.SkipDir
			}
			return nil
		}
		if len(out) >= 500 {
			return fs.SkipAll
		}
		if d.Type().IsRegular() {
			out = append(out, rel)
		}
		return nil
	})
	sort.Strings(out)
	return strings.Join(out, "\n"), err
}

func (r *Registry) readFile(path string) (string, error) {
	p, err := r.resolve(path, true)
	if err != nil {
		return "", err
	}
	st, err := os.Stat(p)
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() {
		return "", errors.New("not a regular file")
	}
	f, err := os.Open(p)
	if err != nil {
		return "", err
	}
	defer f.Close()
	st, err = f.Stat()
	if err != nil {
		return "", err
	}
	if !st.Mode().IsRegular() {
		return "", errors.New("not a regular file")
	}
	b, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil {
		return "", err
	}
	if len(b) > 1<<20 {
		return "", errors.New("file exceeds 1 MiB read limit")
	}
	return string(b), nil
}

func (r *Registry) writeFile(path, content string) (string, error) {
	p, err := r.resolve(path, false)
	if err != nil {
		return "", err
	}
	if st, e := os.Lstat(p); e == nil && !st.Mode().IsRegular() {
		return "", errors.New("write target is not a regular file")
	}
	for _, part := range strings.Split(filepath.Clean(path), string(os.PathSeparator)) {
		if part == ".git" {
			return "", errors.New("git metadata writes denied")
		}
	}
	if len(content) > 4<<20 {
		return "", errors.New("write exceeds 4 MiB limit")
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return "", err
	}
	mode := fs.FileMode(0o644)
	if st, err := os.Stat(p); err == nil {
		mode = st.Mode().Perm()
	}
	tmp, err := os.CreateTemp(filepath.Dir(p), ".codez-write-*")
	if err != nil {
		return "", err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return "", err
	}
	if _, err := tmp.WriteString(content); err != nil {
		tmp.Close()
		return "", err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return "", err
	}
	if err := tmp.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(tmpName, p); err != nil {
		return "", err
	}
	return "wrote " + path, nil
}

func (r *Registry) replaceText(path, old, new string) (string, error) {
	if old == "" {
		return "", errors.New("old text cannot be empty")
	}
	content, e := r.readFile(path)
	if e != nil {
		return "", e
	}
	if strings.Count(content, old) != 1 {
		return "", errors.New("expected exactly one match; reread file and use a unique old text")
	}
	return r.writeFile(path, strings.Replace(content, old, new, 1))
}

func (r *Registry) grep(q, path string) (string, error) {
	if q == "" {
		return "", errors.New("query required")
	}
	base, err := r.resolve(path, true)
	if err != nil {
		return "", err
	}
	var hits []string
	_ = filepath.WalkDir(base, func(p string, d fs.DirEntry, err error) error {
		if len(hits) >= 200 {
			return fs.SkipAll
		}
		if err != nil {
			return nil
		}
		if d.IsDir() {
			name := d.Name()
			if name == ".git" || name == "node_modules" || name == "target" || name == "dist" || name == "build" {
				return filepath.SkipDir
			}
			return nil
		}
		if !d.Type().IsRegular() {
			return nil
		}
		st, e := d.Info()
		if e != nil || st.Size() > 1<<20 {
			return nil
		}
		f, e := os.Open(p)
		if e != nil {
			return nil
		}
		b, e := io.ReadAll(io.LimitReader(f, (1<<20)+1))
		f.Close()
		if e != nil || len(b) > 1<<20 || bytes.IndexByte(b, 0) >= 0 {
			return nil
		}
		for i, line := range strings.Split(string(b), "\n") {
			if strings.Contains(strings.ToLower(line), strings.ToLower(q)) {
				rel, _ := filepath.Rel(r.Root, p)
				hits = append(hits, fmt.Sprintf("%s:%d:%s", rel, i+1, line))
				if len(hits) >= 200 {
					break
				}
			}
		}
		return nil
	})
	return strings.Join(hits, "\n"), nil
}

func (r *Registry) shell(ctx context.Context, command string) (string, error) {
	if command == "" {
		return "", errors.New("command required")
	}
	if risky(command) {
		return "", fmt.Errorf("command requires manual approval: %s", command)
	}
	cctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	cmd := exec.Command("/bin/sh", "-lc", command)
	cmd.Dir = r.Root
	cmd.Env = safeEnvironment()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.WaitDelay = 3 * time.Second
	var out bytes.Buffer
	w := &limitedBuffer{b: &out, max: 2 << 20}
	cmd.Stdout = w
	cmd.Stderr = w
	if err := cmd.Start(); err != nil {
		return "", err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			return out.String(), fmt.Errorf("%w\n%s", err, out.String())
		}
		return out.String(), nil
	case <-cctx.Done():
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
		<-done
		return out.String(), cctx.Err()
	}
}

func safeEnvironment() []string {
	var env []string
	for _, v := range os.Environ() {
		name, _, _ := strings.Cut(v, "=")
		n := strings.ToUpper(name)
		if strings.Contains(n, "TOKEN") || strings.Contains(n, "SECRET") || strings.Contains(n, "PASSWORD") || strings.Contains(n, "API_KEY") || strings.Contains(n, "PRIVATE_KEY") {
			continue
		}
		env = append(env, v)
	}
	return env
}

func risky(s string) bool {
	low := strings.ToLower(s)
	bad := []string{"sudo ", "rm -rf /", "mkfs", "dd if=", "git reset --hard", "git clean -fd", "git push --force", "> /etc/", "systemctl ", "shutdown", "reboot"}
	for _, b := range bad {
		if strings.Contains(low, b) {
			return true
		}
	}
	return false
}

type limitedBuffer struct {
	b   *bytes.Buffer
	max int
}

func (l *limitedBuffer) Write(p []byte) (int, error) {
	n := len(p)
	remain := l.max - l.b.Len()
	if remain > 0 {
		if len(p) > remain {
			p = p[:remain]
		}
		_, _ = l.b.Write(p)
	}
	return n, nil
}

func (r *Registry) cmd(ctx context.Context, timeout time.Duration, name string, args ...string) (string, error) {
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(cctx, name, args...)
	cmd.Dir = r.Root
	var b bytes.Buffer
	w := &limitedBuffer{b: &b, max: 2 << 20}
	cmd.Stdout = w
	cmd.Stderr = w
	err := cmd.Run()
	return b.String(), err
}

func JSON(v any) string { b, _ := json.Marshal(v); return string(b) }
