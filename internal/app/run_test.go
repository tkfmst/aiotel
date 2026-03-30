package app

import (
	"context"
	"errors"
	"log"
	"strings"
	"testing"

	"github.com/tkfmst/aiotel/internal/claude"
)

type fakeRecorder struct {
	records []recordedEvent
}

type recordedEvent struct {
	userName string
	usage    claude.SkillUsage
}

func (f *fakeRecorder) Record(_ context.Context, userName string, usage claude.SkillUsage) error {
	f.records = append(f.records, recordedEvent{
		userName: userName,
		usage:    usage,
	})
	return nil
}

func (f *fakeRecorder) Shutdown(context.Context) error {
	return nil
}

func TestRunProcessesMixedJSONL(t *testing.T) {
	t.Parallel()

	var logBuffer strings.Builder
	input := strings.Join([]string{
		// assistant: Skill tool_use (will be resolved by the user line later)
		`{"type":"assistant","timestamp":"2026-03-29T08:00:00.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_use","id":"toolu_skill1","name":"Skill","input":{"skill":"skill-installer"}}]}}`,
		// user: tool_result for the above skill (success)
		`{"type":"user","timestamp":"2026-03-29T08:00:01.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_skill1","content":"Launching skill: skill-installer"}]}}`,
		// assistant: non-Skill tool_use (Bash)
		`{"type":"assistant","timestamp":"2026-03-29T08:00:02.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"main","message":{"content":[{"type":"tool_use","id":"toolu_bash1","name":"Bash","input":{"command":"ls"}}]}}`,
		// malformed JSON
		`{"type":"user"`,
		// assistant: another Skill tool_use
		`{"type":"assistant","timestamp":"2026-03-29T08:00:03.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"feature/test","message":{"content":[{"type":"tool_use","id":"toolu_skill2","name":"Skill","input":{"skill":"pr-review-toolkit"}}]}}`,
		// user: tool_result for the second skill (error)
		`{"type":"user","timestamp":"2026-03-29T08:00:04.000Z","cwd":"/path/to/repository/aiotel","gitBranch":"feature/test","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_skill2","content":"Error: skill not found","is_error":true}]}}`,
	}, "\n")

	recorder := &fakeRecorder{}
	summary, err := Run(context.Background(), strings.NewReader(input), "alice", recorder, log.New(&logBuffer, "", 0))
	if err != nil {
		t.Fatalf("Run() error = %v", err)
	}

	// 6 lines total
	if summary.RecordsSeen != 6 {
		t.Fatalf("summary.RecordsSeen = %d, want %d", summary.RecordsSeen, 6)
	}
	// 2 skill usages emitted (from the 2 user tool_result lines)
	if summary.EventsEmitted != 2 {
		t.Fatalf("summary.EventsEmitted = %d, want %d", summary.EventsEmitted, 2)
	}
	// 3 skipped: 2 assistant lines (pending, no immediate output) + 1 Bash assistant line
	if summary.Skipped != 3 {
		t.Fatalf("summary.Skipped = %d, want %d", summary.Skipped, 3)
	}
	// 1 malformed
	if summary.Malformed != 1 {
		t.Fatalf("summary.Malformed = %d, want %d", summary.Malformed, 1)
	}

	if len(recorder.records) != 2 {
		t.Fatalf("len(recorder.records) = %d, want %d", len(recorder.records), 2)
	}
	if recorder.records[0].userName != "alice" {
		t.Fatalf("recorder.records[0].userName = %q, want %q", recorder.records[0].userName, "alice")
	}
	if recorder.records[0].usage.SkillName != "skill-installer" {
		t.Fatalf("records[0].SkillName = %q, want %q", recorder.records[0].usage.SkillName, "skill-installer")
	}
	if !recorder.records[0].usage.Success {
		t.Fatal("records[0].Success = false, want true")
	}
	if recorder.records[1].usage.SkillName != "pr-review-toolkit" {
		t.Fatalf("records[1].SkillName = %q, want %q", recorder.records[1].usage.SkillName, "pr-review-toolkit")
	}
	if recorder.records[1].usage.Success {
		t.Fatal("records[1].Success = true, want false")
	}
}

func TestResolveUserPrefersEnvironmentValue(t *testing.T) {
	t.Parallel()

	got := ResolveUser(func(key string) string {
		if key == "AIOTEL_USER" {
			return "override-user"
		}
		return ""
	}, func() (string, error) {
		return "", errors.New("should not be called")
	})

	if got != "override-user" {
		t.Fatalf("ResolveUser() = %q, want %q", got, "override-user")
	}
}

func TestResolveUserFallsBackToCurrentUser(t *testing.T) {
	t.Parallel()

	got := ResolveUser(func(string) string { return "" }, func() (string, error) {
		return "local-user", nil
	})

	if got != "local-user" {
		t.Fatalf("ResolveUser() = %q, want %q", got, "local-user")
	}
}
