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

func TestStreamingProviderToolRounds(t *testing.T) {
	cases := []struct {
		name, path    string
		newProvider   func(string) Provider
		first, second []string
	}{
		{"responses", "/responses", func(url string) Provider { return NewOpenAI(url, "key", "m") }, []string{
			`{"type":"response.output_text.delta","delta":"Reading"}`,
			`{"type":"response.completed","response":{"id":"r1","status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Reading"}]},{"type":"function_call","call_id":"a","name":"read_file","arguments":"{\"path\":\"README.md\"}"}]}}`,
		}, []string{
			`{"type":"response.output_text.delta","delta":"do"}`,
			`{"type":"response.output_text.delta","delta":"ne"}`,
			`{"type":"response.completed","response":{"id":"r2","status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"done"}]}]}}`,
		}},
		{"chat", "/chat/completions", func(url string) Provider { return NewChatCompatible(url, "key", "m") }, []string{
			`{"choices":[{"delta":{"content":"Reading","tool_calls":[{"index":0,"id":"a","function":{"name":"read_file","arguments":"{\"pa"}}]}}]}`,
			`{"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"th\":\"README.md\"}"}}]}}]}`,
			`{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}`, `[DONE]`,
		}, []string{
			`{"choices":[{"delta":{"content":"do"}}]}`,
			`{"choices":[{"delta":{"content":"ne"},"finish_reason":"stop"}]}`, `[DONE]`,
		}},
		{"anthropic", "/v1/messages", func(url string) Provider { return NewAnthropic(url, "key", "m") }, []string{
			`{"type":"message_start","message":{"id":"m1","content":[]}}`,
			`{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Reading"}}`,
			`{"type":"content_block_stop","index":0}`,
			`{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"a","name":"read_file","input":{}}}`,
			`{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"pa"}}`,
			`{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"th\":\"README.md\"}"}}`,
			`{"type":"content_block_stop","index":1}`,
			`{"type":"message_delta","delta":{"stop_reason":"tool_use"}}`, `{"type":"message_stop"}`,
		}, []string{
			`{"type":"message_start","message":{"id":"m2","content":[]}}`,
			`{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"do"}}`,
			`{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ne"}}`,
			`{"type":"content_block_stop","index":0}`,
			`{"type":"message_delta","delta":{"stop_reason":"end_turn"}}`, `{"type":"message_stop"}`,
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			count := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				count++
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
					w.WriteHeader(400)
					return
				}
				if r.URL.Path != tc.path || body["stream"] != true {
					t.Errorf("bad request %s %#v", r.URL.Path, body)
				}
				events := tc.first
				if count == 2 {
					events = tc.second
					serialized, _ := json.Marshal(body)
					if !strings.Contains(string(serialized), "file contents") {
						t.Error("tool result missing in continuation")
					}
				}
				w.Header().Set("Content-Type", "text/event-stream")
				for _, e := range events {
					fmt.Fprintf(w, "data: %s\n\n", e)
					w.(http.Flusher).Flush()
				}
			}))
			defer server.Close()
			p := tc.newProvider(server.URL)
			var text strings.Builder
			ctx := WithTextStream(context.Background(), func(s string) { text.WriteString(s) })
			r, err := p.Complete(ctx, []Message{{Role: "user", Content: "read"}}, nil)
			if err != nil || r.Text != "Reading" || text.String() != "Reading" || len(r.ToolCalls) != 1 {
				t.Fatalf("first result: %+v, %v, %q", r, err, text.String())
			}
			if r.ToolCalls[0].Arguments["path"] != "README.md" || r.ToolCalls[0].ID != "a" {
				t.Fatalf("bad tool: %+v", r.ToolCalls[0])
			}
			text.Reset()
			r, err = p.Continue(ctx, nil, nil, r, map[string]string{"a": "file contents"})
			if err != nil || r.Text != "done" || text.String() != "done" || len(r.ToolCalls) != 0 {
				t.Fatalf("second result: %+v, %v, %q", r, err, text.String())
			}
		})
	}
}

func TestIncompleteStreamsRejectPartialToolCalls(t *testing.T) {
	for _, tc := range []struct {
		name   string
		decode streamDecoder
		data   string
	}{
		{"responses", decodeResponsesStream, `{"type":"response.output_text.delta","delta":"partial"}`},
		{"chat", decodeChatStream, `{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"a","function":{"name":"shell","arguments":"{}"}}]}}]}`},
		{"anthropic", decodeAnthropicStream, `{"type":"message_start","message":{"id":"m1","content":[]}}`},
		{"chat-length", decodeChatStream, `{"choices":[{"delta":{"content":"partial"},"finish_reason":"length"}]}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := tc.decode(strings.NewReader("data: "+tc.data+"\n\n"), func(string) {}); err == nil {
				t.Fatal("accepted incomplete stream")
			}
		})
	}
}

func TestMislabelledEventStream(t *testing.T) {
	for _, contentType := range []string{"text/plain", "application/json", "application/octet-stream", "text/event-stream; charset=utf-8"} {
		t.Run(contentType, func(t *testing.T) {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if !strings.Contains(r.Header.Get("Accept"), "text/event-stream") {
					t.Error("missing SSE negotiation")
				}
				if r.Header.Get("Authorization") != "Bearer valid-key" {
					t.Error("wrong credential")
				}
				w.Header().Set("Content-Type", contentType)
				fmt.Fprint(w, "event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\",\"delta\":\"hello\"}\n\nevent: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"hello\"}]}]}}\n\n")
			}))
			defer s.Close()
			p := NewOpenAI(s.URL, "valid-key", "m")
			var seen strings.Builder
			ctx := WithTextStream(context.Background(), func(s string) { seen.WriteString(s) })
			r, err := p.Complete(ctx, []Message{{Role: "user", Content: "hello"}}, nil)
			if err != nil || r.Text != "hello" || seen.String() != "hello" {
				t.Fatal(r.Text, seen.String(), err)
			}
		})
	}
}

func TestUnexpectedPlainTextDoesNotLeakBody(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprint(w, "error: secret-response")
	}))
	defer s.Close()
	_, err := NewChatCompatible(s.URL, "key", "m").Complete(context.Background(), nil, nil)
	if err == nil || strings.Contains(err.Error(), "secret-response") || !strings.Contains(err.Error(), "endpoint") {
		t.Fatal("missing safe protocol diagnostic", err)
	}
}
