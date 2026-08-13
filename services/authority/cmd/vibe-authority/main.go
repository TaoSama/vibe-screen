package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
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
	migrationPath := flag.String("migrate", "", "apply one SQL migration file and exit")
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *showVersion {
		_, err := fmt.Fprintln(os.Stdout, version)
		return err
	}
	cfg, err := authority.LoadConfig(*configPath)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if *migrationPath != "" {
		contents, err := os.ReadFile(*migrationPath)
		if err != nil {
			return fmt.Errorf("read migration: %w", err)
		}
		return authority.ApplyMigration(ctx, cfg.DatabaseURL, string(contents))
	}
	store, err := authority.OpenPostgres(ctx, cfg)
	if err != nil {
		return err
	}
	defer store.Close()
	service, err := authority.NewServer(cfg, store)
	if err != nil {
		return err
	}
	server := &http.Server{Addr: cfg.ListenAddress, Handler: service.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 * 1024}
	root, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-root.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	slog.Info("authority listening", "address", cfg.ListenAddress)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("serve authority: %w", err)
	}
	return nil
}
