package auxia

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestLoginAndCloudOperations(t *testing.T) {
	device := strings.Repeat("a", 43)
	token := strings.Repeat("b", 43)
	userCode := strings.Repeat("C", 20)
	id := strings.Repeat("d", 24)
	polls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/codez-cloud/v1/device/start":
			if r.Method != "POST" || r.Header.Get("Authorization") != "" {
				t.Error("unexpected auth request")
			}
			_ = json.NewEncoder(w).Encode(Device{device, userCode, "http://" + r.Host + "/codez-cloud/activate?code=" + userCode, 1, 10})
		case "/codez-cloud/v1/device/poll":
			var data map[string]string
			_ = json.NewDecoder(r.Body).Decode(&data)
			if data["device_code"] != device {
				t.Error("wrong device code")
			}
			polls++
			if polls == 1 {
				w.WriteHeader(400)
				fmt.Fprint(w, `{"error":"authorization_pending"}`)
				return
			}
			_ = json.NewEncoder(w).Encode(map[string]string{"access_token": token})
		case "/codez-cloud/v1/me":
			if r.Header.Get("Authorization") != "Bearer "+token {
				t.Error("missing cloud credentials")
			}
			_ = json.NewEncoder(w).Encode(Profile{id, "Alice"})
		case "/codez-cloud/v1/workspaces":
			if r.Header.Get("Authorization") != "Bearer "+token {
				t.Error("missing token")
			}
			if r.Method == "POST" {
				var data map[string]string
				_ = json.NewDecoder(r.Body).Decode(&data)
				if data["name"] != "Workspace" {
					t.Error(data)
				}
				fmt.Fprint(w, `{"ok":true}`)
			} else {
				_ = json.NewEncoder(w).Encode(map[string]any{"items": []Item{{ID: id, Name: "Workspace", State: "owner"}}})
			}
		case "/codez-cloud/v1/workspaces/" + id + "/delete":
			fmt.Fprint(w, `{"ok":true}`)
		default:
			t.Error(r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	c := New("")
	c.base = server.URL + "/codez-cloud"
	shown := false
	got, e := c.Login(context.Background(), func(d Device) {
		shown = true
		if d.UserCode != userCode {
			t.Error("wrong code")
		}
	})
	if e != nil || got != token || !shown {
		t.Fatalf("login: %v, shown %v", e, shown)
	}
	c.token = got
	p, e := c.Me(context.Background())
	if e != nil || p.ID != id {
		t.Fatalf("profile: %+v %v", p, e)
	}
	if e = c.Create(context.Background(), "workspaces", map[string]string{"name": "Workspace"}); e != nil {
		t.Fatal(e)
	}
	items, e := c.List(context.Background(), "workspaces")
	if e != nil || len(items) != 1 || items[0].ID != id {
		t.Fatalf("list: %+v %v", items, e)
	}
	if e = c.Action(context.Background(), "workspaces", id, "delete", nil); e != nil {
		t.Fatal(e)
	}
}

func TestRejectsFalseSuccessAndExternalAuthorization(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/device/start") {
			_ = json.NewEncoder(w).Encode(Device{strings.Repeat("a", 43), strings.Repeat("B", 20), "https://evil.example/activate", 1, 10})
			return
		}
		fmt.Fprint(w, "<html>not an API</html>")
	}))
	defer server.Close()
	c := New("")
	c.base = server.URL
	if _, e := c.Login(context.Background(), func(Device) { t.Error("opened untrusted URL") }); e == nil {
		t.Fatal("accepted external URL")
	}
	if e := c.Create(context.Background(), "workspaces", map[string]string{"name": "x"}); e == nil {
		t.Fatal("accepted HTML as success")
	}
}
