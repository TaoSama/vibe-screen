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

	"github.com/vibe-screen/vibe-screen/services/authority/internal/authority"
)

var version = "development"

func main() {
	if err := run(); err != nil {
		slog.Error("authority stopped", "error", err)
		os.Exit(1)
	}
}
func run() error {
	configPath := flag.String("config", "config.json", "path to authority JSON configuration")
	migrationPath := flag.String("migrate", "", "apply a SQL migration file or directory and exit")
	healthcheckURL := flag.String("healthcheck", "", "probe one authority health or readiness URL and exit")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *showVersion {
		_, err := fmt.Fprintln(os.Stdout, version)
		return err
	}
	if *healthcheckURL != "" {
		return probeHealth(*healthcheckURL)
	}
	if *migrationPath != "" {
		databaseURL, err := authority.LoadDatabaseURL()
		if err != nil {
			return err
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return authority.ApplyMigrationPath(ctx, databaseURL, *migrationPath)
	}
	cfg, err := authority.LoadConfig(*configPath)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	store, err := authority.OpenPostgres(ctx, cfg)
	if err != nil {
		return err
	}
	defer store.Close()
	service, err := authority.NewServer(cfg, store)
	if err != nil {
		return err
	}
	listener, err := net.Listen("tcp", cfg.ListenAddress)
	if err != nil {
		return fmt.Errorf("listen authority: %w", err)
	}
	defer listener.Close()
	server := &http.Server{Addr: cfg.ListenAddress, Handler: service.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	root, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-root.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	slog.Info("authority listening", "address", listener.Addr().String())
	if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve authority: %w", err)
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
