package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode"
)

type composer struct {
	text         []rune
	cursor       int
	history      []string
	historyIndex int
	historyDraft string
}

func (d *composer) set(s string) { d.text = []rune(s); d.cursor = len(d.text) }
func (d *composer) insert(r rune) {
	if len(d.text) >= 32768 {
		return
	}
	d.text = append(d.text, 0)
	copy(d.text[d.cursor+1:], d.text[d.cursor:])
	d.text[d.cursor] = r
	d.cursor++
}
func (d *composer) erase() {
	if d.cursor > 0 {
		copy(d.text[d.cursor-1:], d.text[d.cursor:])
		d.text = d.text[:len(d.text)-1]
		d.cursor--
	}
}
func (d *composer) remember(s string) {
	if s == "" || strings.HasPrefix(s, "/") {
		return
	}
	if len(d.history) == 0 || d.history[len(d.history)-1] != s {
		d.history = append(d.history, s)
		if len(d.history) > 100 {
			d.history = d.history[len(d.history)-100:]
		}
	}
	d.historyIndex = len(d.history)
	d.historyDraft = ""
}
func (d *composer) recall(delta int) {
	if len(d.history) == 0 {
		return
	}
	if d.historyIndex == len(d.history) {
		d.historyDraft = string(d.text)
	}
	d.historyIndex = max(0, min(len(d.history), d.historyIndex+delta))
	if d.historyIndex == len(d.history) {
		d.set(d.historyDraft)
	} else {
		d.set(d.history[d.historyIndex])
	}
}
func (d *composer) reset() { d.set(""); d.historyIndex = len(d.history); d.historyDraft = "" }

// Escape codes are decoded separately from ordinary UTF-8 text.
func (c console) editKey(ctx context.Context) (string, rune, error) {
	b, e := c.menuByte(ctx, time.Time{})
	if e != nil {
		return "", 0, e
	}
	if b == 27 {
		deadline := time.Now().Add(100 * time.Millisecond)
		first, e := c.menuByte(ctx, deadline)
		if e != nil {
			return "escape", 0, nil
		}
		if first != '[' && first != 'O' {
			return "ignored", 0, nil
		}
		var seq strings.Builder
		for i := 0; i < 24; i++ {
			v, e := c.menuByte(ctx, deadline)
			if e != nil {
				return "ignored", 0, nil
			}
			seq.WriteByte(v)
			if v >= 0x40 && v <= 0x7e {
				break
			}
		}
		return seq.String(), 0, nil
	}
	if b < 32 || b == 127 {
		return "ctrl:" + strconv.Itoa(int(b)), 0, nil
	}
	if e = c.in.UnreadByte(); e != nil {
		return "", 0, e
	}
	r, _, e := c.in.ReadRune()
	return "text", r, e
}
func (c console) paste(ctx context.Context, d *composer) error {
	const end = "\x1b[201~"
	var data strings.Builder
	for {
		b, e := c.menuByte(ctx, time.Time{})
		if e != nil {
			return e
		}
		data.WriteByte(b)
		if strings.HasSuffix(data.String(), end) {
			break
		}
		if data.Len() > 4*32768+len(end) {
			return fmt.Errorf("paste exceeds input limit")
		}
	}
	pending := strings.TrimSuffix(data.String(), end)
	for _, r := range strings.ReplaceAll(pending, "\r\n", "\n") {
		if r == '\r' {
			r = '\n'
		}
		if r == '\n' || r == '\t' || !unicode.IsControl(r) {
			d.insert(r)
		}
	}
	return nil
}
func (c console) drawComposer(d *composer, width int) {
	// A bounded, horizontally scrolling input line; pasted newlines are displayed as spaces.
	cap := max(1, width-8)
	start := max(0, d.cursor-cap)
	end := min(len(d.text), start+cap)
	s := strings.Map(func(r rune) rune {
		if r == '\n' || r == '\t' {
			return ' '
		}
		return r
	}, string(d.text[start:end]))
	fmt.Fprintf(c.out, "\r\x1b[2K  %s %s", c.style(accent, "❯"), clean(s))
	if n := end - d.cursor; n > 0 {
		fmt.Fprintf(c.out, "\x1b[%dD", n)
	}
}
func (c console) readPrompt(d *composer, mode agentMode) (string, error) {
	if !c.rich || os.Getenv("CODEZ_SIMPLE_UI") != "" {
		return c.ask(c.prompt())
	}
	saved, e := ttyCommand("-g")
	if e != nil {
		return "", e
	}
	size, _ := ttyCommand("size")
	width := 80
	if p := strings.Fields(size); len(p) == 2 {
		if n, e := strconv.Atoi(p[1]); e == nil && n > 0 {
			width = n
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
	defer stop()
	if _, e = ttyCommand("-icanon", "-echo", "-isig", "-ixon", "min", "1", "time", "0"); e != nil {
		return "", e
	}
	submitted := ""
	defer func() {
		_, _ = ttyCommand(saved)
		fmt.Fprint(c.out, "\x1b[?2004l\r\x1b[2K")
		if submitted != "" {
			fmt.Fprint(c.out, "  "+c.style(accent, "❯")+" "+clean(submitted))
		}
		fmt.Fprintln(c.out)
	}()
	fmt.Fprint(c.out, "\x1b[?2004h\n  "+c.style(muted, "← Chats   Ctrl+K Menu   Shift+Tab "+string(mode))+"\n")
	for {
		c.drawComposer(d, width)
		k, r, e := c.editKey(ctx)
		if e != nil {
			if ctx.Err() != nil {
				return "", io.EOF
			}
			return "", e
		}
		switch k {
		case "text":
			if !unicode.IsControl(r) {
				d.insert(r)
			}
		case "ctrl:13", "ctrl:10":
			s := strings.TrimSpace(string(d.text))
			d.remember(s)
			d.reset()
			submitted = s
			return s, nil
		case "ctrl:3":
			d.reset()
			return "", context.Canceled
		case "ctrl:4":
			if len(d.text) == 0 {
				return "", io.EOF
			}
			if d.cursor < len(d.text) {
				d.text = append(d.text[:d.cursor], d.text[d.cursor+1:]...)
			}
		case "ctrl:127":
			d.erase()
		case "ctrl:8":
			if len(d.text) == 0 {
				return "/history", nil
			}
			d.erase()
		case "D":
			if len(d.text) == 0 {
				return "/chats", nil
			}
			d.cursor = max(0, d.cursor-1)
		case "C":
			d.cursor = min(len(d.text), d.cursor+1)
		case "A":
			d.recall(-1)
		case "B":
			d.recall(1)
		case "H", "1~", "ctrl:1":
			d.cursor = 0
		case "F", "4~", "ctrl:5":
			d.cursor = len(d.text)
		case "3~":
			if d.cursor < len(d.text) {
				d.text = append(d.text[:d.cursor], d.text[d.cursor+1:]...)
			}
		case "200~":
			if e = c.paste(ctx, d); e != nil {
				return "", e
			}
		case "1;5D", "5D":
			return "/workspaces", nil
		case "1;5C", "5C":
			return "/teams", nil
		case "1;5A", "5A":
			return "/friends", nil
		case "1;5B", "5B":
			return "/projects", nil
		case "ctrl:11":
			return "/menu", nil
		case "ctrl:14":
			return "/new", nil
		case "ctrl:16":
			return "/model", nil
		case "ctrl:6":
			return "/search-chats", nil
		case "ctrl:19":
			return "/save", nil
		case "ctrl:12":
			return "/clear", nil
		case "ctrl:18":
			d.recall(-1)
		case "Z":
			return "/mode-next", nil
		case "escape":
			return "", nil
		case "ctrl:9":
			completeCommand(d)
		}
	}
}
func completeCommand(d *composer) {
	s := string(d.text)
	if !strings.HasPrefix(s, "/") || strings.ContainsAny(s, " \n\t") {
		return
	}
	match := ""
	for _, cmd := range []string{"/menu", "/model", "/models", "/setup", "/auxia", "/workspaces", "/teams", "/friends", "/projects", "/chats", "/search-chats", "/history", "/new", "/resume", "/save", "/mode", "/skills", "/doctor", "/status", "/clear", "/exit", "/help"} {
		if strings.HasPrefix(cmd, s) {
			if match != "" {
				return
			}
			match = cmd
		}
	}
	if match != "" {
		d.set(match + " ")
	}
}
