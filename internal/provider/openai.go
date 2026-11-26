package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

type OpenAI struct {
	BaseURL     string
	APIKey      string
	Model       string
	HTTP        *HTTPClient
	AccountMode bool
}

func NewOpenAI(baseURL, key, model string) *OpenAI {
	return &OpenAI{BaseURL: strings.TrimRight(baseURL, "/"), APIKey: key, Model: model, HTTP: NewHTTPClient()}
}

func (p *OpenAI) headers() map[string]string {
	h := map[string]string{}
	if p.APIKey != "" {
		h["Authorization"] = "Bearer " + p.APIKey
	}
	return h
}

func toolPayload(t ToolDef) map[string]any {
	return map[string]any{"type": "function", "name": t.Name, "description": t.Description, "parameters": t.Schema, "strict": false}
}

func (p *OpenAI) Complete(ctx context.Context, messages []Message, tools []ToolDef) (Result, error) {
	input := make([]any, 0, len(messages))
	for _, m := range messages {
		input = append(input, map[string]any{"role": m.Role, "content": m.Content})
	}
	tp := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		tp = append(tp, toolPayload(t))
	}
	body := map[string]any{"model": p.Model, "input": input}
	if len(tp) > 0 {
		body["tools"] = tp
		body["tool_choice"] = "auto"
	}
	if p.AccountMode {
		body["store"] = false
		body["stream"] = true
		body["include"] = []string{"reasoning.encrypted_content"}
	}
	var raw map[string]any
	if err := p.HTTP.modelJSON(ctx, p.BaseURL+"/responses", p.headers(), body, decodeResponsesStream, &raw); err != nil {
		return Result{}, err
	}
	if p.AccountMode {
		raw["_codez_input"] = input
	}
	return parseOpenAI(raw)
}

func (p *OpenAI) Continue(ctx context.Context, messages []Message, tools []ToolDef, prior Result, outputs map[string]string) (Result, error) {
	raw, ok := prior.Raw.(map[string]any)
	if !ok {
		return Result{}, fmt.Errorf("missing prior response")
	}
	id, _ := raw["id"].(string)
	if id == "" && !p.AccountMode {
		return Result{}, fmt.Errorf("missing response id")
	}
	items := make([]map[string]any, 0, len(outputs))
	for callID, out := range outputs {
		items = append(items, map[string]any{"type": "function_call_output", "call_id": callID, "output": out})
	}
	tp := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		tp = append(tp, toolPayload(t))
	}
	body := map[string]any{"model": p.Model, "previous_response_id": id, "input": items}
	if len(tp) > 0 {
		body["tools"] = tp
	}
	if p.AccountMode {
		history, ok := raw["_codez_input"].([]any)
		if !ok {
			return Result{}, fmt.Errorf("missing stateless response history")
		}
		output, ok := raw["output"].([]any)
		if !ok {
			return Result{}, fmt.Errorf("missing stateless response output")
		}
		input := append(append([]any(nil), history...), output...)
		for _, call := range prior.ToolCalls {
			out, ok := outputs[call.ID]
			if !ok {
				return Result{}, fmt.Errorf("missing tool result")
			}
			input = append(input, map[string]any{"type": "function_call_output", "call_id": call.ID, "output": out})
		}
		delete(body, "previous_response_id")
		body["input"] = input
		body["store"] = false
		body["stream"] = true
		body["include"] = []string{"reasoning.encrypted_content"}
	}
	var next map[string]any
	if err := p.HTTP.modelJSON(ctx, p.BaseURL+"/responses", p.headers(), body, decodeResponsesStream, &next); err != nil {
		return Result{}, err
	}
	if p.AccountMode {
		next["_codez_input"] = body["input"]
	}
	return parseOpenAI(next)
}

func parseOpenAI(raw map[string]any) (Result, error) {
	if status := stringValue(raw["status"]); status != "" && status != "completed" {
		return Result{}, fmt.Errorf("provider response status: %s", status)
	}
	r := Result{Raw: raw}
	out, _ := raw["output"].([]any)
	for _, item := range out {
		obj, _ := item.(map[string]any)
		typ, _ := obj["type"].(string)
		switch typ {
		case "message":
			content, _ := obj["content"].([]any)
			for _, c := range content {
				cm, _ := c.(map[string]any)
				if txt, ok := cm["text"].(string); ok {
					r.Text += txt
				}
			}
		case "function_call":
			name, _ := obj["name"].(string)
			id, _ := obj["call_id"].(string)
			argstr, _ := obj["arguments"].(string)
			var args map[string]any
			if argstr != "" {
				if err := json.Unmarshal([]byte(argstr), &args); err != nil {
					return Result{}, fmt.Errorf("invalid tool arguments for %s", name)
				}
			}
			r.ToolCalls = append(r.ToolCalls, ToolCall{ID: id, Name: name, Arguments: args})
		}
	}
	return r, nil
}
