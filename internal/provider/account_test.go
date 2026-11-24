package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestChatGPTAccountStatelessContinuation(t *testing.T) {
	steps := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer access" {
			t.Error("missing OAuth access token")
		}
		if r.URL.Path == "/models" {
			fmt.Fprint(w, `{"models":[{"slug":"allowed","display_name":"Allowed","visibility":"list"},{"slug":"hidden","visibility":"hidden"}]}`)
			return
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
			w.WriteHeader(400)
			return
		}
		if body["store"] != false || body["stream"] != true || body["previous_response_id"] != nil {
			t.Error("invalid account request", body)
		}
		steps++
		w.Header().Set("Content-Type", "text/event-stream")
		if steps == 1 {
			fmt.Fprint(w, "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":[{\"type\":\"reasoning\",\"encrypted_content\":\"opaque\"},{\"type\":\"function_call\",\"call_id\":\"c1\",\"name\":\"read_file\",\"arguments\":\"{}\"}]}}\n\n")
			return
		}
		input, ok := body["input"].([]any)
		if !ok || len(input) != 4 {
			t.Error("missing replayed input", body)
		} else {
			if object(input[1])["encrypted_content"] != "opaque" || object(input[2])["call_id"] != "c1" || object(input[3])["output"] != "file" {
				t.Error("invalid replay", input)
			}
		}
		fmt.Fprint(w, "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"content\":[{\"type\":\"output_text\",\"text\":\"done\"}]}]}}\n\n")
	}))
	defer srv.Close()
	p := NewOpenAI(srv.URL, "access", "allowed")
	p.AccountMode = true
	ids, e := Models(context.Background(), p)
	if e != nil || len(ids) != 1 || ids[0] != "allowed" {
		t.Fatal(ids, e)
	}
	r, e := p.Complete(context.Background(), []Message{{Role: "user", Content: "read"}}, nil)
	if e != nil || len(r.ToolCalls) != 1 {
		t.Fatal(r, e)
	}
	r, e = p.Continue(context.Background(), nil, nil, r, map[string]string{"c1": "file"})
	if e != nil || r.Text != "done" {
		t.Fatal(r, e)
	}
}
