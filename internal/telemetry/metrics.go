package telemetry

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/tkfmst/aiotel/internal/claude"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	otelmetric "go.opentelemetry.io/otel/metric"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
)

const (
	defaultServiceName   = "aiotel-claude-skill-metrics"
	defaultExportEvery   = 5 * time.Second
	meterName            = "github.com/tkfmst/aiotel"
	skillUsageMetricName = "aiotel_skill_usage_total"
)

type Recorder struct {
	provider *sdkmetric.MeterProvider
	counter  otelmetric.Int64Counter
}

func NewRecorder(ctx context.Context) (*Recorder, error) {
	serviceName := strings.TrimSpace(os.Getenv("OTEL_SERVICE_NAME"))
	if serviceName == "" {
		serviceName = defaultServiceName
	}

	exporter, err := otlpmetrichttp.New(ctx)
	if err != nil {
		return nil, fmt.Errorf("create OTLP metric exporter: %w", err)
	}

	res, err := resource.Merge(
		resource.Default(),
		resource.NewSchemaless(attribute.String("service.name", serviceName)),
	)
	if err != nil {
		return nil, fmt.Errorf("build resource: %w", err)
	}

	provider := sdkmetric.NewMeterProvider(
		sdkmetric.WithResource(res),
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter, sdkmetric.WithInterval(exportInterval()))),
	)

	meterInstance := provider.Meter(meterName)
	counter, err := meterInstance.Int64Counter(
		skillUsageMetricName,
		otelmetric.WithDescription("Total number of Claude skill invocations parsed from session logs."),
	)
	if err != nil {
		return nil, fmt.Errorf("create counter: %w", err)
	}

	return &Recorder{
		provider: provider,
		counter:  counter,
	}, nil
}

func (r *Recorder) Record(ctx context.Context, userName string, usage claude.SkillUsage) error {
	r.counter.Add(ctx, 1, otelmetric.WithAttributes(
		attribute.String("user", userName),
		attribute.String("repository", usage.Repository),
		attribute.String("branch", usage.Branch),
		attribute.String("skill_name", usage.SkillName),
		attribute.String("success", fmt.Sprintf("%t", usage.Success)),
	))
	return nil
}

func (r *Recorder) Shutdown(ctx context.Context) error {
	return r.provider.Shutdown(ctx)
}

func exportInterval() time.Duration {
	value := os.Getenv("AIOTEL_METRIC_EXPORT_INTERVAL")
	if value == "" {
		return defaultExportEvery
	}

	duration, err := time.ParseDuration(value)
	if err != nil {
		return defaultExportEvery
	}

	return duration
}
