package skills

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"
)

const maxSkillSize = 32 << 10
const maxSkills = 128

type Skill struct{ ID, Name, Path string }

// Discover only explicitly designated local skill directories. No scripts are run.
func Discover(workspace, userConfig string) ([]Skill, error) {
	var result []Skill
	for _, scope := range []struct{ name, dir string }{{"workspace", filepath.Join(workspace, ".codez", "skills")}, {"user", filepath.Join(userConfig, "skills")}} {
		dir, err := filepath.EvalSymlinks(scope.dir)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return nil, err
		}
		abs, err := filepath.Abs(scope.dir)
		if err != nil {
			return nil, err
		}
		if dir != abs {
			return nil, fmt.Errorf("symlinked skill directory: %s", scope.name)
		}
		entries, err := os.ReadDir(dir)
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			if !entry.IsDir() || entry.Type()&os.ModeSymlink != 0 || strings.HasPrefix(entry.Name(), ".") {
				continue
			}
			p := filepath.Join(dir, entry.Name(), "SKILL.md")
			info, err := os.Lstat(p)
			if os.IsNotExist(err) {
				continue
			}
			if err != nil {
				return nil, err
			}
			if !info.Mode().IsRegular() || info.Size() > maxSkillSize {
				continue
			}
			if len(result) >= maxSkills {
				return nil, errors.New("skill catalog exceeds 128 entries")
			}
			result = append(result, Skill{scope.name + "/" + entry.Name(), entry.Name(), p})
		}
	}
	sort.Slice(result, func(i, j int) bool { return result[i].ID < result[j].ID })
	return result, nil
}
func (s Skill) Read() (string, error) {
	resolved, err := filepath.EvalSymlinks(s.Path)
	if err != nil {
		return "", err
	}
	if resolved != s.Path {
		return "", errors.New("skill symlink is not allowed")
	}
	info, err := os.Lstat(s.Path)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Size() > maxSkillSize {
		return "", errors.New("invalid skill file")
	}
	f, err := os.Open(s.Path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	b, err := io.ReadAll(io.LimitReader(f, maxSkillSize+1))
	if err != nil {
		return "", err
	}
	if len(b) > maxSkillSize || !utf8.Valid(b) {
		return "", errors.New("skill exceeds size limit or is not UTF-8")
	}
	return string(b), nil
}
