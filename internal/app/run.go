package app

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/user"
	"strings"

	"github.com/tkfmst/aiotel/internal/claude"
)

const unknownUser = "unknown"

type Recorder interface {
	Record(context.Context, string, claude.SkillUsage) error
	Shutdown(context.Context) error
}

type Logger interface {
	Printf(string, ...any)
}

type Summary struct {
	RecordsSeen   int
	EventsEmitted int
	Skipped       int
	Malformed     int
}

func Run(ctx context.Context, input io.Reader, userName string, recorder Recorder, logger Logger) (Summary, error) {
	reader := bufio.NewReader(input)
	summary := Summary{}
	extractor := claude.NewSkillExtractor()

	for {
		line, err := reader.ReadBytes('\n')
		for _, chunk := range splitJSONL(line) {
			if len(bytes.TrimSpace(chunk)) == 0 {
				continue
			}
			summary.RecordsSeen++

			usages, extractErr := extractor.Process(chunk)
			if extractErr != nil {
				summary.Malformed++
				logger.Printf("skip malformed line %d: %v", summary.RecordsSeen, extractErr)
			} else if len(usages) > 0 {
				for _, usage := range usages {
					if recordErr := recorder.Record(ctx, userName, usage); recordErr != nil {
						return summary, fmt.Errorf("record metric on line %d: %w", summary.RecordsSeen, recordErr)
					}
					summary.EventsEmitted++
				}
			} else {
				summary.Skipped++
			}
		}

		if err == nil {
			continue
		}
		if errors.Is(err, io.EOF) {
			return summary, nil
		}

		return summary, fmt.Errorf("read stdin: %w", err)
	}
}

// splitJSONL splits a byte slice that may contain multiple concatenated JSON
// objects (e.g. "}{" without newline between files) into individual chunks.
func splitJSONL(data []byte) [][]byte {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 {
		return nil
	}
	// Fast path: no concatenation
	if !bytes.Contains(trimmed, []byte("}{")) {
		return [][]byte{trimmed}
	}
	parts := bytes.Split(trimmed, []byte("}{"))
	result := make([][]byte, len(parts))
	for i, p := range parts {
		switch {
		case i == 0:
			result[i] = append(p, '}')
		case i == len(parts)-1:
			result[i] = append([]byte{'{'}, p...)
		default:
			result[i] = append([]byte{'{'}, append(p, '}')...)
		}
	}
	return result
}

func ResolveUser(lookupEnv func(string) string, currentUser func() (string, error)) string {
	if value := strings.TrimSpace(lookupEnv("AIOTEL_USER")); value != "" {
		return value
	}

	if currentUser != nil {
		if value, err := currentUser(); err == nil {
			if trimmed := strings.TrimSpace(value); trimmed != "" {
				return trimmed
			}
		}
	}

	if value := strings.TrimSpace(lookupEnv("USER")); value != "" {
		return value
	}

	return unknownUser
}

func CurrentOSUserName() (string, error) {
	current, err := user.Current()
	if err != nil {
		return "", err
	}

	return current.Username, nil
}
