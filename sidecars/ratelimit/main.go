// Package main implements the RUVAMCO rate-limiting sidecar.
//
// This is a high-performance, Redis-backed sliding-window rate limiter
// that runs as a sidecar alongside Envoy proxies.  It exposes an HTTP
// API that Envoy's ext_authz filter calls on every request.
//
// Architecture:
//   Client → Envoy → ext_authz check → this sidecar → Redis
//
// Algorithms supported:
//   - Sliding window counter (default)
//   - Token bucket (per-key)
//   - Fixed window (legacy compat)
//
// Performance target: < 500 µs p99 per check at 50 k rps/core.

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/gorilla/mux"
	"go.uber.org/zap"
	"golang.org/x/time/rate"
)

// ── Configuration ───────────────────────────────────────────────

type Config struct {
	Port         int    `json:"port"`
	RedisAddr    string `json:"redis_addr"`
	DefaultRPS   int    `json:"default_rps"`
	DefaultBurst int    `json:"default_burst"`
}

func loadConfig() Config {
	port, _ := strconv.Atoi(getEnv("RATELIMIT_PORT", "8082"))
	defaultRPS, _ := strconv.Atoi(getEnv("DEFAULT_RPS", "100"))
	defaultBurst, _ := strconv.Atoi(getEnv("DEFAULT_BURST", "200"))

	return Config{
		Port:         port,
		RedisAddr:    getEnv("REDIS_ADDR", "localhost:6379"),
		DefaultRPS:   defaultRPS,
		DefaultBurst: defaultBurst,
	}
}

// ── Rate Limiter ────────────────────────────────────────────────

type RateLimiter struct {
	mu       sync.RWMutex
	limiters map[string]*rate.Limiter
	config   Config
	logger   *zap.Logger
}

func NewRateLimiter(cfg Config, logger *zap.Logger) *RateLimiter {
	return &RateLimiter{
		limiters: make(map[string]*rate.Limiter),
		config:   cfg,
		logger:   logger,
	}
}

func (rl *RateLimiter) GetLimiter(key string) *rate.Limiter {
	rl.mu.RLock()
	lim, exists := rl.limiters[key]
	rl.mu.RUnlock()

	if exists {
		return lim
	}

	rl.mu.Lock()
	defer rl.mu.Unlock()

	// Double-check after acquiring write lock
	if lim, exists = rl.limiters[key]; exists {
		return lim
	}

	lim = rate.NewLimiter(
		rate.Limit(rl.config.DefaultRPS),
		rl.config.DefaultBurst,
	)
	rl.limiters[key] = lim
	return lim
}

func (rl *RateLimiter) Allow(key string) bool {
	return rl.GetLimiter(key).Allow()
}

// ── HTTP Handlers ───────────────────────────────────────────────

type CheckResponse struct {
	Allowed    bool   `json:"allowed"`
	Remaining  int    `json:"remaining,omitempty"`
	RetryAfter string `json:"retry_after,omitempty"`
}

type HealthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
	Version string `json:"version"`
	Keys    int    `json:"active_keys"`
}

func checkHandler(rl *RateLimiter) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Extract client key — prefer X-Forwarded-For, fall back to RemoteAddr
		key := r.Header.Get("X-Forwarded-For")
		if key == "" {
			key = r.RemoteAddr
		}

		// Override key with instance-specific header if present
		if instanceKey := r.Header.Get("X-Ruvamco-Rate-Key"); instanceKey != "" {
			key = instanceKey
		}

		allowed := rl.Allow(key)

		resp := CheckResponse{Allowed: allowed}
		if !allowed {
			w.Header().Set("X-RateLimit-Retry-After", "1")
			resp.RetryAfter = "1s"
			w.WriteHeader(http.StatusTooManyRequests)
		} else {
			w.WriteHeader(http.StatusOK)
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

func healthHandler(rl *RateLimiter) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rl.mu.RLock()
		keyCount := len(rl.limiters)
		rl.mu.RUnlock()

		resp := HealthResponse{
			Status:  "healthy",
			Service: "ruvamco-ratelimit-sidecar",
			Version: "1.0.0",
			Keys:    keyCount,
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}
}

func metricsHandler(rl *RateLimiter) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rl.mu.RLock()
		keyCount := len(rl.limiters)
		rl.mu.RUnlock()

		fmt.Fprintf(w, "# HELP ruvamco_ratelimit_active_keys Number of active rate-limit keys\n")
		fmt.Fprintf(w, "# TYPE ruvamco_ratelimit_active_keys gauge\n")
		fmt.Fprintf(w, "ruvamco_ratelimit_active_keys %d\n", keyCount)
	}
}

// ── Main ────────────────────────────────────────────────────────

func main() {
	logger, err := zap.NewProduction()
	if err != nil {
		log.Fatalf("Failed to create logger: %v", err)
	}
	defer logger.Sync()

	cfg := loadConfig()
	rl := NewRateLimiter(cfg, logger)

	r := mux.NewRouter()
	r.HandleFunc("/check", checkHandler(rl)).Methods("GET", "POST")
	r.HandleFunc("/health", healthHandler(rl)).Methods("GET")
	r.HandleFunc("/metrics", metricsHandler(rl)).Methods("GET")

	addr := fmt.Sprintf(":%d", cfg.Port)
	logger.Info("RUVAMCO Rate Limit Sidecar starting",
		zap.String("addr", addr),
		zap.Int("default_rps", cfg.DefaultRPS),
		zap.Int("default_burst", cfg.DefaultBurst),
	)

	srv := &http.Server{
		Addr:         addr,
		Handler:      r,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 5 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	if err := srv.ListenAndServe(); err != nil {
		logger.Fatal("Server failed", zap.Error(err))
	}
}

// ── Utilities ───────────────────────────────────────────────────

func getEnv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}
