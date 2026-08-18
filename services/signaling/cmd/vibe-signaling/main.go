package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vibe-screen/vibe-screen/services/signaling/internal/signaling"
)

var version = "0.1.0"

type redactedHTTPErrorWriter struct {
	logger *slog.Logger
}

func (w redactedHTTPErrorWriter) Write(message []byte) (int, error) {
	// net/http's default error text can include a raw peer address or request data.
	w.logger.Error("HTTP server internal error; details redacted")
	return len(message), nil
}

const (
	readHeaderTimeout = 5 * time.Second
	readTimeout       = 10 * time.Second
	idleTimeout       = 65 * time.Second
	writeGrace        = 10 * time.Second
	shutdownTimeout   = 10 * time.Second
)

func main() {
	configPath := flag.String("config", "config.json", "path to signaling JSON configuration")
	migrationPath := flag.String("migrate", "", "apply one SQL migration file and exit")
	healthcheckURL := flag.String("healthcheck", "", "probe one signaling health or readiness URL and exit")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	if *showVersion {
		if _, err := fmt.Fprintln(os.Stdout, version); err != nil {
			os.Exit(1)
		}
		return
	}
	if *healthcheckURL != "" {
		if err := probeHealth(*healthcheckURL); err != nil {
			logger.Error("healthcheck failed", "error", err)
			os.Exit(1)
		}
		return
	}
	if *migrationPath != "" {
		databaseURL, err := signaling.LoadDatabaseURL()
		if err != nil {
			logger.Error("migration configuration failed", "error", err)
			os.Exit(2)
		}
		contents, err := os.ReadFile(*migrationPath)
		if err != nil {
			logger.Error("read migration failed", "error", err)
			os.Exit(1)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := signaling.ApplyMigration(ctx, databaseURL, string(contents)); err != nil {
			logger.Error("migration failed", "error", err)
			os.Exit(1)
		}
		return
	}

	cfg, err := signaling.LoadConfig(*configPath)
	if err != nil {
		logger.Error("configuration failed", "error", err)
		os.Exit(2)
	}
	service, err := signaling.NewServer(cfg)
	if err != nil {
		logger.Error("server initialization failed", "error", err)
		os.Exit(2)
	}
	defer service.Close()
	listener, err := net.Listen("tcp", cfg.ListenAddress)
	if err != nil {
		logger.Error("listen failed", "error", err)
		os.Exit(1)
	}

	rootContext, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go service.RunCleanup(rootContext)
	httpServer := &http.Server{
		Handler: service.Handler(), ReadHeaderTimeout: readHeaderTimeout,
		ReadTimeout:  readTimeout,
		WriteTimeout: time.Duration(cfg.MaxWaitSeconds)*time.Second + writeGrace,
		IdleTimeout:  idleTimeout, MaxHeaderBytes: 16 * 1024,
		BaseContext: func(net.Listener) context.Context { return rootContext },
		ErrorLog:    log.New(redactedHTTPErrorWriter{logger: logger}, "", 0),
	}
	service.SetReady(true)
	logger.Info("signaling server listening", "address", listener.Addr().String())
	serveErrors := make(chan error, 1)
	go func() { serveErrors <- httpServer.Serve(listener) }()

	select {
	case <-rootContext.Done():
		service.SetReady(false)
		shutdownContext, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		if err := httpServer.Shutdown(shutdownContext); err != nil {
			logger.Error("graceful shutdown failed", "error", err)
			os.Exit(1)
		}
	case err := <-serveErrors:
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("HTTP server failed", "error", err)
			os.Exit(1)
		}
	}
	logger.Info("signaling server stopped")
}

func probeHealth(endpoint string) error {
	client := &http.Client{
		Timeout: 2 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return errors.New("healthcheck redirects are not permitted")
		},
	}
	response, err := client.Get(endpoint)
	if err != nil {
		return fmt.Errorf("healthcheck request: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("healthcheck status: %s", response.Status)
	}
	var status struct {
		Status string `json:"status"`
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, 1024))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&status); err != nil || status.Status != "ok" {
		return errors.New("healthcheck returned an invalid response")
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("healthcheck returned trailing data")
	}
	return nil
}
