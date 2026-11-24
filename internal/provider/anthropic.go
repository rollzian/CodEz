package provider

import (
	"context"
	"fmt"
	"strings"
)

type anthropicState struct {
	System   string
	Messages []map[string]any
	Content  []any
}

type Anthropic struct {
	BaseURL string
	APIKey  string
	Model   string
	HTTP    *HTTPClient
}

func NewAnthropic(baseURL, key, model string) *Anthropic {
	return &Anthropic{BaseURL: strings.TrimRight(baseURL, "/"), APIKey: key, Model: model, HTTP: NewHTTPClient()}
}

func (p *Anthropic) headers() map[string]string {
	return map[string]string{"x-api-key": p.APIKey, "anthropic-version": "2023-06-01"}
}

func splitAnthropicMessages(messages []Message) (string, []map[string]any) {
	var system strings.Builder
	ms := make([]map[string]any, 0, len(messages))
	for _, m := range messages {
		if m.Role == "system" || m.Role == "developer" {
			if system.Len() > 0 {
				system.WriteString("\n\n")
			}
			system.WriteString(m.Content)
			continue
		}
		role := m.Role
		if role != "assistant" {
			role = "user"
		}
		ms = append(ms, map[string]any{"role": role, "content": m.Content})
	}
	return system.String(), ms
}

func anthropicTools(tools []ToolDef) []map[string]any {
	ts := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		ts = append(ts, map[string]any{"name": t.Name, "description": t.Description, "input_schema": t.Schema})
	}
	return ts
}

func (p *Anthropic) Complete(ctx context.Context, messages []Message, tools []ToolDef) (Result, error) {
	system, ms := splitAnthropicMessages(messages)
	body := map[string]any{"model": p.Model, "max_tokens": 8192, "messages": ms, "tools": anthropicTools(tools)}
	if system != "" {
		body["system"] = system
	}
	var raw map[string]any
	if err := p.HTTP.modelJSON(ctx, p.BaseURL+"/v1/messages", p.headers(), body, decodeAnthropicStream, &raw); err != nil {
		return Result{}, err
	}
	return parseAnthropic(raw, system, ms)
}

func (p *Anthropic) Continue(ctx context.Context, messages []Message, tools []ToolDef, prior Result, outputs map[string]string) (Result, error) {
	state, ok := prior.Raw.(anthropicState)
	if !ok {
		return Result{}, fmt.Errorf("missing prior response")
	}
	system, ms := state.System, append([]map[string]any(nil), state.Messages...)
	content := state.Content
	ms = append(ms, map[string]any{"role": "assistant", "content": content})
	toolResults := make([]map[string]any, 0, len(outputs))
	for _, call := range prior.ToolCalls {
		id, out := call.ID, outputs[call.ID]
		toolResults = append(toolResults, map[string]any{"type": "tool_result", "tool_use_id": id, "content": out})
	}
	ms = append(ms, map[string]any{"role": "user", "content": toolResults})
	body := map[string]any{"model": p.Model, "max_tokens": 8192, "messages": ms, "tools": anthropicTools(tools)}
	if system != "" {
		body["system"] = system
	}
	var next map[string]any
	if err := p.HTTP.modelJSON(ctx, p.BaseURL+"/v1/messages", p.headers(), body, decodeAnthropicStream, &next); err != nil {
		return Result{}, err
	}
	return parseAnthropic(next, system, ms)
}

func parseAnthropic(raw map[string]any, system string, ms []map[string]any) (Result, error) {
	if reason := stringValue(raw["stop_reason"]); reason != "" && reason != "end_turn" && reason != "tool_use" && reason != "stop_sequence" {
		return Result{}, fmt.Errorf("provider stopped: %s", reason)
	}
	content, _ := raw["content"].([]any)
	r := Result{Raw: anthropicState{System: system, Messages: ms, Content: content}}
	for _, v := range content {
		o, _ := v.(map[string]any)
		typ, _ := o["type"].(string)
		switch typ {
		case "text":
			if s, ok := o["text"].(string); ok {
				r.Text += s
			}
		case "tool_use":
			name, _ := o["name"].(string)
			id, _ := o["id"].(string)
			args, _ := o["input"].(map[string]any)
			r.ToolCalls = append(r.ToolCalls, ToolCall{ID: id, Name: name, Arguments: args})
		}
	}
	return r, nil
}
