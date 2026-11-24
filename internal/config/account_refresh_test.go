package config

import (
	"context"
	"github.com/AuxiaCorp/CodEz/internal/auth"
	"testing"
	"time"
)

func TestRefreshRejectedUnexpiredToken(t *testing.T) {
	t.Setenv("XDG_CONFIG_HOME", t.TempDir())
	d, err := Dir()
	if err != nil {
		t.Fatal(err)
	}
	a := auth.Account{ClientID: "oaiapp_test", Subject: "u", AccessToken: "old", RefreshToken: "refresh", ExpiresAt: time.Now().Add(time.Hour)}
	if err = saveAccount(d, a); err != nil {
		t.Fatal(err)
	}
	calls := 0
	refresh := func(ctx context.Context, a auth.Account) (auth.Account, error) {
		calls++
		a.AccessToken = "fresh"
		return a, nil
	}
	key, err := chatGPTKey(context.Background(), "", refresh)
	if err != nil || key != "old" || calls != 0 {
		t.Fatal(key, err, calls)
	}
	key, err = chatGPTKey(context.Background(), "old", refresh)
	if err != nil || key != "fresh" || calls != 1 {
		t.Fatal(key, err, calls)
	}
	key, err = chatGPTKey(context.Background(), "old", refresh)
	if err != nil || key != "fresh" || calls != 1 {
		t.Fatal(key, err, calls)
	}
}
