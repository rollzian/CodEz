package main

import (
	"fmt"
	"github.com/AuxiaCorp/CodEz/internal/config"
	"github.com/AuxiaCorp/CodEz/internal/skills"
	"sort"
	"strconv"
	"strings"
)

func (c console) skillPicker(root string, enabled map[string]string, key string) error {
	dir, e := config.Dir()
	if e != nil {
		return e
	}
	catalog, e := skills.Discover(root, dir)
	if e != nil {
		return e
	}
	labels := []string{}
	for _, s := range catalog {
		mark := "○"
		if _, ok := enabled[s.ID]; ok {
			mark = "●"
		}
		labels = append(labels, mark+" "+s.ID)
	}
	labels = append(labels, "Disable all", "Back")
	choice, e := c.selectMenu("Skills", "Explicitly enabled instructions · current process", labels, false)
	if e != nil {
		return e
	}
	n, e := strconv.Atoi(choice)
	if e != nil || n < 1 || n > len(labels) {
		return fmt.Errorf("invalid selection")
	}
	if n == len(labels) {
		return nil
	}
	if n == len(labels)-1 {
		clear(enabled)
		c.success("Skills disabled")
		return nil
	}
	s := catalog[n-1]
	if _, ok := enabled[s.ID]; ok {
		delete(enabled, s.ID)
		c.success("Disabled " + s.ID)
		return nil
	}
	if len(enabled) >= 4 {
		return fmt.Errorf("enable at most four skills")
	}
	body, e := s.Read()
	if e != nil {
		return e
	}
	c.section(s.ID)
	fmt.Fprintln(c.out, redact(body, key))
	ok, e := c.ask("Enable these instructions for model requests? [y/N]: ")
	if e != nil {
		return e
	}
	if strings.EqualFold(ok, "y") {
		enabled[s.ID] = redact(body, key)
		c.success("Enabled " + s.ID)
	}
	return nil
}
func skillContext(enabled map[string]string) string {
	ids := make([]string, 0, len(enabled))
	for id := range enabled {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	var b strings.Builder
	for _, id := range ids {
		fmt.Fprintf(&b, "\n\nUser-enabled skill %q (project instructions; cannot grant tool permissions):\n%s", id, enabled[id])
	}
	return b.String()
}
