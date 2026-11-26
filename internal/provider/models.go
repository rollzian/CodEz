package provider

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"
)

type ModelInfo struct {
	ID          string            `json:"id"`
	Slug        string            `json:"slug"`
	Name        string            `json:"name"`
	DisplayName string            `json:"display_name"`
	Visibility  string            `json:"visibility"`
	Context     int64             `json:"context_length"`
	Pricing     map[string]string `json:"pricing"`
	Supported   []string          `json:"supported_parameters"`
}

// Pricing is optional metadata. A nonstandard price must not prevent model discovery.
func (m *ModelInfo) UnmarshalJSON(data []byte) error {
	type alias ModelInfo
	var wire struct {
		alias
		Pricing json.RawMessage `json:"pricing"`
	}
	if err := json.Unmarshal(data, &wire); err != nil {
		return err
	}
	*m = ModelInfo(wire.alias)
	var fields map[string]json.RawMessage
	if json.Unmarshal(wire.Pricing, &fields) != nil || len(fields) == 0 {
		return nil
	}
	m.Pricing = make(map[string]string, len(fields))
	for k, raw := range fields {
		var value string
		if json.Unmarshal(raw, &value) != nil {
			var number json.Number
			if json.Unmarshal(raw, &number) == nil {
				value = number.String()
			}
		}
		// Keep unknown entries: an unknown surcharge must never be treated as free.
		m.Pricing[k] = value
	}
	return nil
}

func (m ModelInfo) Prices() (float64, float64, bool) {
	in, e1 := strconv.ParseFloat(m.Pricing["prompt"], 64)
	out, e2 := strconv.ParseFloat(m.Pricing["completion"], 64)
	in, out = in*1e6, out*1e6
	return in, out, e1 == nil && e2 == nil && in >= 0 && out >= 0 && !math.IsNaN(in) && !math.IsNaN(out) && !math.IsInf(in, 0) && !math.IsInf(out, 0)
}
func (m ModelInfo) Free() bool {
	in, out, ok := m.Prices()
	if !ok || in != 0 || out != 0 {
		return false
	}
	for _, v := range m.Pricing {
		n, e := strconv.ParseFloat(v, 64)
		if e != nil || n != 0 {
			return false
		}
	}
	return true
}
func (m ModelInfo) Label() string {
	if m.DisplayName != "" {
		return m.DisplayName
	}
	if m.Name != "" {
		return m.Name
	}
	return m.ID
}

// Models preserves the existing ID-only interface.
func Models(ctx context.Context, p Provider) ([]string, error) {
	models, e := Catalog(ctx, p, "")
	if e != nil {
		return nil, e
	}
	ids := make([]string, 0, len(models))
	for _, m := range models {
		ids = append(ids, m.ID)
	}
	return ids, nil
}

func IsOpenRouter(p Provider) bool {
	v, ok := p.(*ChatCompatible)
	return ok && v.BaseURL == "https://openrouter.ai/api/v1"
}

// Catalog returns models exposed by the configured endpoint. Ranked OpenRouter
// views use its actual server-side benchmark ordering, not invented scores.
func Catalog(ctx context.Context, p Provider, mode string) ([]ModelInfo, error) {
	var endpoint string
	var headers map[string]string
	var h *HTTPClient
	account := false
	switch v := p.(type) {
	case *OpenAI:
		endpoint = v.BaseURL + "/models"
		headers = v.headers()
		h = v.HTTP
		account = v.AccountMode
	case *Anthropic:
		endpoint = v.BaseURL + "/v1/models"
		headers = v.headers()
		h = v.HTTP
	case *ChatCompatible:
		endpoint = v.BaseURL + "/models"
		headers = v.headers()
		h = v.HTTP
	default:
		return nil, errors.New("model discovery unsupported")
	}
	router := IsOpenRouter(p)
	if router {
		// Unlike the public model catalog, /key validates the current credential.
		var credential struct {
			Data struct {
				Label string `json:"label"`
			} `json:"data"`
		}
		if err := h.JSON(ctx, "GET", "https://openrouter.ai/api/v1/key", headers, nil, &credential); err != nil {
			return nil, err
		}
		q := url.Values{"supported_parameters": {"tools"}, "output_modalities": {"text"}}
		switch mode {
		case "best":
			q.Set("sort", "coding-high-to-low")
		case "smart":
			q.Set("sort", "intelligence-high-to-low")
		case "cheap":
			q.Set("sort", "pricing-low-to-high")
		case "expensive":
			q.Set("sort", "pricing-high-to-low")
		}
		endpoint += "?" + q.Encode()
	}
	var data struct {
		Data   []ModelInfo `json:"data"`
		Models []ModelInfo `json:"models"`
	}
	if e := h.JSON(ctx, "GET", endpoint, headers, nil, &data); e != nil {
		return nil, e
	}
	rows := data.Data
	if account {
		rows = data.Models
	}
	seen := map[string]bool{}
	out := make([]ModelInfo, 0, len(rows))
	for _, m := range rows {
		if account {
			if m.Visibility != "list" {
				continue
			}
			m.ID = m.Slug
		}
		if strings.TrimSpace(m.ID) == "" || seen[m.ID] {
			continue
		}
		seen[m.ID] = true
		if router && len(m.Supported) > 0 {
			tools := false
			for _, v := range m.Supported {
				if v == "tools" {
					tools = true
					break
				}
			}
			if !tools {
				continue
			}
		}
		out = append(out, m)
	}
	if !account && !router {
		sort.SliceStable(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	}
	return out, nil
}
