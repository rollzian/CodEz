package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func ttyCommand(args ...string) (string, error) {
	cmd := exec.Command("stty", args...)
	cmd.Stdin = os.Stdin
	b, e := cmd.Output()
	return strings.TrimSpace(string(b)), e
}

// The alternate-screen selector never consumes the normal agent transcript.
// Restore the exact previous terminal settings, including on cancellation.
func (c console) selectMenu(title, subtitle string, items []string, actions bool) (string, error) {
	if !c.rich || os.Getenv("CODEZ_SIMPLE_UI") != "" {
		c.section(title)
		if subtitle != "" {
			c.note(subtitle)
		}
		for i, item := range items {
			fmt.Fprintf(c.out, "  %s  %s\n", c.style(accent, fmt.Sprintf("%2d", i+1)), item)
		}
		if actions {
			return c.ask("  Select number · /search · next/prev · filter · q: ")
		}
		return c.ask(fmt.Sprintf("  Select [1-%d]: ", len(items)))
	}
	saved, e := ttyCommand("-g")
	if e != nil {
		return "", fmt.Errorf("terminal settings: %w", e)
	}
	size, _ := ttyCommand("size")
	height, width := 24, 80
	if parts := strings.Fields(size); len(parts) == 2 {
		if v, e := strconv.Atoi(parts[0]); e == nil && v > 0 {
			height = v
		}
		if v, e := strconv.Atoi(parts[1]); e == nil && v > 0 {
			width = v
		}
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
	defer stop()
	if _, e = ttyCommand("-icanon", "-echo", "-isig", "min", "1", "time", "0"); e != nil {
		return "", e
	}
	defer func() { _, _ = ttyCommand(saved); fmt.Fprint(c.out, "\x1b[?25h\x1b[?1049l") }()
	fmt.Fprint(c.out, "\x1b[?1049h\x1b[?25l")
	focus := 0
	first := 0
	count := max(1, height-8)
	for {
		if focus < first {
			first = focus
		}
		if focus >= first+count {
			first = focus - count + 1
		}
		c.drawMenu(title, subtitle, items, actions, focus, first, count, width)
		k, e := c.menuKey(ctx)
		if e != nil {
			return "", e
		}
		switch k {
		case "up", "k":
			focus = max(0, focus-1)
		case "down", "j":
			focus = min(max(0, len(items)-1), focus+1)
		case "enter":
			if len(items) > 0 {
				return strconv.Itoa(focus + 1), nil
			}
		case "escape", "q":
			return "", errors.New("selection cancelled")
		case "left", "p":
			if actions {
				return "prev", nil
			}
		case "right", "n":
			if actions {
				return "next", nil
			}
		case "/":
			if actions {
				return "/", nil
			}
		case "tab", "f":
			if actions {
				return "filter", nil
			}
		}
	}
}
func clipLine(s string, width int) string {
	s = strings.Join(strings.Fields(clean(s)), " ")
	r := []rune(s)
	if width < 1 {
		return ""
	}
	if len(r) > width {
		return string(r[:max(0, width-1)]) + "…"
	}
	return s
}
func (c console) drawMenu(title, subtitle string, items []string, actions bool, focus, first, count, width int) {
	var b strings.Builder
	b.WriteString("\x1b[H\x1b[2J\n  ")
	b.WriteString(c.style(accent, "◆"))
	b.WriteString("  ")
	b.WriteString(c.style("1", "CodEz"))
	b.WriteString("   ")
	b.WriteString(c.style(muted, "#"+build+"-"+release))
	b.WriteString("\n\n  ")
	b.WriteString(c.style("1", clipLine(title, width-4)))
	b.WriteString("\n  ")
	b.WriteString(c.style(muted, clipLine(subtitle, width-4)))
	b.WriteString("\n\n")
	for i := first; i < min(first+count, len(items)); i++ {
		prefix := "    "
		label := clipLine(items[i], width-6)
		if i == focus {
			prefix = "  ❯ "
			label = c.style("1;"+accent, label)
		}
		b.WriteString(prefix + label + "\n")
	}
	if len(items) == 0 {
		b.WriteString("    No matching models\n")
	}
	hint := "↑ ↓ Navigate   Enter Select   Esc Back"
	if actions {
		hint = "↑ ↓ Select   Enter   / Search   Tab Filter   ← → Page   Esc Back"
	}
	b.WriteString("\n  " + c.style(muted, clipLine(hint, width-4)) + "\n")
	fmt.Fprint(c.out, b.String())
}
func (c console) menuByte(ctx context.Context, deadline time.Time) (byte, error) {
	for {
		if e := ctx.Err(); e != nil {
			return 0, e
		}
		if c.in.Buffered() > 0 {
			return c.in.ReadByte()
		}
		if !deadline.IsZero() && time.Now().After(deadline) {
			return 0, io.EOF
		}
		var fds syscall.FdSet
		fds.Bits[0] = 1
		timeout := syscall.Timeval{Usec: 50000}
		n, e := syscall.Select(1, &fds, nil, nil, &timeout)
		if e == syscall.EINTR {
			continue
		}
		if e != nil {
			return 0, e
		}
		if n > 0 {
			return c.in.ReadByte()
		}
	}
}
func (c console) menuKey(ctx context.Context) (string, error) {
	b, e := c.menuByte(ctx, time.Time{})
	if e != nil {
		return "", e
	}
	switch b {
	case 3:
		return "", context.Canceled
	case 4:
		return "", io.EOF
	case 13, 10:
		return "enter", nil
	case 9:
		return "tab", nil
	case 27:
		deadline := time.Now().Add(100 * time.Millisecond)
		next, e := c.menuByte(ctx, deadline)
		if e != nil {
			return "escape", nil
		}
		if next != '[' && next != 'O' {
			return "escape", nil
		}
		last, e := c.menuByte(ctx, deadline)
		if e != nil {
			return "escape", nil
		}
		switch last {
		case 'A':
			return "up", nil
		case 'B':
			return "down", nil
		case 'C':
			return "right", nil
		case 'D':
			return "left", nil
		}
		return "", nil
	default:
		return string(b), nil
	}
}
