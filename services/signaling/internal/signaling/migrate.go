package signaling

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
)

const previousWaiterCountSchemaChecksum = "10d8417ba2f7ecba631db9e6c076befd5a8beb9e6e06af9cbe133e20a5278ee1"

func ApplyMigration(ctx context.Context, databaseURL, source string) error {
	connection, err := pgx.Connect(ctx, databaseURL)
	if err != nil {
		return fmt.Errorf("connect for signaling migration: %w", err)
	}
	defer func() { _ = connection.Close(ctx) }()
	if _, err := connection.Exec(ctx, "SELECT pg_advisory_lock(838433002)"); err != nil {
		return fmt.Errorf("lock signaling migration: %w", err)
	}
	defer func() { _, _ = connection.Exec(context.Background(), "SELECT pg_advisory_unlock(838433002)") }()
	if _, err := connection.Exec(ctx, "CREATE TABLE IF NOT EXISTS signaling_schema_migrations(version bigint PRIMARY KEY,checksum_sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())"); err != nil {
		return fmt.Errorf("prepare signaling migration ledger: %w", err)
	}
	digest := sha256.Sum256([]byte(source))
	checksum := hex.EncodeToString(digest[:])
	var existing string
	err = connection.QueryRow(ctx, "SELECT checksum_sha256 FROM signaling_schema_migrations WHERE version=1").Scan(&existing)
	if err == nil {
		if existing != checksum {
			if existing != previousWaiterCountSchemaChecksum || !strings.Contains(source, "signaling_waiter_leases") {
				return errors.New("signaling migration 1 checksum mismatch")
			}
			if _, err := connection.Exec(ctx, source); err != nil {
				return fmt.Errorf("upgrade signaling waiter leases: %w", err)
			}
			if _, err := connection.Exec(ctx, "UPDATE signaling_schema_migrations SET checksum_sha256=$1, applied_at=now() WHERE version=1", checksum); err != nil {
				return fmt.Errorf("record signaling waiter lease upgrade: %w", err)
			}
		}
		return nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("read signaling migration ledger: %w", err)
	}
	tx, err := connection.Begin(ctx)
	if err != nil {
		return fmt.Errorf("begin signaling migration: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, source); err != nil {
		return fmt.Errorf("apply signaling migration: %w", err)
	}
	if _, err := tx.Exec(ctx, "INSERT INTO signaling_schema_migrations(version,checksum_sha256) VALUES (1,$1)", checksum); err != nil {
		return fmt.Errorf("record signaling migration: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit signaling migration: %w", err)
	}
	return nil
}
