package provider

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHTTPUnauthorizedNotRetried(t *testing.T) {
	calls := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; w.WriteHeader(401); fmt.Fprint(w, "secret") }))
	defer s.Close()
	_, err := Catalog(context.Background(), NewChatCompatible(s.URL, "secret", "x"), "")
	if !IsUnauthorized(err) || calls != 1 || err.Error() != "provider HTTP 401" {
		t.Fatal(calls, err)
	}
}
func TestPricesAndFree(t *testing.T) {
	a := ModelInfo{Pricing: map[string]string{"prompt": "0", "completion": "0"}}
	if !a.Free() {
		t.Fatal("zero prices rejected")
	}
	a.Pricing["request"] = "0.001"
	if a.Free() {
		t.Fatal("paid request marked free")
	}
	a.Pricing["prompt"] = "NaN"
	if _, _, ok := a.Prices(); ok {
		t.Fatal("NaN price accepted")
	}
	if (ModelInfo{}).Free() {
		t.Fatal("unknown price marked free")
	}
}

func Test401Diagnostics(t *testing.T) {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("x-request-id", "req_example")
		w.WriteHeader(401)
		fmt.Fprint(w, `{"error":{"code":"subscription_sharing_invalid_user","message":"SECRET"}}`)
	}))
	defer s.Close()
	_, err := Catalog(context.Background(), NewChatCompatible(s.URL, "secret", "x"), "")
	if !IsUnauthorized(err) || err.Error() != "provider HTTP 401 (subscription_sharing_invalid_user) [request req_example]" {
		t.Fatal(err)
	}
}
