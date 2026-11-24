package session

import (
	"strings"
	"testing"
)

func TestChatIsolation(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	a, e := New("/one")
	if e != nil {
		t.Fatal(e)
	}
	if e = a.Append("user", "first prompt"); e != nil {
		t.Fatal(e)
	}
	b, e := a.Create()
	if e != nil {
		t.Fatal(e)
	}
	if e = b.Append("user", "second prompt"); e != nil {
		t.Fatal(e)
	}
	other, _ := New("/two")
	if _, e = other.Open(b.ID()); e == nil {
		t.Fatal("cross-workspace chat")
	}
	if _, e = a.Open("../" + b.ID()); e == nil {
		t.Fatal("path escape")
	}
	rows, e := a.List()
	if e != nil || len(rows) != 2 {
		t.Fatal(rows, e)
	}
	names := rows[0].Title + rows[1].Title
	if !strings.Contains(names, "first prompt") || !strings.Contains(names, "second prompt") {
		t.Fatal(rows)
	}
	saved, e := b.Open(a.ID())
	if e != nil {
		t.Fatal(e)
	}
	events, e := saved.Recent(10)
	if e != nil || len(events) != 1 || events[0].Content != "first prompt" {
		t.Fatal(events, e)
	}
	if e = b.Sync(); e != nil {
		t.Fatal(e)
	}
}
func TestActiveChatPersists(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	s, e := New("/project")
	if e != nil {
		t.Fatal(e)
	}
	next, e := s.Create()
	if e != nil {
		t.Fatal(e)
	}
	if e = next.SelectActive(); e != nil {
		t.Fatal(e)
	}
	active, e := s.Active()
	if e != nil || active.ID() != next.ID() {
		t.Fatal(active, e)
	}
}
