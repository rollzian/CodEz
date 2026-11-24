package provider

import (
	"context"
	"errors"
	"sort"
)

// Models discovers model IDs exposed by the configured server.
func Models(ctx context.Context, p Provider) ([]string, error) {
	var endpoint string
	var headers map[string]string
	var h *HTTPClient
	switch v := p.(type) {
	case *OpenAI:
		endpoint = v.BaseURL + "/models"
		headers = v.headers()
		h = v.HTTP
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
	var data struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if e := h.JSON(ctx, "GET", endpoint, headers, nil, &data); e != nil {
		return nil, e
	}
	ids := make([]string, 0, len(data.Data))
	seen := map[string]bool{}
	for _, m := range data.Data {
		if m.ID != "" && !seen[m.ID] {
			seen[m.ID] = true
			ids = append(ids, m.ID)
		}
	}
	sort.Strings(ids)
	return ids, nil
}
