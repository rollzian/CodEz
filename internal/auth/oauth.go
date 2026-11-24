package auth

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const resource = "https://api.openai.com/v1"
const issuer = "https://auth.openai.com"
const tokenEndpoint = issuer + "/api/accounts/oauth/token"
const planScopes = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"

// Account holds the credentials for a single registered ChatGPT client.
type Account struct {
	ClientID     string    `json:"client_id"`
	Subject      string    `json:"subject"`
	Email        string    `json:"email,omitempty"`
	AccessToken  string    `json:"access_token"`
	RefreshToken string    `json:"refresh_token"`
	IDToken      string    `json:"id_token"`
	Scope        string    `json:"scope"`
	ExpiresAt    time.Time `json:"expires_at"`
}

type tokenResponse struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	IDToken      string `json:"id_token"`
	Scope        string `json:"scope"`
	TokenType    string `json:"token_type"`
	ExpiresIn    int64  `json:"expires_in"`
}

type Client struct{ HTTP *http.Client }

func New() *Client {
	return &Client{HTTP: &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}
func randomString() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
func challenge(verifier string) string {
	h := sha256.Sum256([]byte(verifier))
	return base64.RawURLEncoding.EncodeToString(h[:])
}
func HostID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	b[6] = (b[6] & 15) | 64
	b[8] = (b[8] & 63) | 128
	return fmt.Sprintf("urn:uuid:%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:]), nil
}
func (c *Client) request(ctx context.Context, method, endpoint, kind string, body io.Reader, dst any) error {
	req, err := http.NewRequestWithContext(ctx, method, endpoint, body)
	if err != nil {
		return err
	}
	if kind != "" {
		req.Header.Set("Content-Type", kind)
	}
	req.Header.Set("Accept", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return errors.New("authorization server connection failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("authorization server HTTP %d", resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 {
		return errors.New("invalid authorization response size")
	}
	if err = json.Unmarshal(raw, dst); err != nil {
		return errors.New("invalid authorization response")
	}
	return nil
}
func (c *Client) exchange(ctx context.Context, values url.Values) (tokenResponse, error) {
	var t tokenResponse
	values.Set("resource", resource)
	err := c.request(ctx, http.MethodPost, tokenEndpoint, "application/x-www-form-urlencoded", strings.NewReader(values.Encode()), &t)
	return t, err
}
func (t tokenResponse) validate(scope string) error {
	if t.AccessToken == "" || t.RefreshToken == "" || !strings.EqualFold(t.TokenType, "Bearer") || t.ExpiresIn <= 0 || t.ExpiresIn > 86400*30 {
		return errors.New("incomplete OAuth credentials")
	}
	if scope == "" {
		scope = t.Scope
	}
	scopes := strings.Fields(scope)
	for _, required := range []string{"resource.invoke", "chatgpt.tokens.use.direct"} {
		found := false
		for _, s := range scopes {
			if s == required {
				found = true
				break
			}
		}
		if !found {
			return errors.New("ChatGPT plan permission not granted")
		}
	}
	return nil
}

type identity struct {
	Issuer   string          `json:"iss"`
	Audience json.RawMessage `json:"aud"`
	Subject  string          `json:"sub"`
	Email    string          `json:"email"`
	Nonce    string          `json:"nonce"`
	Exp      int64           `json:"exp"`
	Azp      string          `json:"azp"`
}

func verifyIDToken(raw, clientID, nonce string, keys []jwk, now time.Time) (identity, error) {
	var id identity
	parts := strings.Split(raw, ".")
	if len(parts) != 3 || len(raw) > 128<<10 {
		return id, errors.New("invalid ID token")
	}
	decode := base64.RawURLEncoding.DecodeString
	head, err := decode(parts[0])
	if err != nil {
		return id, errors.New("invalid ID token header")
	}
	var header struct {
		Alg string `json:"alg"`
		Kid string `json:"kid"`
	}
	if json.Unmarshal(head, &header) != nil || header.Alg != "RS256" || header.Kid == "" {
		return id, errors.New("unsupported ID token signature")
	}
	sig, err := decode(parts[2])
	if err != nil {
		return id, errors.New("invalid ID token signature")
	}
	digest := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	verified := false
	for _, k := range keys {
		if k.Kid != header.Kid || k.Kty != "RSA" || (k.Alg != "" && k.Alg != "RS256") || (k.Use != "" && k.Use != "sig") {
			continue
		}
		n, e := decode(k.N)
		ex, exerr := decode(k.E)
		if e != nil || exerr != nil || len(n) < 256 || len(n) > 1024 || len(ex) == 0 || len(ex) > 4 {
			continue
		}
		exp := int(new(big.Int).SetBytes(ex).Int64())
		if exp < 3 || exp%2 == 0 {
			continue
		}
		pub := rsa.PublicKey{N: new(big.Int).SetBytes(n), E: exp}
		if rsa.VerifyPKCS1v15(&pub, crypto.SHA256, digest[:], sig) == nil {
			verified = true
			break
		}
	}
	if !verified {
		return id, errors.New("ID token signature verification failed")
	}
	claims, err := decode(parts[1])
	if err != nil || json.Unmarshal(claims, &id) != nil {
		return id, errors.New("invalid ID token claims")
	}
	var aud string
	var audiences []string
	if json.Unmarshal(id.Audience, &aud) == nil {
		audiences = []string{aud}
	} else if json.Unmarshal(id.Audience, &audiences) != nil {
		return id, errors.New("invalid ID token audience")
	}
	found := false
	for _, a := range audiences {
		if a == clientID {
			found = true
		}
	}
	if !found || (len(audiences) > 1 && id.Azp != clientID) || (id.Azp != "" && id.Azp != clientID) || id.Issuer != issuer || id.Subject == "" || id.Exp <= now.Unix() || (nonce != "" && subtle.ConstantTimeCompare([]byte(id.Nonce), []byte(nonce)) != 1) {
		return id, errors.New("ID token identity validation failed")
	}
	return id, nil
}

type jwk struct {
	Kid string `json:"kid"`
	Kty string `json:"kty"`
	Alg string `json:"alg"`
	Use string `json:"use"`
	N   string `json:"n"`
	E   string `json:"e"`
}

func (c *Client) verify(ctx context.Context, raw, clientID, nonce string) (identity, error) {
	var data struct {
		Keys []jwk `json:"keys"`
	}
	if err := c.request(ctx, http.MethodGet, issuer+"/.well-known/jwks.json", "", nil, &data); err != nil {
		return identity{}, err
	}
	return verifyIDToken(raw, clientID, nonce, data.Keys, time.Now())
}

type callbackResult struct {
	Code, ClientID string
	Err            error
}

func callbackHandler(state, clientID string, result chan<- callbackResult) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Content-Security-Policy", "default-src 'none'")
		w.Header().Set("Referrer-Policy", "no-referrer")
		if r.Method != http.MethodGet || r.URL.Path != "/auth/callback" {
			http.NotFound(w, r)
			return
		}
		q := r.URL.Query()
		if len(q["state"]) != 1 || subtle.ConstantTimeCompare([]byte(q.Get("state")), []byte(state)) != 1 {
			http.Error(w, "Invalid authorization state", http.StatusBadRequest)
			return
		}
		out := callbackResult{Code: q.Get("code"), ClientID: q.Get("client_id")}
		if q.Get("error") != "" {
			out.Err = errors.New("authorization declined or failed")
		} else if len(q["code"]) != 1 || out.Code == "" {
			out.Err = errors.New("authorization code missing")
		} else if clientID == "dynamic_agent_client" {
			if len(q["client_id"]) != 1 || !strings.HasPrefix(out.ClientID, "oaiapp_") {
				out.Err = errors.New("issued client ID missing or invalid")
			}
		} else if out.ClientID == "" {
			out.ClientID = clientID
		} else if out.ClientID != clientID {
			out.Err = errors.New("registered client ID changed")
		}
		select {
		case result <- out:
		default:
		}
		fmt.Fprint(w, "Authorization received. Return to CodEz to complete sign-in.")
	}
}
func (c *Client) LoginChatGPT(ctx context.Context, host string, previous *Account, show func(string)) (Account, error) {
	var account Account
	verifier, err := randomString()
	if err != nil {
		return account, err
	}
	state, err := randomString()
	if err != nil {
		return account, err
	}
	nonce, err := randomString()
	if err != nil {
		return account, err
	}
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return account, err
	}
	defer listener.Close()
	redirect := "http://" + listener.Addr().String() + "/auth/callback"
	clientID := "dynamic_agent_client"
	if previous != nil {
		clientID = previous.ClientID
	}
	result := make(chan callbackResult, 1)
	srv := &http.Server{Handler: callbackHandler(state, clientID, result), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, MaxHeaderBytes: 16 << 10}
	go func() { _ = srv.Serve(listener) }()
	defer srv.Close()
	q := url.Values{"client_id": {clientID}, "ext_agent_host_id": {host}, "response_type": {"code"}, "redirect_uri": {redirect}, "scope": {planScopes}, "resource": {resource}, "state": {state}, "nonce": {nonce}, "code_challenge_method": {"S256"}, "code_challenge": {challenge(verifier)}}
	if previous == nil {
		q.Set("agent_name_hint", "CodEz")
	}
	show(issuer + "/api/accounts/authorize?" + q.Encode())
	var cb callbackResult
	select {
	case <-ctx.Done():
		return account, ctx.Err()
	case cb = <-result:
	}
	if cb.Err != nil {
		return account, cb.Err
	}
	t, err := c.exchange(ctx, url.Values{"grant_type": {"authorization_code"}, "client_id": {cb.ClientID}, "code": {cb.Code}, "code_verifier": {verifier}, "redirect_uri": {redirect}})
	if err != nil {
		return account, err
	}
	if err = t.validate(""); err != nil {
		return account, err
	}
	id, err := c.verify(ctx, t.IDToken, cb.ClientID, nonce)
	if err != nil {
		return account, err
	}
	if previous != nil && id.Subject != previous.Subject {
		return account, errors.New("account does not match saved registration")
	}
	return Account{ClientID: cb.ClientID, Subject: id.Subject, Email: id.Email, AccessToken: t.AccessToken, RefreshToken: t.RefreshToken, IDToken: t.IDToken, Scope: t.Scope, ExpiresAt: time.Now().Add(time.Duration(t.ExpiresIn) * time.Second)}, nil
}
func (c *Client) Refresh(ctx context.Context, a Account) (Account, error) {
	t, err := c.exchange(ctx, url.Values{"grant_type": {"refresh_token"}, "client_id": {a.ClientID}, "refresh_token": {a.RefreshToken}})
	if err != nil {
		return a, err
	}
	scope := t.Scope
	if scope == "" {
		scope = a.Scope
	}
	if err = t.validate(scope); err != nil {
		return a, err
	}
	if t.IDToken != "" {
		id, err := c.verify(ctx, t.IDToken, a.ClientID, "")
		if err != nil {
			return a, err
		}
		if id.Subject != a.Subject {
			return a, errors.New("refreshed identity changed")
		}
		a.IDToken = t.IDToken
	}
	a.AccessToken = t.AccessToken
	a.RefreshToken = t.RefreshToken
	a.Scope = scope
	a.ExpiresAt = time.Now().Add(time.Duration(t.ExpiresIn) * time.Second)
	return a, nil
}
func (c *Client) LoginOpenRouter(ctx context.Context, show func(string), readCode func() (string, error)) (string, error) {
	verifier, err := randomString()
	if err != nil {
		return "", err
	}
	q := url.Values{"code_challenge": {challenge(verifier)}, "code_challenge_method": {"S256"}, "key_label": {"CodEz"}}
	show("https://openrouter.ai/auth?" + q.Encode())
	code, err := readCode()
	if err != nil {
		return "", err
	}
	if code == "" || len(code) > 8192 || strings.ContainsAny(code, " \r\n\t") {
		return "", errors.New("invalid authorization code")
	}
	payload, _ := json.Marshal(map[string]string{"code": code, "code_verifier": verifier, "code_challenge_method": "S256"})
	var result struct {
		Key string `json:"key"`
	}
	if err = c.request(ctx, http.MethodPost, "https://openrouter.ai/api/v1/auth/keys", "application/json", strings.NewReader(string(payload)), &result); err != nil {
		return "", err
	}
	if result.Key == "" {
		return "", errors.New("OpenRouter did not issue an API key")
	}
	return result.Key, nil
}
