package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/vibe-screen/vibe-screen/services/relay/internal/relay"
)

const shutdownTimeout = 10 * time.Second

var version = "development"

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "vibe-relay: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	configPath := flag.String("config", "config.json", "path to relay JSON configuration")
	migrationPath := flag.String("migrate", "", "apply one SQL migration file and exit")
	healthcheckURL := flag.String("healthcheck", "", "probe one relay health or readiness URL and exit")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		return nil
	}
	if *healthcheckURL != "" {
		return probeHealth(*healthcheckURL)
	}
	if *migrationPath != "" {
		databaseURL, err := relay.LoadDatabaseURL()
		if err != nil {
			return err
		}
		contents, err := os.ReadFile(*migrationPath)
		if err != nil {
			return fmt.Errorf("read migration: %w", err)
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return relay.ApplyMigration(ctx, databaseURL, string(contents))
	}
	cfg, err := relay.LoadConfig(*configPath)
	if err != nil {
		return err
	}
	service, err := relay.NewServer(cfg)
	if err != nil {
		return fmt.Errorf("initialize service: %w", err)
	}
	defer service.Close()
	listener, err := net.Listen("tcp", cfg.ListenAddress)
	if err != nil {
		return fmt.Errorf("listen relay control plane: %w", err)
	}
	defer listener.Close()
	server := &http.Server{Addr: cfg.ListenAddress, Handler: service.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			slog.Error("graceful shutdown failed", "error", err)
		}
	}()
	slog.Info("relay control plane listening", "address", listener.Addr().String())
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve HTTP: %w", err)
	}
	return nil
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
		Status string
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
