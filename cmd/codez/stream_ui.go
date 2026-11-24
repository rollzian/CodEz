package main

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/AuxiaCorp/CodEz/internal/provider"
)

// Hold a possible key prefix until the next delta arrives. Never print a partial secret.
type streamRedactor struct {
	key, pending string
}

func (r *streamRedactor) push(text string, end bool) string {
	if r.key == "" {
		return clean(text)
	}
	r.pending += clean(text)
	var out strings.Builder
	for {
		before, after, found := strings.Cut(r.pending, r.key)
		if !found {
			break
		}
		out.WriteString(before)
		out.WriteString("[REDACTED]")
		r.pending = after
	}
	keep := 0
	if !end {
		for n := min(len(r.pending), len(r.key)-1); n > 0; n-- {
			if strings.HasSuffix(r.pending, r.key[:n]) {
				keep = n
				break
			}
		}
	}
	out.WriteString(r.pending[:len(r.pending)-keep])
	r.pending = r.pending[len(r.pending)-keep:]
	return out.String()
}

func (c console) modelRequest(ctx context.Context, key string, request func(context.Context) (provider.Result, error)) (provider.Result, error) {
	stop := c.progress("Waiting for model")
	var received strings.Builder
	started := false
	redactor := streamRedactor{key: clean(key)}
	if os.Getenv("CODEZ_NO_STREAM") == "" {
		ctx = provider.WithTextStream(ctx, func(delta string) {
			if delta == "" {
				return
			}
			if !started {
				stop()
				started = true
				c.answerHeader()
			}
			received.WriteString(delta)
			fmt.Fprint(c.out, redactor.push(delta, false))
		})
	}
	res, err := request(ctx)
	if !started {
		stop()
		if err == nil && res.Text != "" {
			c.answer(redact(res.Text, key))
		}
		return res, err
	}
	if err == nil && strings.HasPrefix(res.Text, received.String()) {
		fmt.Fprint(c.out, redactor.push(strings.TrimPrefix(res.Text, received.String()), true))
	} else {
		// A failed stream may end in the middle of a secret. Discard that suffix.
		redactor.pending = ""
	}
	fmt.Fprintln(c.out)
	if err == nil && !strings.HasPrefix(res.Text, received.String()) && res.Text != "" {
		c.answer(redact(res.Text, key))
	}
	return res, err
}
