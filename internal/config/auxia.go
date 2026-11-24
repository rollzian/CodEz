package config

import (
	"os"
	"path/filepath"
	"strings"
)

func AuxiaToken() (string, error) {
	d, e := Dir()
	if e != nil {
		return "", e
	}
	b, e := privateRead(d, "auxia-session")
	return strings.TrimSpace(string(b)), e
}
func SaveAuxiaToken(token string) error {
	d, e := Dir()
	if e != nil {
		return e
	}
	return atomic(d, "auxia-session", []byte(token))
}
func RemoveAuxiaToken() error {
	d, e := Dir()
	if e != nil {
		return e
	}
	e = os.Remove(filepath.Join(d, "auxia-session"))
	if os.IsNotExist(e) {
		return nil
	}
	return e
}
