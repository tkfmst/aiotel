package claude

import "testing"

func TestDirectSlashCommand(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	// Line 1: <command-name> detected, stored as pending
	cmdLine := []byte(`{"type":"user","timestamp":"2026-03-29T13:15:12.770Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"role":"user","content":"<command-message>skill-test</command-message>\n<command-name>/skill-test</command-name>"}}`)
	usages, err := ext.Process(cmdLine)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("command-name line returned %d usages, want 0 (pending)", len(usages))
	}

	// Line 2: isMeta confirms it is a skill
	metaLine := []byte(`{"type":"user","timestamp":"2026-03-29T13:15:12.771Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"Base directory for this skill: ..."}]}}`)
	usages, err = ext.Process(metaLine)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("isMeta line returned %d usages, want 1", len(usages))
	}

	u := usages[0]
	if u.SkillName != "skill-test" {
		t.Fatalf("SkillName = %q, want %q", u.SkillName, "skill-test")
	}
	if u.Repository != "aiotel" {
		t.Fatalf("Repository = %q, want %q", u.Repository, "aiotel")
	}
	if u.Branch != "main" {
		t.Fatalf("Branch = %q, want %q", u.Branch, "main")
	}
	if !u.Success {
		t.Fatal("Success = false, want true")
	}
	if u.OccurredAt.IsZero() {
		t.Fatal("OccurredAt should be parsed")
	}
}

func TestDirectSlashCommandWithArgs(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	cmdLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp/repo","gitBranch":"dev","message":{"role":"user","content":"<command-message>head</command-message>\n<command-name>/head</command-name>\n<command-args>go.mod</command-args>"}}`)
	usages, _ := ext.Process(cmdLine)
	if len(usages) != 0 {
		t.Fatalf("command-name line returned %d usages, want 0", len(usages))
	}

	metaLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.001Z","cwd":"/tmp/repo","gitBranch":"dev","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"# head skill content\n\nARGUMENTS: go.mod"}]}}`)
	usages, _ = ext.Process(metaLine)
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}
	if usages[0].SkillName != "head" {
		t.Fatalf("SkillName = %q, want %q", usages[0].SkillName, "head")
	}
}

func TestDirectSlashCommandWithNamespace(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	cmdLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp/repo","gitBranch":"dev","message":{"role":"user","content":"<command-message>commit-commands:commit</command-message>\n<command-name>/commit-commands:commit</command-name>"}}`)
	ext.Process(cmdLine)

	metaLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.001Z","cwd":"/tmp/repo","gitBranch":"dev","isMeta":true,"message":{"role":"user","content":[{"type":"text","text":"skill content"}]}}`)
	usages, _ := ext.Process(metaLine)
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}
	if usages[0].SkillName != "commit-commands:commit" {
		t.Fatalf("SkillName = %q, want %q", usages[0].SkillName, "commit-commands:commit")
	}
}

func TestBuiltinCommandIgnored(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	// Built-in command has <command-name> but no isMeta follow-up
	cmdLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp/repo","gitBranch":"main","message":{"role":"user","content":"<command-name>/agents</command-name>\n            <command-message>agents</command-message>\n            <command-args></command-args>"}}`)
	usages, _ := ext.Process(cmdLine)
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0", len(usages))
	}

	// Next non-isMeta message discards the pending
	nextLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/tmp/repo","gitBranch":"main","message":{"role":"user","content":"next user message"}}`)
	usages, _ = ext.Process(nextLine)
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0 (built-in should be discarded)", len(usages))
	}
}

func TestImplicitSkillToolSuccess(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	line := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_abc123","content":"Launching skill: pr-review-toolkit"}]},"toolUseResult":{"success":true,"commandName":"pr-review-toolkit"}}`)
	usages, err := ext.Process(line)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}

	u := usages[0]
	if u.SkillName != "pr-review-toolkit" {
		t.Fatalf("SkillName = %q, want %q", u.SkillName, "pr-review-toolkit")
	}
	if u.Repository != "aiotel" {
		t.Fatalf("Repository = %q, want %q", u.Repository, "aiotel")
	}
	if !u.Success {
		t.Fatal("Success = false, want true")
	}
}

func TestImplicitSkillToolFailure(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	line := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/tmp/repo","gitBranch":"dev","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_err1","content":"Error: skill not found"}]},"toolUseResult":{"success":false,"commandName":"broken-skill"}}`)
	usages, err := ext.Process(line)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}
	if usages[0].Success {
		t.Fatal("Success = true, want false")
	}
	if usages[0].SkillName != "broken-skill" {
		t.Fatalf("SkillName = %q, want %q", usages[0].SkillName, "broken-skill")
	}
}

func TestIgnoresNonSkillToolUseResult(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	line := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/tmp","gitBranch":"main","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_bash1","content":"file1.txt"}]},"toolUseResult":{"stdout":"file1.txt","stderr":"","interrupted":false}}`)
	usages, err := ext.Process(line)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0", len(usages))
	}
}

func TestIgnoresPlainUserText(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	line := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp","gitBranch":"main","message":{"content":"hello world"}}`)
	usages, err := ext.Process(line)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0", len(usages))
	}
}

func TestIgnoresAssistantMessage(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	line := []byte(`{"type":"assistant","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp","gitBranch":"main","message":{"content":[{"type":"tool_use","id":"toolu_abc","name":"Skill","input":{"skill":"some-skill"}}]}}`)
	usages, err := ext.Process(line)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0", len(usages))
	}
}

func TestSubagentSkillToolUse(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	assistantLine := []byte(`{"type":"assistant","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_use","id":"toolu_015fdTDbQAP27JL2yH8agTgw","name":"Skill","input":{"skill":"skill-test"}}]}}`)
	usages, err := ext.Process(assistantLine)
	if err != nil {
		t.Fatalf("Process(assistant) error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("Process(assistant) returned %d usages, want 0", len(usages))
	}

	userLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_015fdTDbQAP27JL2yH8agTgw","content":"Launching skill: skill-test"}]}}`)
	usages, err = ext.Process(userLine)
	if err != nil {
		t.Fatalf("Process(user) error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}

	u := usages[0]
	if u.SkillName != "skill-test" {
		t.Fatalf("SkillName = %q, want %q", u.SkillName, "skill-test")
	}
	if u.Repository != "aiotel" {
		t.Fatalf("Repository = %q, want %q", u.Repository, "aiotel")
	}
	if !u.Success {
		t.Fatal("Success = false, want true")
	}
}

func TestSubagentSkillToolUseIsError(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	assistantLine := []byte(`{"type":"assistant","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp/repo","gitBranch":"dev","message":{"content":[{"type":"tool_use","id":"toolu_sub_err","name":"Skill","input":{"skill":"broken"}}]}}`)
	ext.Process(assistantLine)

	userLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/tmp/repo","gitBranch":"dev","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_sub_err","content":"Error","is_error":true}]}}`)
	usages, err := ext.Process(userLine)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1", len(usages))
	}
	if usages[0].Success {
		t.Fatal("Success = true, want false")
	}
}

func TestParentToolUseResultNotDoubleCounted(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()

	assistantLine := []byte(`{"type":"assistant","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/tmp/repo","gitBranch":"main","message":{"content":[{"type":"tool_use","id":"toolu_dup1","name":"Skill","input":{"skill":"my-skill"}}]}}`)
	ext.Process(assistantLine)

	userLine := []byte(`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/tmp/repo","gitBranch":"main","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_dup1","content":"Launching skill: my-skill"}]},"toolUseResult":{"success":true,"commandName":"my-skill"}}`)
	usages, err := ext.Process(userLine)
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 1 {
		t.Fatalf("returned %d usages, want 1 (should not double-count)", len(usages))
	}
}

func TestRejectsInvalidJSON(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()
	_, err := ext.Process([]byte(`{"type":"user"`))
	if err == nil {
		t.Fatal("error = nil, want non-nil")
	}
}

func TestIgnoresEmptyLine(t *testing.T) {
	t.Parallel()

	ext := NewSkillExtractor()
	usages, err := ext.Process([]byte("  \n"))
	if err != nil {
		t.Fatalf("error = %v", err)
	}
	if len(usages) != 0 {
		t.Fatalf("returned %d usages, want 0", len(usages))
	}
}

func TestRepositoryFromCwdFallback(t *testing.T) {
	t.Parallel()

	if got := repositoryFromCwd(""); got != unknownLabel {
		t.Fatalf("repositoryFromCwd(\"\") = %q, want %q", got, unknownLabel)
	}
	if got := repositoryFromCwd("/"); got != unknownLabel {
		t.Fatalf("repositoryFromCwd(\"/\") = %q, want %q", got, unknownLabel)
	}
}
