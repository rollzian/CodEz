package session

import (
	"fmt"
	"testing"
)

func TestRecent(t *testing.T) {
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	s, e := New("/tmp/work")
	if e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 100; i++ {
		if e = s.Append("user", fmt.Sprint(i)); e != nil {
			t.Fatal(e)
		}
	}
	rows, e := s.Recent(3)
	if e != nil || len(rows) != 3 || rows[0].Content != "97" || rows[2].Content != "99" {
		t.Fatalf("%#v %v", rows, e)
	}
}
