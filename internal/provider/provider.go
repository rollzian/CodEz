package provider

import (
	"context"
)

type ToolDef struct {
	Name        string
	Description string
	Schema      map[string]any
}

type ToolCall struct {
	ID        string
	Name      string
	Arguments map[string]any
}

type Result struct {
	Text      string
	ToolCalls []ToolCall
	Raw       any
}

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type Provider interface {
	Complete(ctx context.Context, messages []Message, tools []ToolDef) (Result, error)
	Continue(ctx context.Context, messages []Message, tools []ToolDef, prior Result, outputs map[string]string) (Result, error)
}
