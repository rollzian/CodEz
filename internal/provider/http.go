package provider

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"
)

type HTTPClient struct{ C *http.Client }

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
		return fmt.Errorf("invalid provider JSON: %w", err)
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
		resp.Body.Close()
		if (resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500) && attempt+1 < attempts {
			if err := sleepBackoff(ctx, attempt, resp.Header.Get("Retry-After")); err != nil {
				return err
			}
			continue
		}
		return fmt.Errorf("provider HTTP %d", resp.StatusCode)
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
