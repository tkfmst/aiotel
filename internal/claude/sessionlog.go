package claude

import (
	"bytes"
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

var commandNameRe = regexp.MustCompile(`<command-name>/([^<]+)</command-name>`)

const (
	unknownLabel = "unknown"

	// pendingDirectCommand is a synthetic key used for direct slash command pending entries.
	// Only one direct command can be pending at a time.
	pendingDirectCommand = "__direct_command__"
)

type SkillUsage struct {
	OccurredAt time.Time
	Repository string
	Branch     string
	SkillName  string
	Success    bool
}

// SkillExtractor extracts skill invocations from session log lines.
// It detects three patterns:
//   - Direct slash command: user message with <command-name>, confirmed by subsequent isMeta message
//   - Implicit Skill tool (parent): user message with toolUseResult containing commandName
//   - Implicit Skill tool (subagent): assistant tool_use (name=Skill) → user tool_result pair
type SkillExtractor struct {
	pending map[string]pendingSkill
}

type pendingSkill struct {
	skillName  string
	occurredAt time.Time
	repository string
	branch     string
}

func NewSkillExtractor() *SkillExtractor {
	return &SkillExtractor{pending: make(map[string]pendingSkill)}
}

// Process parses a single JSONL line and returns SkillUsage entries found in it.
func (e *SkillExtractor) Process(line []byte) ([]SkillUsage, error) {
	if len(bytes.TrimSpace(line)) == 0 {
		return nil, nil
	}

	var record sessionRecord
	if err := json.Unmarshal(line, &record); err != nil {
		return nil, fmt.Errorf("decode claude record: %w", err)
	}

	switch record.Type {
	case "assistant":
		e.trackSkillToolUse(record)
		return nil, nil
	case "user":
		return e.processUser(record), nil
	default:
		return nil, nil
	}
}

type sessionRecord struct {
	Type          string          `json:"type"`
	Timestamp     string          `json:"timestamp"`
	Cwd           string          `json:"cwd"`
	GitBranch     string          `json:"gitBranch"`
	Message       json.RawMessage `json:"message"`
	ToolUseResult json.RawMessage `json:"toolUseResult,omitempty"`
	IsMeta        bool            `json:"isMeta,omitempty"`
}

// skillToolUseResult represents the toolUseResult field when the tool is Skill.
type skillToolUseResult struct {
	Success     *bool  `json:"success"`
	CommandName string `json:"commandName"`
}

type messageEnvelope struct {
	Content json.RawMessage `json:"content"`
}

type contentBlock struct {
	Type      string          `json:"type"`
	ID        string          `json:"id"`
	Name      string          `json:"name"`
	Input     json.RawMessage `json:"input"`
	ToolUseID string          `json:"tool_use_id"`
	IsError   *bool           `json:"is_error,omitempty"`
}

type skillInput struct {
	Skill string `json:"skill"`
}

// trackSkillToolUse stores pending Skill tool_use entries from assistant messages.
// Used as fallback for subagent logs where toolUseResult is absent.
func (e *SkillExtractor) trackSkillToolUse(record sessionRecord) {
	blocks := parseContentBlocks(record.Message)
	occurredAt, _ := time.Parse(time.RFC3339Nano, record.Timestamp)

	for _, b := range blocks {
		if b.Type != "tool_use" || b.Name != "Skill" || b.ID == "" {
			continue
		}
		var input skillInput
		if err := json.Unmarshal(b.Input, &input); err != nil || strings.TrimSpace(input.Skill) == "" {
			continue
		}
		e.pending[b.ID] = pendingSkill{
			skillName:  strings.TrimSpace(input.Skill),
			occurredAt: occurredAt,
			repository: repositoryFromCwd(record.Cwd),
			branch:     labelOrUnknown(record.GitBranch),
		}
	}
}

func (e *SkillExtractor) processUser(record sessionRecord) []SkillUsage {
	// Confirm pending direct command when isMeta follow-up arrives
	if record.IsMeta {
		if p, ok := e.pending[pendingDirectCommand]; ok {
			delete(e.pending, pendingDirectCommand)
			return []SkillUsage{{
				OccurredAt: p.occurredAt,
				Repository: p.repository,
				Branch:     p.branch,
				SkillName:  p.skillName,
				Success:    true,
			}}
		}
		return nil
	}

	// Discard unconfirmed direct command candidate (e.g. built-in command)
	delete(e.pending, pendingDirectCommand)

	occurredAt, _ := time.Parse(time.RFC3339Nano, record.Timestamp)
	repo := repositoryFromCwd(record.Cwd)
	branch := labelOrUnknown(record.GitBranch)

	// Pattern 1: Direct slash command — store as pending, confirmed by next isMeta
	if skillName := extractCommandName(record.Message); skillName != "" {
		e.pending[pendingDirectCommand] = pendingSkill{
			skillName:  skillName,
			occurredAt: occurredAt,
			repository: repo,
			branch:     branch,
		}
		return nil
	}

	// Pattern 2: toolUseResult.commandName (parent session)
	if r := parseSkillToolUseResult(record.ToolUseResult); r != nil {
		e.consumePending(record.Message)
		success := true
		if r.Success != nil {
			success = *r.Success
		}
		return []SkillUsage{{
			OccurredAt: occurredAt,
			Repository: repo,
			Branch:     branch,
			SkillName:  r.CommandName,
			Success:    success,
		}}
	}

	// Pattern 3: Fallback — resolve pending assistant tool_use (subagent logs)
	return e.resolvePending(record)
}

// consumePending removes matching pending entries so they are not double-counted.
func (e *SkillExtractor) consumePending(raw json.RawMessage) {
	for _, b := range parseContentBlocks(raw) {
		if b.Type == "tool_result" && b.ToolUseID != "" {
			delete(e.pending, b.ToolUseID)
		}
	}
}

// resolvePending matches tool_result blocks against pending Skill tool_use entries.
func (e *SkillExtractor) resolvePending(record sessionRecord) []SkillUsage {
	blocks := parseContentBlocks(record.Message)
	var usages []SkillUsage

	for _, b := range blocks {
		if b.Type != "tool_result" || b.ToolUseID == "" {
			continue
		}
		p, ok := e.pending[b.ToolUseID]
		if !ok {
			continue
		}
		delete(e.pending, b.ToolUseID)

		success := true
		if b.IsError != nil && *b.IsError {
			success = false
		}

		usages = append(usages, SkillUsage{
			OccurredAt: p.occurredAt,
			Repository: p.repository,
			Branch:     p.branch,
			SkillName:  p.skillName,
			Success:    success,
		})
	}
	return usages
}

// extractCommandName extracts a skill name from <command-name>/skill</command-name>
// in a user message with string content.
func extractCommandName(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var env messageEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return ""
	}
	var s string
	if err := json.Unmarshal(env.Content, &s); err != nil {
		return ""
	}
	m := commandNameRe.FindStringSubmatch(s)
	if len(m) < 2 {
		return ""
	}
	return strings.TrimSpace(m[1])
}

// parseSkillToolUseResult extracts a Skill-specific toolUseResult.
// Returns nil if the field is absent or not a Skill result.
func parseSkillToolUseResult(raw json.RawMessage) *skillToolUseResult {
	if len(raw) == 0 {
		return nil
	}
	var r skillToolUseResult
	if err := json.Unmarshal(raw, &r); err != nil {
		return nil
	}
	if r.CommandName == "" {
		return nil
	}
	return &r
}

func parseContentBlocks(raw json.RawMessage) []contentBlock {
	if len(raw) == 0 {
		return nil
	}
	var env messageEnvelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil
	}
	var blocks []contentBlock
	_ = json.Unmarshal(env.Content, &blocks)
	return blocks
}

func repositoryFromCwd(cwd string) string {
	cleaned := strings.TrimSpace(cwd)
	if cleaned == "" {
		return unknownLabel
	}

	base := filepath.Base(cleaned)
	if base == "" || base == "." || base == string(filepath.Separator) {
		return unknownLabel
	}

	return base
}

func labelOrUnknown(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return unknownLabel
	}

	return trimmed
}
