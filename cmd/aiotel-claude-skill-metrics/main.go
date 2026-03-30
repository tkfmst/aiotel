package main

import (
	"context"
	"log"
	"os"
	"time"

	"github.com/tkfmst/aiotel/internal/app"
	"github.com/tkfmst/aiotel/internal/telemetry"
)

func main() {
	os.Exit(run())
}

func run() int {
	logger := log.New(os.Stderr, "", log.LstdFlags)
	ctx := context.Background()

	recorder, err := telemetry.NewRecorder(ctx)
	if err != nil {
		logger.Printf("initialize telemetry: %v", err)
		return 1
	}

	userName := app.ResolveUser(os.Getenv, app.CurrentOSUserName)
	summary, runErr := app.Run(ctx, os.Stdin, userName, recorder, logger)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	shutdownErr := recorder.Shutdown(shutdownCtx)
	if summary.RecordsSeen > 0 || summary.EventsEmitted > 0 || summary.Malformed > 0 {
		logger.Printf(
			"processed=%d emitted=%d skipped=%d malformed=%d",
			summary.RecordsSeen,
			summary.EventsEmitted,
			summary.Skipped,
			summary.Malformed,
		)
	}

	if runErr != nil {
		logger.Printf("process stdin: %v", runErr)
		return 1
	}

	if shutdownErr != nil {
		logger.Printf("shutdown telemetry: %v", shutdownErr)
		return 1
	}

	return 0
}
