package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCatalogOptionalPricing(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, `{"data":[{"id":"no-price"},{"id":"numeric","pricing":{"prompt":0.000001,"completion":0.000002}},{"id":"null-price","pricing":{"prompt":null,"completion":"0"}},{"id":"bad-price","pricing":{"prompt":{"amount":0},"completion":0}},{"id":"free","pricing":{"prompt":"0","completion":"0"}},{"id":"unknown-fee","pricing":{"prompt":"0","completion":"0","request":null}}]}`)
	}))
	defer s.Close()
	rows, e := Catalog(context.Background(), NewChatCompatible(s.URL, "", "m"), "")
	if e != nil || len(rows) != 6 {
		t.Fatalf("catalog: %v %#v", e, rows)
	}
	for _, m := range rows {
		in, out, known := m.Prices()
		switch m.ID {
		case "numeric":
			if !known || in != 1 || out != 2 {
				t.Fatalf("numeric: %v %v %v", in, out, known)
			}
		case "no-price", "null-price", "bad-price":
			if known || m.Free() {
				t.Fatal("invalid price reported as known/free", m)
			}
		case "free":
			if !m.Free() {
				t.Fatal("verified zero price lost", m)
			}
		case "unknown-fee":
			if m.Free() {
				t.Fatal("unknown fee reported free", m)
			}
		}
	}
}

func TestTextOnlyRequestsOmitToolParameters(t *testing.T) {
	for _, kind := range []string{"chat", "responses", "anthropic"} {
		t.Run(kind, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var b map[string]any
				if e := json.NewDecoder(r.Body).Decode(&b); e != nil {
					t.Error(e)
					w.WriteHeader(400)
					return
				}
				if b["model"] != "unpriced-model" {
					t.Error("wrong model", b)
				}
				if _, ok := b["tools"]; ok {
					t.Error("tools sent for text-only model")
					w.WriteHeader(400)
					return
				}
				if _, ok := b["tool_choice"]; ok {
					t.Error("tool_choice sent for text-only model")
					w.WriteHeader(400)
					return
				}
				switch kind {
				case "chat":
					fmt.Fprint(w, `{"choices":[{"message":{"role":"assistant","content":"ok"}}]}`)
				case "responses":
					fmt.Fprint(w, `{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"ok"}]}]}`)
				case "anthropic":
					fmt.Fprint(w, `{"content":[{"type":"text","text":"ok"}]}`)
				}
			}))
			defer s.Close()
			var p Provider
			switch kind {
			case "chat":
				p = NewChatCompatible(s.URL, "key", "unpriced-model")
			case "responses":
				p = NewOpenAI(s.URL, "key", "unpriced-model")
			case "anthropic":
				p = NewAnthropic(s.URL, "key", "unpriced-model")
			}
			got, e := p.Complete(context.Background(), []Message{{Role: "user", Content: "hello"}}, nil)
			if e != nil || got.Text != "ok" {
				t.Fatalf("complete: %#v %v", got, e)
			}
		})
	}
}

func TestReasoningReplayDuringToolRound(t *testing.T) {
	for _, stream := range []bool{false, true} {
		t.Run(fmt.Sprint(stream), func(t *testing.T) {
			steps := 0
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				steps++
				var body map[string]any
				if e := json.NewDecoder(r.Body).Decode(&body); e != nil {
					t.Error(e)
					w.WriteHeader(400)
					return
				}
				if steps == 1 {
					if stream {
						w.Header().Set("Content-Type", "text/event-stream")
						fmt.Fprint(w, "data: {\"choices\":[{\"delta\":{\"reasoning_content\":\"opaque-\"}}]}\n\ndata: {\"choices\":[{\"delta\":{\"reasoning_content\":\"state\",\"tool_calls\":[{\"index\":0,\"id\":\"a\",\"function\":{\"name\":\"read_file\",\"arguments\":\"{}\"}}]},\"finish_reason\":\"tool_calls\"}]}\n\ndata: [DONE]\n\n")
					} else {
						fmt.Fprint(w, `{"choices":[{"finish_reason":"tool_calls","message":{"role":"assistant","content":null,"reasoning_content":"opaque-state","tool_calls":[{"id":"a","type":"function","function":{"name":"read_file","arguments":"{}"}}]}}]}`)
					}
					return
				}
				ms := body["messages"].([]any)
				if object(ms[len(ms)-2])["reasoning_content"] != "opaque-state" || object(ms[len(ms)-1])["tool_call_id"] != "a" {
					t.Error("missing provider state", ms)
					w.WriteHeader(400)
					return
				}
				fmt.Fprint(w, `{"choices":[{"finish_reason":"stop","message":{"role":"assistant","content":"done"}}]}`)
			}))
			defer s.Close()
			p := NewChatCompatible(s.URL, "key", "m")
			ctx := context.Background()
			var visible strings.Builder
			if stream {
				ctx = WithTextStream(ctx, func(s string) { visible.WriteString(s) })
			}
			defs := []ToolDef{{Name: "read_file", Schema: map[string]any{"type": "object"}}}
			res, e := p.Complete(ctx, []Message{{Role: "user", Content: "read"}}, defs)
			if e != nil || len(res.ToolCalls) != 1 || res.Text != "" || visible.Len() != 0 {
				t.Fatalf("initial: %v %v %q", res, e, visible.String())
			}
			res, e = p.Continue(ctx, nil, defs, res, map[string]string{"a": "contents"})
			if e != nil || res.Text != "done" {
				t.Fatalf("continue: %v %v", res, e)
			}
		})
	}
}

func TestProviderErrorDiagnostics(t *testing.T) {
	for _, tc := range []struct{ body, expected string }{{`{"error":{"type":"invalid_request_error","param":"tools","message":"secret text"}}`, "provider HTTP 400 (invalid_request_error) [parameter tools]"}, {`{"error":{"code":400,"message":"secret text"}}`, "provider HTTP 400 (400)"}} {
		s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(400); fmt.Fprint(w, tc.body) }))
		_, e := NewChatCompatible(s.URL, "key", "m").Complete(context.Background(), nil, nil)
		s.Close()
		if e == nil || e.Error() != tc.expected {
			t.Fatal(e, tc.expected)
		}
	}
}
