package tracing

import "context"

// Init is a no-op placeholder until full OTel wiring lands (observability
// profile A). Tracing stays disabled while endpoint is empty; the returned
// shutdown func is always safe to call.
func Init(_ context.Context, endpoint, serviceName string) (func(context.Context) error, error) {
	_ = endpoint
	_ = serviceName
	return func(context.Context) error { return nil }, nil
}
