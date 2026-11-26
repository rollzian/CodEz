package provider

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

type textStreamKey struct{}

// WithTextStream enables streaming for model requests made with this context.
func WithTextStream(ctx context.Context, callback func(string)) context.Context {
	return context.WithValue(ctx, textStreamKey{}, callback)
}
func textStream(ctx context.Context) func(string) {
	callback, _ := ctx.Value(textStreamKey{}).(func(string))
	return callback
}

type streamDecoder func(io.Reader, func(string)) (map[string]any, error)

func (h *HTTPClient) modelJSON(ctx context.Context, url string, headers map[string]string, body map[string]any, decoder streamDecoder, out *map[string]any) error {
	callback := textStream(ctx)
	if callback != nil {
		body["stream"] = true
	}
	if callback == nil {
		callback = func(string) {}
	}
	requestHeaders := make(map[string]string, len(headers)+1)
	for k, v := range headers {
		requestHeaders[k] = v
	}
	if body["stream"] == true {
		requestHeaders["Accept"] = "text/event-stream, application/json"
	}
	return h.request(ctx, "POST", url, requestHeaders, body, func(resp *http.Response) error {
		reader := bufio.NewReader(resp.Body)
		// SSE permits a UTF-8 BOM. Remove it before either decoder sees the body.
		if first, _ := reader.Peek(1); len(first) > 0 && first[0] == 0xef {
			if bom, _ := reader.Peek(3); string(bom) == "\xef\xbb\xbf" {
				_, _ = reader.Discard(3)
			}
		}
		mediaType := strings.TrimSpace(strings.SplitN(resp.Header.Get("Content-Type"), ";", 2)[0])
		if !strings.EqualFold(mediaType, "text/event-stream") && !looksLikeSSE(reader) {
			return decodeJSON(reader, out)
		}
		value, err := decoder(reader, callback)
		if err == nil {
			*out = value
		}
		return err
	})
}

// Some proxies replace the event stream Content-Type. Detect only exact SSE
// field prefixes, without consuming data or waiting for the whole response.
func looksLikeSSE(r *bufio.Reader) bool {
	for i := 0; i < 64; i++ {
		b, err := r.Peek(i + 1)
		if err != nil {
			return false
		}
		var prefix string
		switch b[i] {
		case '\r', '\n', ' ', '\t':
			continue
		case ':':
			return true
		case 'e':
			prefix = "event:"
		case 'd':
			prefix = "data:"
		case 'i':
			prefix = "id:"
		case 'r':
			prefix = "retry:"
		default:
			return false
		}
		b, _ = r.Peek(i + len(prefix))
		return len(b) >= i+len(prefix) && string(b[i:]) == prefix
	}
	return false
}

// consumeEvents accepts SSE comments and multi-line data fields. Bounds are per stream.
func consumeEvents(r io.Reader, event func(string) (bool, error)) error {
	const limit = 8 << 20
	s := bufio.NewScanner(io.LimitReader(r, limit+1))
	s.Buffer(make([]byte, 4096), limit)
	var data strings.Builder
	total := 0
	dispatch := func() (bool, error) {
		if data.Len() == 0 {
			return false, nil
		}
		payload := strings.TrimSuffix(data.String(), "\n")
		data.Reset()
		return event(payload)
	}
	for s.Scan() {
		line := s.Text()
		total += len(line) + 1
		if total > limit {
			return errors.New("provider stream exceeds size limit")
		}
		if line == "" {
			done, err := dispatch()
			if done || err != nil {
				return err
			}
			continue
		}
		if strings.HasPrefix(line, "data:") {
			data.WriteString(strings.TrimPrefix(strings.TrimPrefix(line, "data:"), " "))
			data.WriteByte('\n')
		}
	}
	if err := s.Err(); err != nil {
		return err
	}
	if data.Len() > 0 {
		done, err := dispatch()
		if done || err != nil {
			return err
		}
	}
	return io.ErrUnexpectedEOF
}
func object(v any) map[string]any { m, _ := v.(map[string]any); return m }
func stringValue(v any) string    { s, _ := v.(string); return s }
func eventJSON(s string) (map[string]any, error) {
	var m map[string]any
	err := json.Unmarshal([]byte(s), &m)
	return m, err
}
func eventIndex(v any) (int, error) {
	n, ok := v.(float64)
	if !ok || n < 0 || n > 1024 || float64(int(n)) != n {
		return 0, errors.New("invalid stream index")
	}
	return int(n), nil
}

func decodeResponsesStream(r io.Reader, emit func(string)) (map[string]any, error) {
	var final map[string]any
	err := consumeEvents(r, func(s string) (bool, error) {
		m, e := eventJSON(s)
		if e != nil {
			return false, e
		}
		switch m["type"] {
		case "response.output_text.delta":
			emit(stringValue(m["delta"]))
		case "response.completed":
			final = object(m["response"])
			if final == nil {
				return false, errors.New("missing completed response")
			}
			return true, nil
		case "response.failed", "response.incomplete", "error":
			return false, fmt.Errorf("provider stream ended: %s", m["type"])
		}
		return false, nil
	})
	return final, err
}

type streamedCall struct{ id, name, args strings.Builder }

func decodeChatStream(r io.Reader, emit func(string)) (map[string]any, error) {
	var content, reasoning strings.Builder
	var hasReasoning bool
	calls := map[int]*streamedCall{}
	finish := ""
	err := consumeEvents(r, func(s string) (bool, error) {
		if s == "[DONE]" {
			if finish == "" {
				return false, errors.New("stream ended without finish reason")
			}
			return true, nil
		}
		m, e := eventJSON(s)
		if e != nil {
			return false, e
		}
		if m["error"] != nil {
			return false, errors.New("provider stream error")
		}
		choices, _ := m["choices"].([]any)
		if len(choices) == 0 {
			return false, nil
		}
		choice := object(choices[0])
		delta := object(choice["delta"])
		if fragment, ok := delta["reasoning_content"].(string); ok {
			hasReasoning = true
			reasoning.WriteString(fragment)
		}
		text := stringValue(delta["content"])
		content.WriteString(text)
		if text != "" {
			emit(text)
		}
		tools, _ := delta["tool_calls"].([]any)
		for _, v := range tools {
			t := object(v)
			i, e := eventIndex(t["index"])
			if e != nil {
				return false, e
			}
			c := calls[i]
			if c == nil {
				c = &streamedCall{}
				calls[i] = c
			}
			c.id.WriteString(stringValue(t["id"]))
			f := object(t["function"])
			c.name.WriteString(stringValue(f["name"]))
			c.args.WriteString(stringValue(f["arguments"]))
		}
		if v := stringValue(choice["finish_reason"]); v != "" {
			finish = v
			if v != "stop" && v != "tool_calls" {
				return false, fmt.Errorf("provider stopped: %s", v)
			}
		}
		return false, nil
	})
	if err != nil {
		return nil, err
	}
	msg := map[string]any{"role": "assistant", "content": content.String()}
	if hasReasoning {
		msg["reasoning_content"] = reasoning.String()
	}
	if len(calls) > 0 {
		ts := make([]any, 0, len(calls))
		for i := 0; i < len(calls); i++ {
			c := calls[i]
			if c == nil || c.id.Len() == 0 || c.name.Len() == 0 {
				return nil, errors.New("incomplete streamed tool call")
			}
			ts = append(ts, map[string]any{"id": c.id.String(), "type": "function", "function": map[string]any{"name": c.name.String(), "arguments": c.args.String()}})
		}
		msg["tool_calls"] = ts
	}
	return map[string]any{"choices": []any{map[string]any{"message": msg, "finish_reason": finish}}}, nil
}

type anthropicBlock struct {
	data    map[string]any
	partial strings.Builder
	stopped bool
}

func decodeAnthropicStream(r io.Reader, emit func(string)) (map[string]any, error) {
	var final map[string]any
	blocks := map[int]*anthropicBlock{}
	err := consumeEvents(r, func(s string) (bool, error) {
		m, e := eventJSON(s)
		if e != nil {
			return false, e
		}
		switch m["type"] {
		case "message_start":
			final = object(m["message"])
			if final == nil {
				return false, errors.New("missing message")
			}
		case "content_block_start":
			i, e := eventIndex(m["index"])
			if e != nil {
				return false, e
			}
			if blocks[i] != nil {
				return false, errors.New("duplicate content block")
			}
			d := object(m["content_block"])
			if d == nil {
				return false, errors.New("invalid content block")
			}
			blocks[i] = &anthropicBlock{data: d}
			if d["type"] == "text" {
				emit(stringValue(d["text"]))
			}
		case "content_block_delta":
			i, e := eventIndex(m["index"])
			if e != nil {
				return false, e
			}
			b := blocks[i]
			if b == nil || b.stopped {
				return false, errors.New("unexpected content delta")
			}
			d := object(m["delta"])
			switch d["type"] {
			case "text_delta":
				t := stringValue(d["text"])
				b.data["text"] = stringValue(b.data["text"]) + t
				emit(t)
			case "input_json_delta":
				b.partial.WriteString(stringValue(d["partial_json"]))
			case "thinking_delta":
				b.data["thinking"] = stringValue(b.data["thinking"]) + stringValue(d["thinking"])
			case "signature_delta":
				b.data["signature"] = stringValue(b.data["signature"]) + stringValue(d["signature"])
			}
		case "content_block_stop":
			i, e := eventIndex(m["index"])
			if e != nil {
				return false, e
			}
			b := blocks[i]
			if b == nil || b.stopped {
				return false, errors.New("unexpected block stop")
			}
			if b.partial.Len() > 0 {
				var input map[string]any
				if e = json.Unmarshal([]byte(b.partial.String()), &input); e != nil {
					return false, e
				}
				b.data["input"] = input
			}
			b.stopped = true
		case "message_delta":
			if final == nil {
				return false, errors.New("missing message start")
			}
			d := object(m["delta"])
			for k, v := range d {
				final[k] = v
			}
		case "message_stop":
			if final == nil {
				return false, errors.New("missing message start")
			}
			switch final["stop_reason"] {
			case "end_turn", "tool_use", "stop_sequence":
			default:
				return false, fmt.Errorf("provider stopped: %v", final["stop_reason"])
			}
			content := make([]any, 0, len(blocks))
			for i := 0; i < len(blocks); i++ {
				b := blocks[i]
				if b == nil || !b.stopped {
					return false, errors.New("incomplete content block")
				}
				content = append(content, b.data)
			}
			final["content"] = content
			return true, nil
		case "error":
			return false, errors.New("provider stream error")
		}
		return false, nil
	})
	return final, err
}
