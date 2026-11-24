package main

import (
	"bytes"
	"context"
	"github.com/AuxiaCorp/CodEz/internal/provider"
	"github.com/AuxiaCorp/CodEz/internal/tools"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

type forbiddenProvider struct {
	t      *testing.T
	denied bool
}

func (p *forbiddenProvider) Complete(ctx context.Context, ms []provider.Message, defs []provider.ToolDef) (provider.Result, error) {
	for _, d := range defs {
		if d.Name == "write_file" || d.Name == "shell" || d.Name == "replace_text" {
			p.t.Fatal("mutable tool advertised")
		}
	}
	if !strings.Contains(ms[0].Content, `"test-model" with CodEz`) {
		p.t.Fatal("model missing from system prompt")
	}
	return provider.Result{ToolCalls: []provider.ToolCall{{ID: "1", Name: "write_file", Arguments: map[string]any{"path": "unexpected.txt", "content": "bad"}}}}, nil
}
func (p *forbiddenProvider) Continue(ctx context.Context, ms []provider.Message, defs []provider.ToolDef, prior provider.Result, outs map[string]string) (provider.Result, error) {
	p.denied = outs["1"] == "Denied by agent mode"
	return provider.Result{Text: "done"}, nil
}
func TestReadonlyModesRejectUnadvertisedMutations(t *testing.T) {
	for _, mode := range []agentMode{modeAsk, modePlan, modeReview} {
		t.Run(string(mode), func(t *testing.T) {
			root := t.TempDir()
			r, e := tools.New(root)
			if e != nil {
				t.Fatal(e)
			}
			p := &forbiddenProvider{t: t}
			var out bytes.Buffer
			c := console{out: &out}
			ms := []provider.Message{{Role: "system", Content: systemPrompt("base", "test-model", mode)}}
			ans, e := c.turn(context.Background(), p, r, ms, "", mode)
			if e != nil || ans != "done" || !p.denied {
				t.Fatal(ans, e, p.denied)
			}
			if _, e = os.Stat(filepath.Join(root, "unexpected.txt")); !os.IsNotExist(e) {
				t.Fatal("read-only write occurred", e)
			}
		})
	}
}
func TestComposerCursorAndRecall(t *testing.T) {
	d := &composer{}
	d.set("ac")
	d.cursor = 1
	d.insert('b')
	if string(d.text) != "abc" {
		t.Fatal(string(d.text))
	}
	d.erase()
	if string(d.text) != "ac" {
		t.Fatal(string(d.text))
	}
	d.remember("prior")
	d.set("draft")
	d.recall(-1)
	if string(d.text) != "prior" {
		t.Fatal(string(d.text))
	}
	d.recall(1)
	if string(d.text) != "draft" {
		t.Fatal(string(d.text))
	}
	d.set("/doc")
	completeCommand(d)
	if string(d.text) != "/doctor " {
		t.Fatal(string(d.text))
	}
}
