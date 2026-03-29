#!/usr/bin/env bash
# docker/import-postgre.sh
# Imports a PostgreSQL backup into the running postgres container.
#
# Supported backup formats (place in database/stem_kg_backup/):
#   backup.dump   ← pg_dump -Fc (custom format, preferred)
#   backup.sql    ← pg_dump plain SQL

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_backup"

# Load .env for variable overrides
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

CONTAINER="${PG_CONTAINER_NAME:-stem_kg_postgres}"
PG_USER="${PG_USER:-postgres}"
PG_NAME="${PG_NAME:-data-edu}"

# ── Detect backup file ────────────────────────────────────────────────────────
BACKUP_DUMP="$BACKUP_DIR/backup.dump"
BACKUP_SQL="$BACKUP_DIR/backup.sql"

if [ -f "$BACKUP_DUMP" ]; then
    BACKUP_FILE="$BACKUP_DUMP"
    FORMAT="custom"
elif [ -f "$BACKUP_SQL" ]; then
    BACKUP_FILE="$BACKUP_SQL"
    FORMAT="sql"
else
    echo "ERROR: No backup found in: $BACKUP_DIR"
    echo ""
    echo "  For custom format (recommended):"
    echo "    pg_dump -Fc -U $PG_USER $PG_NAME > database/stem_kg_backup/backup.dump"
    echo ""
    echo "  For plain SQL:"
    echo "    pg_dump -U $PG_USER $PG_NAME > database/stem_kg_backup/backup.sql"
    echo ""
    echo "  Then re-run this script."
    exit 1
fi

# ── Validate container is running ─────────────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    echo "  Start services first: docker compose up -d postgres"
    exit 1
fi

echo "Backup file: $BACKUP_FILE (format: $FORMAT)"

# ── Copy backup into container ────────────────────────────────────────────────
echo "[1/2] Copying backup to container '$CONTAINER'..."
docker cp "$BACKUP_FILE" "$CONTAINER:/tmp/pg_restore_file"

# ── Restore ───────────────────────────────────────────────────────────────────
echo "[2/2] Restoring database '$PG_NAME' as user '$PG_USER'..."
if [ "$FORMAT" = "custom" ]; then
    docker exec "$CONTAINER" pg_restore \
        -U "$PG_USER" \
        --clean --if-exists \
        -d "$PG_NAME" \
        /tmp/pg_restore_file
else
    docker exec "$CONTAINER" psql \
        -U "$PG_USER" \
        -d "$PG_NAME" \
        -f /tmp/pg_restore_file
fi

docker exec "$CONTAINER" rm -f /tmp/pg_restore_file

echo ""
echo "SUCCESS: PostgreSQL '$PG_NAME' imported into container '$CONTAINER'."
