package authority

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"

	"github.com/jackc/pgx/v5"
)

type Migration struct {
	Version int64
	Source  string
}

func ApplyMigration(ctx context.Context, databaseURL, source string) error {
	return ApplyMigrations(ctx, databaseURL, []Migration{{Version: 1, Source: source}})
}

func ApplyMigrationPath(ctx context.Context, databaseURL, path string) error {
	migrations, err := LoadMigrations(path)
	if err != nil {
		return err
	}
	return ApplyMigrations(ctx, databaseURL, migrations)
}

func LoadMigrations(path string) ([]Migration, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("stat authority migration path: %w", err)
	}
	if !info.IsDir() {
		contents, err := os.ReadFile(path)
		if err != nil {
			return nil, fmt.Errorf("read authority migration: %w", err)
		}
		version, err := migrationVersion(filepath.Base(path))
		if err != nil {
			return nil, err
		}
		return []Migration{{Version: version, Source: string(contents)}}, nil
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return nil, fmt.Errorf("read authority migration directory: %w", err)
	}
	migrations := make([]Migration, 0, len(entries))
	seen := make(map[int64]string)
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".sql" {
			continue
		}
		version, err := migrationVersion(entry.Name())
		if err != nil {
			return nil, err
		}
		if previous := seen[version]; previous != "" {
			return nil, fmt.Errorf("duplicate authority migration version %d: %s and %s", version, previous, entry.Name())
		}
		contents, err := os.ReadFile(filepath.Join(path, entry.Name()))
		if err != nil {
			return nil, fmt.Errorf("read authority migration %s: %w", entry.Name(), err)
		}
		seen[version] = entry.Name()
		migrations = append(migrations, Migration{Version: version, Source: string(contents)})
	}
	sort.Slice(migrations, func(i, j int) bool { return migrations[i].Version < migrations[j].Version })
	if len(migrations) == 0 {
		return nil, fmt.Errorf("no authority SQL migrations found in %s", path)
	}
	return migrations, nil
}

var migrationFilePattern = regexp.MustCompile(`^(\d+)_.*\.sql$`)

func migrationVersion(name string) (int64, error) {
	matches := migrationFilePattern.FindStringSubmatch(name)
	if matches == nil {
		return 0, fmt.Errorf("authority migration %s does not start with a numeric version", name)
	}
	version, err := strconv.ParseInt(matches[1], 10, 64)
	if err != nil || version <= 0 {
		return 0, fmt.Errorf("authority migration %s has invalid version", name)
	}
	return version, nil
}

func ApplyMigrations(ctx context.Context, databaseURL string, migrations []Migration) error {
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
	for _, migration := range migrations {
		if migration.Version <= 0 {
			return fmt.Errorf("authority migration version must be positive: %d", migration.Version)
		}
		digest := sha256.Sum256([]byte(migration.Source))
		checksum := hex.EncodeToString(digest[:])
		var existing string
		err = connection.QueryRow(ctx, `SELECT checksum_sha256 FROM authority_schema_migrations WHERE version=$1`, migration.Version).Scan(&existing)
		if err == nil {
			if existing != checksum {
				return fmt.Errorf("authority migration %d checksum mismatch", migration.Version)
			}
			continue
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("read migration ledger: %w", err)
		}
		tx, err := connection.Begin(ctx)
		if err != nil {
			return fmt.Errorf("begin authority migration %d: %w", migration.Version, err)
		}
		if _, err := tx.Exec(ctx, migration.Source); err != nil {
			_ = tx.Rollback(ctx)
			return fmt.Errorf("apply authority migration %d: %w", migration.Version, err)
		}
		if _, err := tx.Exec(ctx, `INSERT INTO authority_schema_migrations(version,checksum_sha256) VALUES ($1,$2)`, migration.Version, checksum); err != nil {
			_ = tx.Rollback(ctx)
			return fmt.Errorf("record authority migration %d: %w", migration.Version, err)
		}
		if err := tx.Commit(ctx); err != nil {
			return fmt.Errorf("commit authority migration %d: %w", migration.Version, err)
		}
	}
	return nil
}
