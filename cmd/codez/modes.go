package main

import (
	"fmt"
	"github.com/AuxiaCorp/CodEz/internal/provider"
	"strings"
)

type agentMode string

const (
	modeCode   agentMode = "Code"
	modeAsk    agentMode = "Ask"
	modePlan   agentMode = "Plan"
	modeReview agentMode = "Review"
)

var agentModes = []agentMode{modeCode, modeAsk, modePlan, modeReview}

func (m agentMode) allows(name string) bool {
	if m == modeCode {
		return true
	}
	switch name {
	case "list_files", "read_file", "grep", "git_status", "git_diff":
		return true
	}
	return false
}
func (m agentMode) definitions(all []provider.ToolDef) []provider.ToolDef {
	var out []provider.ToolDef
	for _, d := range all {
		if m.allows(d.Name) {
			out = append(out, d)
		}
	}
	return out
}
func systemPrompt(base, model string, m agentMode) string {
	return fmt.Sprintf("You are the active provider model %q with CodEz. When asked who you are, identify yourself as %q with CodEz. Do not claim a different model or invent a version.\nAgent mode: %s. %s\n\n%s", strings.Join(strings.Fields(model), " "), strings.Join(strings.Fields(model), " "), m, map[agentMode]string{modeCode: "Implement authorized changes and verify them.", modeAsk: "Answer questions using read-only tools. Do not edit or execute shell commands.", modePlan: "Create an implementation plan using read-only tools. Do not implement changes.", modeReview: "Review the repository and report findings with evidence. Do not edit or execute shell commands."}[m], base)
}
func (m agentMode) next() agentMode {
	for i, v := range agentModes {
		if v == m {
			return agentModes[(i+1)%len(agentModes)]
		}
	}
	return modeCode
}
