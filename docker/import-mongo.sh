#!/usr/bin/env bash
# docker/import-mongo.sh
# Imports a mongodump backup into the running MongoDB container.
#
# Expected backup layout (mongodump --db <DB> --out database/stem_kg_mongo):
#   database/stem_kg_mongo/Metadata-Edu/*.bson   ← standard --out layout
#   OR
#   database/stem_kg_mongo/*.bson                ← --db-specific layout

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_mongo"

# Load .env for variable overrides (safe even if .env is missing)
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

CONTAINER="${MONGODB_CONTAINER_NAME:-stem_kg_mongodb}"
DB_NAME="${MONGODB_DB:-Metadata-Edu}"

# ── Validate backup directory ─────────────────────────────────────────────────
if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
    echo "ERROR: No backup files found in: $BACKUP_DIR"
    echo ""
    echo "  To create a backup from a running MongoDB instance:"
    echo "    mongodump --uri \"mongodb://localhost:27017\" --db \"$DB_NAME\" --out database/stem_kg_mongo"
    echo ""
    echo "  Then re-run this script."
    exit 1
fi

# ── Validate container is running ─────────────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    echo "  Start services first: docker compose up -d mongodb"
    exit 1
fi

# ── Copy backup into container ────────────────────────────────────────────────
echo "[1/3] Copying backup to container '$CONTAINER'..."
docker exec "$CONTAINER" rm -rf /tmp/mongo_restore
docker cp "$BACKUP_DIR/." "$CONTAINER:/tmp/mongo_restore/"

# ── Detect layout and restore ─────────────────────────────────────────────────
echo "[2/3] Restoring database '$DB_NAME' (--drop existing collections)..."
if docker exec "$CONTAINER" test -d "/tmp/mongo_restore/$DB_NAME"; then
    # Standard mongodump --out layout: directory named after the database
    docker exec "$CONTAINER" mongorestore --drop --db "$DB_NAME" "/tmp/mongo_restore/$DB_NAME"
else
    # Flat layout: BSON files are directly in the backup directory
    docker exec "$CONTAINER" mongorestore --drop --db "$DB_NAME" /tmp/mongo_restore
fi

# ── Cleanup ───────────────────────────────────────────────────────────────────
echo "[3/3] Cleaning up temporary files..."
docker exec "$CONTAINER" rm -rf /tmp/mongo_restore

echo ""
echo "SUCCESS: MongoDB '$DB_NAME' imported into container '$CONTAINER'."
