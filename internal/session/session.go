package session

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type Event struct {
	Time    time.Time `json:"time"`
	Role    string    `json:"role"`
	Content string    `json:"content"`
}

type Store struct{ path string }

func stateHome() string {
	if v := os.Getenv("XDG_STATE_HOME"); v != "" {
		return v
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "state")
}

func New(root string) (*Store, error) {
	sum := sha256.Sum256([]byte(root))
	dir := filepath.Join(stateHome(), "codez", "sessions")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	return &Store{path: filepath.Join(dir, hex.EncodeToString(sum[:8])+".jsonl")}, nil
}

func (s *Store) Append(role, content string) error {
	f, err := os.OpenFile(s.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return err
	}
	defer f.Close()
	return json.NewEncoder(f).Encode(Event{Time: time.Now().UTC(), Role: role, Content: content})
}

func (s *Store) Recent(limit int) ([]Event, error) {
	f, err := os.Open(s.path)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var all []Event
	sc := bufio.NewScanner(f)
	buf := make([]byte, 64*1024)
	sc.Buffer(buf, 2<<20)
	for sc.Scan() {
		var e Event
		if err := json.Unmarshal(sc.Bytes(), &e); err != nil {
			return nil, fmt.Errorf("corrupt session: %w", err)
		}
		if limit > 0 {
			if len(all) == limit {
				copy(all, all[1:])
				all = all[:limit-1]
			}
			all = append(all, e)
		}
	}

	return all, sc.Err()
}
