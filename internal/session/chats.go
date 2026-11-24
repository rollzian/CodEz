package session

import (
	"bufio"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Chat struct {
	ID, Title string
	Modified  time.Time
}

// ID is scoped to the existing workspace's session namespace.
func (s *Store) ID() string     { return strings.TrimSuffix(filepath.Base(s.path), ".jsonl") }
func (s *Store) prefix() string { return strings.SplitN(s.ID(), "-", 2)[0] }
func (s *Store) validID(id string) bool {
	if id == s.prefix() {
		return true
	}
	if !strings.HasPrefix(id, s.prefix()+"-") {
		return false
	}
	suffix := strings.TrimPrefix(id, s.prefix()+"-")
	_, err := hex.DecodeString(suffix)
	return len(suffix) == 32 && err == nil
}
func (s *Store) Open(id string) (*Store, error) {
	if !s.validID(id) {
		return nil, errors.New("invalid chat ID")
	}
	path := filepath.Join(filepath.Dir(s.path), id+".jsonl")
	info, err := os.Lstat(path)
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() {
		return nil, errors.New("invalid chat file")
	}
	return &Store{path: path}, nil
}
func (s *Store) Create() (*Store, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return nil, err
	}
	next := &Store{path: filepath.Join(filepath.Dir(s.path), s.prefix()+"-"+hex.EncodeToString(b[:])+".jsonl")}
	f, err := os.OpenFile(next.path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	return next, f.Close()
}
func (s *Store) title() string {
	f, err := os.Open(s.path)
	if err != nil {
		return "Untitled chat"
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 4096), 2<<20)
	for i := 0; i < 20 && sc.Scan(); i++ {
		var event Event
		if json.Unmarshal(sc.Bytes(), &event) == nil && event.Role == "user" {
			r := []rune(strings.Join(strings.Fields(event.Content), " "))
			if len(r) > 70 {
				r = append(r[:69], '…')
			}
			if len(r) > 0 {
				return string(r)
			}
		}
	}
	return "Untitled chat"
}
func (s *Store) List() ([]Chat, error) {
	entries, err := os.ReadDir(filepath.Dir(s.path))
	if err != nil {
		return nil, err
	}
	var chats []Chat
	for _, entry := range entries {
		if !strings.HasSuffix(entry.Name(), ".jsonl") || !s.validID(strings.TrimSuffix(entry.Name(), ".jsonl")) {
			continue
		}
		info, e := entry.Info()
		if e != nil {
			return nil, e
		}
		if !info.Mode().IsRegular() {
			continue
		}
		chats = append(chats, Chat{ID: strings.TrimSuffix(entry.Name(), ".jsonl"), Modified: info.ModTime()})
	}
	sort.Slice(chats, func(i, j int) bool {
		return chats[i].Modified.After(chats[j].Modified) || chats[i].Modified.Equal(chats[j].Modified) && chats[i].ID < chats[j].ID
	})
	// Bound metadata reads; all on-disk histories remain intact.
	if len(chats) > 500 {
		chats = chats[:500]
	}
	for i := range chats {
		chats[i].Title = (&Store{path: filepath.Join(filepath.Dir(s.path), chats[i].ID+".jsonl")}).title()
	}
	return chats, nil
}
func (s *Store) Sync() error {
	f, e := os.OpenFile(s.path, os.O_CREATE|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	defer f.Close()
	return f.Sync()
}

// Remember the current conversation without changing or deleting its history.
func (s *Store) SelectActive() error {
	f, err := os.CreateTemp(filepath.Dir(s.path), ".active-")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.WriteString(s.ID()); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), filepath.Join(filepath.Dir(s.path), s.prefix()+".active"))
}
func (s *Store) Active() (*Store, error) {
	path := filepath.Join(filepath.Dir(s.path), s.prefix()+".active")
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Size() > 64 {
		return nil, errors.New("invalid active chat marker")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if string(b) == s.ID() {
		return s, nil
	}
	return s.Open(string(b))
}
