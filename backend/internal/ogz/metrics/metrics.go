package metrics

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics holds all Prometheus collectors in one place (tech-stack §2).
type Metrics struct {
	registry     *prometheus.Registry
	HTTPRequests *prometheus.CounterVec
	JobsTotal    *prometheus.CounterVec
}

func New() *Metrics {
	reg := prometheus.NewRegistry()
	m := &Metrics{
		registry: reg,
		HTTPRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "ogz_http_requests_total",
			Help: "Total HTTP requests by method, path and status.",
		}, []string{"method", "path", "status"}),
		JobsTotal: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "ogz_jobs_total",
			Help: "Total jobs by status transition.",
		}, []string{"status"}),
	}
	reg.MustRegister(m.HTTPRequests, m.JobsTotal)
	return m
}

func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{})
}
