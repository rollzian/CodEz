package auth

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func jsonResponse(v any) *http.Response {
	b, _ := json.Marshal(v)
	return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(string(b)))}
}
func signedIdentity(t *testing.T, key *rsa.PrivateKey, claims map[string]any) string {
	t.Helper()
	enc := base64.RawURLEncoding
	header := enc.EncodeToString([]byte(`{"alg":"RS256","kid":"test-key"}`))
	body, _ := json.Marshal(claims)
	unsigned := header + "." + enc.EncodeToString(body)
	hash := sha256.Sum256([]byte(unsigned))
	sig, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, hash[:])
	if err != nil {
		t.Fatal(err)
	}
	return unsigned + "." + enc.EncodeToString(sig)
}
func TestChatGPTRegistrationAndRefresh(t *testing.T) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	enc := base64.RawURLEncoding
	keys := []jwk{{Kid: "test-key", Kty: "RSA", Alg: "RS256", N: enc.EncodeToString(key.N.Bytes()), E: enc.EncodeToString(big.NewInt(int64(key.E)).Bytes())}}
	var authorize url.Values
	var exchanges int
	client := &Client{HTTP: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		switch r.URL.String() {
		case issuer + "/.well-known/jwks.json":
			return jsonResponse(map[string]any{"keys": keys}), nil
		case tokenEndpoint:
			if err := r.ParseForm(); err != nil {
				t.Fatal(err)
			}
			exchanges++
			if r.Form.Get("client_id") != "oaiapp_test" || r.Form.Get("resource") != resource {
				t.Fatalf("bad token request: %v", r.Form)
			}
			if exchanges == 1 {
				if r.Form.Get("grant_type") != "authorization_code" || r.Form.Get("code") != "test-code" || r.Form.Get("redirect_uri") != authorize.Get("redirect_uri") || challenge(r.Form.Get("code_verifier")) != authorize.Get("code_challenge") {
					t.Fatal("PKCE exchange mismatch")
				}
				id := signedIdentity(t, key, map[string]any{"iss": issuer, "aud": "oaiapp_test", "sub": "user1", "email": "user@example.invalid", "nonce": authorize.Get("nonce"), "exp": time.Now().Add(time.Hour).Unix()})
				return jsonResponse(tokenResponse{AccessToken: "access1", RefreshToken: "refresh1", IDToken: id, Scope: planScopes, TokenType: "Bearer", ExpiresIn: 3600}), nil
			}
			if r.Form.Get("grant_type") != "refresh_token" || r.Form.Get("refresh_token") != "refresh1" {
				t.Fatal("invalid refresh grant")
			}
			return jsonResponse(tokenResponse{AccessToken: "access2", RefreshToken: "refresh2", TokenType: "Bearer", ExpiresIn: 3600}), nil
		default:
			return nil, fmt.Errorf("unexpected endpoint %s", r.URL)
		}
	})}}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	a, err := client.LoginChatGPT(ctx, "urn:uuid:test", nil, func(link string) {
		u, e := url.Parse(link)
		if e != nil {
			t.Fatal(e)
		}
		authorize = u.Query()
		if u.Host != "auth.openai.com" || authorize.Get("client_id") != "dynamic_agent_client" || authorize.Get("agent_name_hint") != "CodEz" || authorize.Get("code_challenge_method") != "S256" {
			t.Fatal("invalid sign-in URL")
		}
		callback := authorize.Get("redirect_uri") + "?" + url.Values{"state": {authorize.Get("state")}, "code": {"test-code"}, "client_id": {"oaiapp_test"}}.Encode()
		r, e := http.Get(callback)
		if e != nil {
			t.Fatal(e)
		}
		r.Body.Close()
		if r.StatusCode != 200 {
			t.Fatal(r.StatusCode)
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	if a.AccessToken != "access1" || a.Subject != "user1" || a.ClientID != "oaiapp_test" {
		t.Fatal("invalid account")
	}
	a, err = client.Refresh(ctx, a)
	if err != nil || a.AccessToken != "access2" || a.RefreshToken != "refresh2" || a.Scope != planScopes || a.Subject != "user1" {
		t.Fatal("refresh failed", err)
	}
}
func TestCallbackRejectsWrongStateAndClient(t *testing.T) {
	result := make(chan callbackResult, 1)
	h := callbackHandler("expected", "oaiapp_saved", result)
	rr := httptest.NewRecorder()
	h(rr, httptest.NewRequest("GET", "/auth/callback?state=wrong&code=abc", nil))
	if rr.Code != 400 || len(result) != 0 {
		t.Fatal("wrong state accepted")
	}
	rr = httptest.NewRecorder()
	h(rr, httptest.NewRequest("GET", "/auth/callback?state=expected&code=abc&client_id=oaiapp_other", nil))
	if (<-result).Err == nil {
		t.Fatal("wrong client accepted")
	}
}
func TestIDTokenClaimsAndSignature(t *testing.T) {
	key, e := rsa.GenerateKey(rand.Reader, 2048)
	if e != nil {
		t.Fatal(e)
	}
	enc := base64.RawURLEncoding
	keys := []jwk{{Kid: "test-key", Kty: "RSA", N: enc.EncodeToString(key.N.Bytes()), E: enc.EncodeToString(big.NewInt(int64(key.E)).Bytes())}}
	now := time.Now()
	claims := map[string]any{"iss": issuer, "aud": "app", "sub": "u", "nonce": "n", "exp": now.Add(time.Hour).Unix()}
	token := signedIdentity(t, key, claims)
	if _, e := verifyIDToken(token, "app", "n", keys, now); e != nil {
		t.Fatal(e)
	}
	if _, e := verifyIDToken(token, "other", "n", keys, now); e == nil {
		t.Fatal("bad audience accepted")
	}
	if _, e := verifyIDToken(token, "app", "bad", keys, now); e == nil {
		t.Fatal("bad nonce accepted")
	}
	if _, e := verifyIDToken(token, "app", "n", keys, now.Add(2*time.Hour)); e == nil {
		t.Fatal("expired token accepted")
	}
	parts := strings.Split(token, ".")
	parts[1] = enc.EncodeToString([]byte(`{"sub":"attacker"}`))
	if _, e := verifyIDToken(strings.Join(parts, "."), "app", "n", keys, now); e == nil {
		t.Fatal("tampered token accepted")
	}
}
func TestOpenRouterPKCE(t *testing.T) {
	var q url.Values
	client := &Client{HTTP: &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.URL.String() != "https://openrouter.ai/api/v1/auth/keys" {
			t.Fatal(r.URL)
		}
		var v map[string]string
		if e := json.NewDecoder(r.Body).Decode(&v); e != nil {
			t.Fatal(e)
		}
		if v["code"] != "code" || v["code_challenge_method"] != "S256" || challenge(v["code_verifier"]) != q.Get("code_challenge") {
			t.Fatal("invalid PKCE")
		}
		return jsonResponse(map[string]string{"key": "test-key"}), nil
	})}}
	key, e := client.LoginOpenRouter(context.Background(), func(s string) {
		u, err := url.Parse(s)
		if err != nil || u.Host != "openrouter.ai" {
			t.Fatal(s)
		}
		q = u.Query()
	}, func() (string, error) { return "code", nil })
	if e != nil || key != "test-key" {
		t.Fatal(e)
	}
}
