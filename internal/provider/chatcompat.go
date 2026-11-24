package provider

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

type ChatCompatible struct {
	BaseURL string
	APIKey  string
	Model   string
	HTTP    *HTTPClient
}

type chatState struct {
	Messages []map[string]any
}

func NewChatCompatible(baseURL, key, model string) *ChatCompatible {
	return &ChatCompatible{BaseURL: strings.TrimRight(baseURL, "/"), APIKey: key, Model: model, HTTP: NewHTTPClient()}
}

func (p *ChatCompatible) headers() map[string]string {
	h := map[string]string{}
	if p.APIKey != "" {
		h["Authorization"] = "Bearer " + p.APIKey
	}
	return h
}

func (p *ChatCompatible) Complete(ctx context.Context, messages []Message, tools []ToolDef) (Result, error) {
	ms := make([]map[string]any, 0, len(messages))
	for _, m := range messages {
		ms = append(ms, map[string]any{"role": m.Role, "content": m.Content})
	}
	return p.complete(ctx, ms, tools)
}

func (p *ChatCompatible) Continue(ctx context.Context, messages []Message, tools []ToolDef, prior Result, outputs map[string]string) (Result, error) {
	state, ok := prior.Raw.(chatState)
	if !ok {
		return Result{}, fmt.Errorf("missing prior chat state")
	}
	ms := append([]map[string]any(nil), state.Messages...)
	for _, tc := range prior.ToolCalls {
		out, ok := outputs[tc.ID]
		if !ok {
			continue
		}
		ms = append(ms, map[string]any{"role": "tool", "tool_call_id": tc.ID, "content": out})
	}
	return p.complete(ctx, ms, tools)
}

func (p *ChatCompatible) complete(ctx context.Context, messages []map[string]any, tools []ToolDef) (Result, error) {
	tp := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		tp = append(tp, map[string]any{
			"type": "function",
			"function": map[string]any{
				"name":        t.Name,
				"description": t.Description,
				"parameters":  t.Schema,
			},
		})
	}
	body := map[string]any{"model": p.Model, "messages": messages, "tools": tp, "tool_choice": "auto"}
	var raw map[string]any
	if err := p.HTTP.modelJSON(ctx, p.BaseURL+"/chat/completions", p.headers(), body, decodeChatStream, &raw); err != nil {
		return Result{}, err
	}
	return parseChatCompatible(raw, messages)
}

func parseChatCompatible(raw map[string]any, messages []map[string]any) (Result, error) {
	choices, _ := raw["choices"].([]any)
	if len(choices) == 0 {
		return Result{}, fmt.Errorf("provider returned no choices")
	}
	choice, _ := choices[0].(map[string]any)
	if reason := stringValue(choice["finish_reason"]); reason != "" && reason != "stop" && reason != "tool_calls" {
		return Result{}, fmt.Errorf("provider stopped: %s", reason)
	}
	msg, _ := choice["message"].(map[string]any)
	result := Result{}
	if s, ok := msg["content"].(string); ok {
		result.Text = s
	}
	calls, _ := msg["tool_calls"].([]any)
	for _, c := range calls {
		obj, _ := c.(map[string]any)
		id, _ := obj["id"].(string)
		fn, _ := obj["function"].(map[string]any)
		name, _ := fn["name"].(string)
		argstr, _ := fn["arguments"].(string)
		var args map[string]any
		if argstr != "" {
			if err := json.Unmarshal([]byte(argstr), &args); err != nil {
				return Result{}, fmt.Errorf("invalid tool arguments for %s: %w", name, err)
			}
		}
		result.ToolCalls = append(result.ToolCalls, ToolCall{ID: id, Name: name, Arguments: args})
	}
	assistant := map[string]any{"role": "assistant", "content": result.Text}
	if len(calls) > 0 {
		assistant["tool_calls"] = calls
	}
	stateMessages := append(append([]map[string]any(nil), messages...), assistant)
	result.Raw = chatState{Messages: stateMessages}
	return result, nil
}
