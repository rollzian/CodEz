package main

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"github.com/AuxiaCorp/CodEz/internal/config"
	"github.com/AuxiaCorp/CodEz/internal/provider"
)

const (
	accent = "38;5;141"
	muted  = "38;5;245"
	good   = "38;5;114"
	warn   = "38;5;221"
	bad    = "38;5;203"
)

func newConsole(in *os.File, out *os.File) console {
	a, ae := in.Stat()
	b, be := out.Stat()
	var terminalInput *os.File
	if ae == nil && a.Mode()&os.ModeCharDevice != 0 {
		cmd := exec.Command("stty", "-g")
		cmd.Stdin = in
		if cmd.Run() == nil {
			terminalInput = in
		}
	}
	terminal := terminalInput != nil && be == nil && b.Mode()&os.ModeCharDevice != 0 && os.Getenv("TERM") != "dumb" && os.Getenv("TERM") != ""
	_, noColor := os.LookupEnv("NO_COLOR")
	return console{in: bufio.NewReader(in), out: out, terminalInput: terminalInput, rich: terminal, color: terminal && !noColor, motion: terminal && os.Getenv("CODEZ_NO_MOTION") == "" && !noColor, interactive: terminalInput != nil}
}

func (c console) style(code, value string) string {
	if !c.color {
		return value
	}
	return "\x1b[" + code + "m" + value + "\x1b[0m"
}

func (c console) banner(root string) {
	if !c.rich {
		fmt.Fprintf(c.out, "\nCodEz #%s-%s\n%s\n\n", build, release, clean(root))
		return
	}
	fmt.Fprintln(c.out)
	fmt.Fprintln(c.out, "  "+c.style(accent, "╭━━╮")+"  "+c.style("1", "CodEz")+"  "+c.style(muted, "#"+build+"-"+release))
	fmt.Fprintln(c.out, "  "+c.style(accent, "╰━╸╱")+"  "+c.style(muted, "Your terminal. Your codebase."))
	fmt.Fprintln(c.out, "  "+c.style(muted, "Workspace")+"  "+clean(root))
	fmt.Fprintln(c.out)
}

func (c console) section(title string) { fmt.Fprintln(c.out, "\n  "+c.style("1", title)) }
func (c console) note(s string)        { fmt.Fprintln(c.out, "  "+c.style(muted, clean(s))) }
func (c console) failure(s string)     { fmt.Fprintln(c.out, "  "+c.style(bad, "×")+" "+clean(s)) }
func (c console) success(s string)     { fmt.Fprintln(c.out, "  "+c.style(good, "✓")+" "+clean(s)) }
func (c console) status(cfg config.Config, messages int) {
	fmt.Fprintf(c.out, "  %s %s  %s  %s\n", c.style(accent, "●"), clean(cfg.Model), c.style(muted, cfg.Provider), c.style(muted, fmt.Sprintf("%d messages", messages)))
}
func (c console) prompt() string {
	if !c.rich {
		return "codez › "
	}
	return "\n  " + c.style(accent, "❯") + " "
}
func (c console) help() {
	c.section("Commands")
	for _, row := range [][2]string{{"/models [filter]", "Browse and switch models"}, {"/model", "Open model library"}, {"/setup", "Configure provider"}, {"/status", "Show current session"}, {"/resume", "Restore recent messages"}, {"/new", "Start a fresh context"}, {"/clear", "Clear the terminal"}, {"/exit", "Close CodEz"}} {
		fmt.Fprintf(c.out, "  %s %s\n", c.style(accent, fmt.Sprintf("%-19s", row[0])), row[1])
	}
}
func (c console) progress(label string) func() {
	if !c.motion {
		return func() {}
	}
	done := make(chan struct{})
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		frames := []string{"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"}
		ticker := time.NewTicker(110 * time.Millisecond)
		defer ticker.Stop()
		start := time.Now()
		i := 0
		for {
			fmt.Fprintf(c.out, "\r\x1b[2K  %s %s %s", c.style(accent, frames[i%len(frames)]), label, c.style(muted, fmt.Sprintf("%.1fs", time.Since(start).Seconds())))
			i++
			select {
			case <-done:
				fmt.Fprint(c.out, "\r\x1b[2K")
				return
			case <-ticker.C:
			}
		}
	}()
	return func() { close(done); <-finished }
}
func (c console) toolResult(name string, err error, took time.Duration) {
	mark, code := "✓", good
	if err != nil {
		mark, code = "×", bad
	}
	fmt.Fprintf(c.out, "  %s %s %s\n", c.style(code, mark), clean(name), c.style(muted, fmt.Sprintf("(%s)", took.Round(time.Millisecond))))
}
func toolLabel(call provider.ToolCall, key string) string {
	name := strings.ReplaceAll(call.Name, "_", " ")
	arg, _ := call.Arguments["path"].(string)
	if call.Name == "grep" {
		arg, _ = call.Arguments["query"].(string)
	}
	if arg != "" {
		name += " · " + arg
	}
	name = strings.Join(strings.Fields(redact(name, key)), " ")
	runes := []rune(name)
	if len(runes) > 64 {
		name = string(runes[:61]) + "…"
	}
	return name
}
func modelSelection(input string, ids []string) (string, error) {
	input = strings.TrimSpace(input)
	if input == "" {
		return "", fmt.Errorf("model ID is required")
	}
	for _, id := range ids {
		if id == input {
			return id, nil
		}
	}
	if n, e := strconv.Atoi(input); e == nil && len(ids) > 0 {
		if n < 1 || n > len(ids) {
			return "", fmt.Errorf("model selection out of range")
		}
		return ids[n-1], nil
	}
	return input, nil
}
func (c console) showModels(ids []string, filter string, numbered bool) {
	count := 0
	for i, id := range ids {
		if !strings.Contains(strings.ToLower(id), strings.ToLower(filter)) {
			continue
		}
		if numbered {
			fmt.Fprintf(c.out, "  %s %s\n", c.style(muted, fmt.Sprintf("%3d", i+1)), clean(id))
		} else {
			fmt.Fprintln(c.out, "  "+clean(id))
		}
		count++
	}
	if count == 0 {
		c.note("No matching models.")
	}
}

func (c console) answerHeader() {
	if c.rich {
		fmt.Fprintln(c.out, "\n  "+c.style(accent, "◆")+" "+c.style("1", "CodEz"))
	}
}

func (c console) answer(s string) {
	c.answerHeader()
	// Preserve the response verbatim, including indentation and code blocks.
	fmt.Fprintln(c.out, s)
}

func (c console) clear() {
	if c.rich {
		io.WriteString(c.out, "\x1b[2J\x1b[H")
	}
}
