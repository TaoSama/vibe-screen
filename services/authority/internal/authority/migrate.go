package authority

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

func ApplyMigration(ctx context.Context, databaseURL, source string) error {
	connection, err := pgx.Connect(ctx, databaseURL)
	if err != nil {
		return fmt.Errorf("connect for migration: %w", err)
	}
	defer func() { _ = connection.Close(ctx) }()
	if _, err := connection.Exec(ctx, `SELECT pg_advisory_lock(838433001)`); err != nil {
		return fmt.Errorf("lock authority migration: %w", err)
	}
	defer func() { _, _ = connection.Exec(context.Background(), `SELECT pg_advisory_unlock(838433001)`) }()
	if _, err := connection.Exec(ctx, `CREATE TABLE IF NOT EXISTS authority_schema_migrations(version bigint PRIMARY KEY,checksum_sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())`); err != nil {
		return fmt.Errorf("prepare migration ledger: %w", err)
	}
	digest := sha256.Sum256([]byte(source))
	checksum := hex.EncodeToString(digest[:])
	var existing string
	err = connection.QueryRow(ctx, `SELECT checksum_sha256 FROM authority_schema_migrations WHERE version=1`).Scan(&existing)
	if err == nil {
		if existing != checksum {
			return errors.New("authority migration 1 checksum mismatch")
		}
		return nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return fmt.Errorf("read migration ledger: %w", err)
	}
	tx, err := connection.Begin(ctx)
	if err != nil {
		return fmt.Errorf("begin authority migration: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, source); err != nil {
		return fmt.Errorf("apply authority migration: %w", err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO authority_schema_migrations(version,checksum_sha256) VALUES (1,$1)`, checksum); err != nil {
		return fmt.Errorf("record authority migration: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit authority migration: %w", err)
	}
	return nil
}
