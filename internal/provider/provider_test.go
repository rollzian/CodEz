package provider

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestOpenAIResponsesToolLoop(t *testing.T) {
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/responses" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		step++
		w.Header().Set("Content-Type", "application/json")
		if step == 1 {
			_, _ = w.Write([]byte(`{"id":"r1","output":[{"type":"function_call","call_id":"c1","name":"read_file","arguments":"{\"path\":\"README.md\"}"}]}`))
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["previous_response_id"] != "r1" {
			t.Fatalf("missing previous_response_id: %#v", body)
		}
		_, _ = w.Write([]byte(`{"id":"r2","output":[{"type":"message","content":[{"type":"output_text","text":"done"}]}]}`))
	}))
	defer srv.Close()

	p := NewOpenAI(srv.URL, "k", "m")
	r, err := p.Complete(context.Background(), []Message{{Role: "user", Content: "read"}}, nil)
	if err != nil || len(r.ToolCalls) != 1 {
		t.Fatalf("complete: %v %#v", err, r)
	}
	r, err = p.Continue(context.Background(), nil, nil, r, map[string]string{"c1": "hello"})
	if err != nil || r.Text != "done" {
		t.Fatalf("continue: %v %#v", err, r)
	}
}

func TestChatCompatibleToolLoop(t *testing.T) {
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/chat/completions" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		step++
		w.Header().Set("Content-Type", "application/json")
		if step == 1 {
			_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"","tool_calls":[{"id":"c1","type":"function","function":{"name":"git_status","arguments":"{}"}}]}}]}`))
			return
		}
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"clean"}}]}`))
	}))
	defer srv.Close()

	p := NewChatCompatible(srv.URL, "", "m")
	r, err := p.Complete(context.Background(), []Message{{Role: "system", Content: "x"}, {Role: "user", Content: "status"}}, nil)
	if err != nil || len(r.ToolCalls) != 1 {
		t.Fatalf("complete: %v %#v", err, r)
	}
	r, err = p.Continue(context.Background(), nil, nil, r, map[string]string{"c1": "## main"})
	if err != nil || r.Text != "clean" {
		t.Fatalf("continue: %v %#v", err, r)
	}
}

func TestAnthropicSystemSeparatedAndToolLoop(t *testing.T) {
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/messages" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		step++
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["system"] != "rules" {
			t.Fatalf("system = %#v", body["system"])
		}
		for _, raw := range body["messages"].([]any) {
			msg := raw.(map[string]any)
			if msg["role"] == "system" {
				t.Fatal("system role leaked into messages")
			}
		}
		w.Header().Set("Content-Type", "application/json")
		if step == 1 {
			_, _ = w.Write([]byte(`{"content":[{"type":"tool_use","id":"t1","name":"list_files","input":{}}]}`))
			return
		}
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}]}`))
	}))
	defer srv.Close()

	p := NewAnthropic(srv.URL, "k", "m")
	msgs := []Message{{Role: "system", Content: "rules"}, {Role: "user", Content: "list"}}
	r, err := p.Complete(context.Background(), msgs, nil)
	if err != nil || len(r.ToolCalls) != 1 {
		t.Fatalf("complete: %v %#v", err, r)
	}
	r, err = p.Continue(context.Background(), msgs, nil, r, map[string]string{"t1": "README.md"})
	if err != nil || r.Text != "ok" {
		t.Fatalf("continue: %v %#v", err, r)
	}
}

func TestAnthropicRetainsAllToolRounds(t *testing.T) {
	step := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var b map[string]any
		if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
			t.Error(err)
			return
		}
		step++
		if n := len(b["messages"].([]any)); n != 2*step-1 {
			t.Errorf("round %d messages %d", step, n)
		}
		if step == 1 {
			w.Write([]byte(`{"content":[{"type":"tool_use","id":"a","name":"list_files","input":{}}]}`))
		} else if step == 2 {
			w.Write([]byte(`{"content":[{"type":"tool_use","id":"b","name":"list_files","input":{}}]}`))
		} else {
			w.Write([]byte(`{"content":[{"type":"text","text":"done"}]}`))
		}
	}))
	defer srv.Close()
	p := NewAnthropic(srv.URL, "k", "m")
	ctx := context.Background()
	ms := []Message{{Role: "user", Content: "test"}}
	r, e := p.Complete(ctx, ms, nil)
	if e != nil {
		t.Fatal(e)
	}
	r, e = p.Continue(ctx, ms, nil, r, map[string]string{"a": "a-result"})
	if e != nil {
		t.Fatal(e)
	}
	r, e = p.Continue(ctx, ms, nil, r, map[string]string{"b": "b-result"})
	if e != nil || r.Text != "done" {
		t.Fatalf("%v %#v", e, r)
	}
}

func TestModelsDiscovery(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/models" {
			t.Error(r.Method, r.URL.Path)
		}
		w.Write([]byte(`{"data":[{"id":"b"},{"id":"a"},{"id":"b"}]}`))
	}))
	defer srv.Close()
	ids, e := Models(context.Background(), NewChatCompatible(srv.URL, "", "m"))
	if e != nil || len(ids) != 2 || ids[0] != "a" || ids[1] != "b" {
		t.Fatalf("%#v %v", ids, e)
	}
}
