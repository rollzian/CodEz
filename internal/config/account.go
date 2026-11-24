package config

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"time"

	"github.com/AuxiaCorp/CodEz/internal/auth"
)

func privateRead(d, name string) ([]byte, error) {
	p := filepath.Join(d, name)
	s, err := os.Lstat(p)
	if err != nil {
		return nil, err
	}
	if !s.Mode().IsRegular() || s.Mode().Perm()&0077 != 0 || s.Size() > 1<<20 {
		return nil, errors.New("unsafe credential file")
	}
	return os.ReadFile(p)
}
func readAccount(d string) (auth.Account, error) {
	var a auth.Account
	b, err := privateRead(d, "chatgpt-account.json")
	if err != nil {
		return a, err
	}
	if err = json.Unmarshal(b, &a); err != nil {
		return a, errors.New("invalid saved ChatGPT account")
	}
	if a.ClientID == "" || a.Subject == "" || a.AccessToken == "" || a.RefreshToken == "" {
		return a, errors.New("incomplete saved ChatGPT account")
	}
	return a, nil
}
func saveAccount(d string, a auth.Account) error {
	b, err := json.Marshal(a)
	if err != nil {
		return err
	}
	return atomic(d, "chatgpt-account.json", b)
}
func accountLock(d string) (func(), error) {
	f, err := os.OpenFile(filepath.Join(d, "chatgpt.lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, errors.New("ChatGPT account is in use by another CodEz process")
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); _ = f.Close() }, nil
}
func ChatGPTAccount() (auth.Account, error) {
	d, err := Dir()
	if err != nil {
		return auth.Account{}, err
	}
	return readAccount(d)
}
func LoginChatGPT(ctx context.Context, show func(string), newAccount bool) (auth.Account, error) {
	d, err := Dir()
	if err != nil {
		return auth.Account{}, err
	}
	unlock, err := accountLock(d)
	if err != nil {
		return auth.Account{}, err
	}
	defer unlock()
	b, err := privateRead(d, "host-id")
	if os.IsNotExist(err) {
		host, e := auth.HostID()
		if e != nil {
			return auth.Account{}, e
		}
		b = []byte(host)
		err = atomic(d, "host-id", b)
	}
	if err != nil {
		return auth.Account{}, err
	}
	var previous *auth.Account
	if !newAccount {
		a, e := readAccount(d)
		if e == nil {
			previous = &a
		} else if !os.IsNotExist(e) {
			return auth.Account{}, e
		}
	}
	a, err := auth.New().LoginChatGPT(ctx, string(b), previous, show)
	if err != nil {
		return auth.Account{}, err
	}
	return a, saveAccount(d, a)
}
func ChatGPTKey(ctx context.Context) (string, error) {
	return chatGPTKey(ctx, "", auth.New().Refresh)
}

// RecoverChatGPTKey refreshes the rejected token even before its local expiry.
// If another process already rotated it, use that replacement instead.
func RecoverChatGPTKey(ctx context.Context, rejected string) (string, error) {
	if rejected == "" {
		return "", errors.New("missing rejected account token")
	}
	return chatGPTKey(ctx, rejected, auth.New().Refresh)
}

func chatGPTKey(ctx context.Context, rejected string, refresh func(context.Context, auth.Account) (auth.Account, error)) (string, error) {
	d, err := Dir()
	if err != nil {
		return "", err
	}
	unlock, err := accountLock(d)
	if err != nil {
		return "", err
	}
	defer unlock()
	a, err := readAccount(d)
	if err != nil {
		return "", err
	}
	if time.Until(a.ExpiresAt) < 2*time.Minute || (rejected != "" && a.AccessToken == rejected) {
		a, err = refresh(ctx, a)
		if err != nil {
			return "", err
		}
		if err = saveAccount(d, a); err != nil {
			return "", err
		}
	}
	return a.AccessToken, nil
}
