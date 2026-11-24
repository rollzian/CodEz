package auxia

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
)

const BaseURL = "https://auxia.space/codez-cloud"

var deviceSecret = regexp.MustCompile(`^[A-Za-z0-9_-]{43}$`)
var deviceUserCode = regexp.MustCompile(`^[A-F0-9]{20}$`)
var itemID = regexp.MustCompile(`^[a-f0-9]{24}$`)

type Client struct {
	base  string
	token string
	http  *http.Client
}

func New(token string) *Client {
	return &Client{BaseURL, token, &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}

type Failure struct {
	Status int
	Code   string
}

func (e *Failure) Error() string { return fmt.Sprintf("Auxia Cloud HTTP %d (%s)", e.Status, e.Code) }
func (c *Client) request(ctx context.Context, method, path string, input, output any) error {
	var b []byte
	if input != nil {
		var e error
		b, e = json.Marshal(input)
		if e != nil {
			return e
		}
	}
	req, e := http.NewRequestWithContext(ctx, method, c.base+"/v1"+path, bytes.NewReader(b))
	if e != nil {
		return e
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, e := c.http.Do(req)
	if e != nil {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		return errors.New("Auxia Cloud connection unavailable")
	}
	defer resp.Body.Close()
	data, e := io.ReadAll(io.LimitReader(resp.Body, 1048577))
	if e != nil || len(data) > 1048576 {
		return errors.New("Auxia Cloud response invalid or too large")
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		var v struct {
			Error string `json:"error"`
		}
		_ = json.Unmarshal(data, &v)
		if len(v.Error) > 64 || strings.IndexFunc(v.Error, func(r rune) bool { return !(r >= 'a' && r <= 'z' || r == '_') }) >= 0 {
			v.Error = ""
		}
		if v.Error == "" {
			v.Error = "request_failed"
		}
		return &Failure{resp.StatusCode, v.Error}
	}
	if output == nil {
		var ack struct {
			OK bool `json:"ok"`
		}
		if json.Unmarshal(data, &ack) != nil || !ack.OK {
			return errors.New("Auxia Cloud did not confirm the operation")
		}
	} else if json.Unmarshal(data, output) != nil {
		return errors.New("Auxia Cloud returned an invalid response; check server deployment")
	}
	return nil
}

type Device struct {
	DeviceCode      string `json:"device_code"`
	UserCode        string `json:"user_code"`
	VerificationURI string `json:"verification_uri"`
	Interval        int    `json:"interval"`
	ExpiresIn       int    `json:"expires_in"`
}
type Profile struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}
type Item struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Detail string `json:"detail"`
	State  string `json:"state"`
	URL    string `json:"url"`
}

func (c *Client) Login(ctx context.Context, show func(Device)) (string, error) {
	var d Device
	if e := c.request(ctx, "POST", "/device/start", map[string]string{}, &d); e != nil {
		return "", e
	}
	u, e := url.Parse(d.VerificationURI)
	expected, _ := url.Parse(c.base)
	if e != nil || u.Scheme != expected.Scheme || u.Host != expected.Host || u.User != nil || u.Fragment != "" || u.Path != expected.Path+"/activate" || u.Query().Get("code") != d.UserCode || !deviceSecret.MatchString(d.DeviceCode) || !deviceUserCode.MatchString(d.UserCode) || d.Interval < 1 || d.Interval > 30 || d.ExpiresIn < 1 || d.ExpiresIn > 600 {
		return "", errors.New("invalid Auxia authorization challenge")
	}
	show(d)
	ctx, cancel := context.WithTimeout(ctx, time.Duration(d.ExpiresIn)*time.Second)
	defer cancel()
	for {
		t := time.NewTimer(time.Duration(d.Interval) * time.Second)
		select {
		case <-ctx.Done():
			t.Stop()
			return "", ctx.Err()
		case <-t.C:
		}
		var result struct {
			Token string `json:"access_token"`
		}
		e := c.request(ctx, "POST", "/device/poll", map[string]string{"device_code": d.DeviceCode}, &result)
		if e == nil {
			if !deviceSecret.MatchString(result.Token) {
				return "", errors.New("empty Auxia session")
			}
			return result.Token, nil
		}
		var failure *Failure
		if !errors.As(e, &failure) {
			return "", e
		}
		if failure.Code == "slow_down" && failure.Status == 429 {
			d.Interval = min(30, d.Interval+2)
			continue
		}
		if failure.Code != "authorization_pending" || failure.Status != 400 {
			return "", e
		}
	}
}
func (c *Client) Me(ctx context.Context) (Profile, error) {
	var p Profile
	e := c.request(ctx, "GET", "/me", nil, &p)
	if e == nil && (!itemID.MatchString(p.ID) || p.Name == "") {
		e = errors.New("invalid Auxia profile")
	}
	return p, e
}
func (c *Client) List(ctx context.Context, kind string) ([]Item, error) {
	if !validKind(kind) {
		return nil, errors.New("unknown collection")
	}
	var v struct {
		Items []Item `json:"items"`
	}
	e := c.request(ctx, "GET", "/"+kind, nil, &v)
	if e == nil && (v.Items == nil || !validItems(v.Items)) {
		e = errors.New("invalid Auxia collection")
	}
	return v.Items, e
}
func validItems(items []Item) bool {
	for _, item := range items {
		if !itemID.MatchString(item.ID) || item.Name == "" {
			return false
		}
		if item.URL != "" {
			u, e := url.Parse(item.URL)
			if e != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
				return false
			}
		}
	}
	return true
}
func validKind(k string) bool {
	return k == "workspaces" || k == "teams" || k == "friends" || k == "projects"
}
func (c *Client) Create(ctx context.Context, kind string, fields map[string]string) error {
	if !validKind(kind) {
		return errors.New("unknown collection")
	}
	return c.request(ctx, "POST", "/"+kind, fields, nil)
}
func (c *Client) Action(ctx context.Context, kind, id, action string, fields map[string]string) error {
	if !validKind(kind) || !itemID.MatchString(id) || !(action == "accept" || action == "invite" || action == "delete") {
		return errors.New("invalid action")
	}
	return c.request(ctx, "POST", "/"+kind+"/"+url.PathEscape(id)+"/"+action, fields, nil)
}
func (c *Client) Logout(ctx context.Context) error {
	return c.request(ctx, "POST", "/logout", map[string]string{}, nil)
}

func (c *Client) TeamMembers(ctx context.Context, id string) ([]Item, error) {
	if !itemID.MatchString(id) {
		return nil, errors.New("invalid team ID")
	}
	var v struct {
		Items []Item `json:"items"`
	}
	e := c.request(ctx, "GET", "/teams/"+id+"/members", nil, &v)
	if e == nil && (v.Items == nil || !validItems(v.Items)) {
		e = errors.New("invalid Auxia collection")
	}
	return v.Items, e
}
