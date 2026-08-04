package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
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
	showVersion := flag.Bool("version", false, "print version and exit")
	flag.Parse()
	if *showVersion {
		if _, err := fmt.Fprintln(os.Stdout, version); err != nil {
			os.Exit(1)
		}
		return
	}

	logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))
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
