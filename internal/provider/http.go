package provider

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type HTTPClient struct{ C *http.Client }

type HTTPError struct {
	Status                 int
	Code, Param, RequestID string
}

func (e *HTTPError) Error() string {
	message := fmt.Sprintf("provider HTTP %d", e.Status)
	if e.Code != "" {
		message += " (" + e.Code + ")"
	}
	if e.Param != "" {
		message += " [parameter " + e.Param + "]"
	}
	if e.RequestID != "" {
		message += " [request " + e.RequestID + "]"
	}
	return message
}

func diagnosticID(s string) string {
	if len(s) > 128 || strings.ContainsAny(s, "\r\n\t ") {
		return ""
	}
	for _, r := range s {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_' || r == '.') {
			return ""
		}
	}
	return s
}
func providerError(resp *http.Response) error {
	err := &HTTPError{Status: resp.StatusCode, RequestID: diagnosticID(resp.Header.Get("x-request-id"))}
	// Extract machine-readable codes only; never echo arbitrary error bodies or credentials.
	var body struct {
		Error struct {
			Code  json.RawMessage `json:"code"`
			Type  string          `json:"type"`
			Param string          `json:"param"`
		} `json:"error"`
	}
	if data, e := io.ReadAll(io.LimitReader(resp.Body, 16385)); e == nil && len(data) <= 16384 && json.Unmarshal(data, &body) == nil {
		var code string
		if json.Unmarshal(body.Error.Code, &code) != nil {
			var numeric json.Number
			if json.Unmarshal(body.Error.Code, &numeric) == nil {
				code = numeric.String()
			}
		}
		err.Code = diagnosticID(code)
		if err.Code == "" {
			err.Code = diagnosticID(body.Error.Type)
		}
		err.Param = diagnosticID(body.Error.Param)
	}
	return err
}
func IsUnauthorized(err error) bool {
	var status *HTTPError
	return errors.As(err, &status) && status.Status == http.StatusUnauthorized
}

func NewHTTPClient() *HTTPClient {
	return &HTTPClient{C: &http.Client{Timeout: 90 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}}
}

func (h *HTTPClient) JSON(ctx context.Context, method, url string, headers map[string]string, body any, out any) error {
	return h.request(ctx, method, url, headers, body, func(resp *http.Response) error { return decodeJSON(resp.Body, out) })
}

func decodeJSON(reader io.Reader, out any) error {
	data, err := io.ReadAll(io.LimitReader(reader, (8<<20)+1))
	if err != nil {
		return err
	}
	if len(data) > 8<<20 {
		return fmt.Errorf("provider response exceeds size limit")
	}
	if err = json.Unmarshal(data, out); err != nil {
		return fmt.Errorf("invalid provider JSON; check endpoint, proxy and response format: %w", err)
	}
	return nil
}

func (h *HTTPClient) request(ctx context.Context, method, url string, headers map[string]string, body any, consume func(*http.Response) error) error {
	var payload []byte
	var err error
	if body != nil {
		payload, err = json.Marshal(body)
		if err != nil {
			return err
		}
	}
	const attempts = 4
	for attempt := 0; attempt < attempts; attempt++ {
		req, err := http.NewRequestWithContext(ctx, method, url, bytes.NewReader(payload))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Accept", "application/json")
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := h.C.Do(req)
		if err != nil {
			if attempt+1 == attempts || ctx.Err() != nil {
				return err
			}
			if err := sleepBackoff(ctx, attempt, ""); err != nil {
				return err
			}
			continue
		}
		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			err := consume(resp)
			resp.Body.Close()
			return err
		}
		failure := providerError(resp)
		resp.Body.Close()
		if (resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500) && attempt+1 < attempts {
			if err := sleepBackoff(ctx, attempt, resp.Header.Get("Retry-After")); err != nil {
				return err
			}
			continue
		}
		return failure
	}
	return fmt.Errorf("provider request exhausted retries")
}

func sleepBackoff(ctx context.Context, attempt int, retryAfter string) error {
	if retryAfter != "" {
		if seconds, err := strconv.Atoi(retryAfter); err == nil && seconds >= 0 {
			if seconds > 30 {
				seconds = 30
			}
			t := time.NewTimer(time.Duration(seconds) * time.Second)
			defer t.Stop()
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-t.C:
				return nil
			}
		}
	}
	capDelay := 250 * time.Millisecond * time.Duration(1<<attempt)
	var b [8]byte
	_, _ = rand.Read(b[:])
	jitter := time.Duration(binary.LittleEndian.Uint64(b[:]) % uint64(capDelay+1))
	t := time.NewTimer(jitter)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
