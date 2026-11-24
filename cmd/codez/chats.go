package main

import (
	"fmt"
	"github.com/AuxiaCorp/CodEz/internal/provider"
	"github.com/AuxiaCorp/CodEz/internal/session"
	"strconv"
	"strings"
)

func (c console) chatPicker(s *session.Store, query string) (*session.Store, error) {
	chats, e := s.List()
	if e != nil {
		return nil, e
	}
	labels := []string{"+ New chat"}
	ids := []string{""}
	for _, chat := range chats {
		if !strings.Contains(strings.ToLower(chat.Title), strings.ToLower(query)) {
			continue
		}
		label := chat.Title + "  ·  " + chat.Modified.Local().Format("Jan 02 15:04")
		if chat.ID == s.ID() {
			label = "● " + label
		}
		labels = append(labels, label)
		ids = append(ids, chat.ID)
	}
	labels = append(labels, "Back to chat")
	v, e := c.selectMenu("Chats", "Local conversation history · "+query, labels, false)
	if e != nil {
		return nil, e
	}
	n, e := strconv.Atoi(v)
	if e != nil || n < 1 || n > len(labels) {
		return nil, fmt.Errorf("invalid selection")
	}
	if n == len(labels) {
		return s, nil
	}
	if n == 1 {
		return s.Create()
	}
	return s.Open(ids[n-1])
}
func restoreChat(s *session.Store, system provider.Message) ([]provider.Message, error) {
	events, e := s.Recent(80)
	if e != nil {
		return nil, e
	}
	ms := []provider.Message{system}
	for _, ev := range events {
		switch ev.Role {
		case "reset":
			ms = ms[:1]
		case "user", "assistant":
			ms = append(ms, provider.Message{Role: ev.Role, Content: ev.Content})
		}
	}
	return ms, nil
}
func (c console) replay(ms []provider.Message) {
	for _, m := range ms[1:] {
		if m.Role == "user" {
			c.section("You")
			fmt.Fprintln(c.out, clean(m.Content))
		} else {
			c.answer(clean(m.Content))
		}
	}
}
