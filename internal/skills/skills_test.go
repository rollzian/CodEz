package skills

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDiscoverAndRead(t *testing.T) {
	root, user := t.TempDir(), t.TempDir()
	path := filepath.Join(root, ".codez", "skills", "review")
	if e := os.MkdirAll(path, 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(path, "SKILL.md"), []byte("# Review\nCheck test integrity"), 0600); e != nil {
		t.Fatal(e)
	}
	if e := os.Symlink(path, filepath.Join(root, ".codez", "skills", "alias")); e != nil {
		t.Fatal(e)
	}
	ss, e := Discover(root, user)
	if e != nil || len(ss) != 1 || ss[0].ID != "workspace/review" {
		t.Fatal(ss, e)
	}
	body, e := ss[0].Read()
	if e != nil || body != "# Review\nCheck test integrity" {
		t.Fatal(body, e)
	}
	os.Remove(ss[0].Path)
	if e = os.Symlink(filepath.Join(user, "secret"), ss[0].Path); e != nil {
		t.Fatal(e)
	}
	if _, e = ss[0].Read(); e == nil {
		t.Fatal("followed skill symlink")
	}
}
