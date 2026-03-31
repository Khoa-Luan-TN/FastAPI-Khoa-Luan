#!/usr/bin/env bash
# docker/import-mongo.sh
# Imports a MongoDB backup into the running MongoDB container.
#
# Supported backup layouts:
#   database/stem_kg_mongo/Metadata-Edu/*.bson   ← standard mongodump --out layout
#   database/stem_kg_mongo/*.bson                ← flat BSON layout
#   database/stem_kg_mongo/Metadata-Edu.*.json   ← one JSON file per collection

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_mongo"

read_env_value() {
    local key="$1"
    local env_file="$PROJECT_ROOT/.env"
    [ -f "$env_file" ] || return 1
    local line
    line=$(grep -m1 "^${key}=" "$env_file" || true)
    [ -n "$line" ] || return 1
    line="${line#*=}"
    line="${line%\"}"
    line="${line#\"}"
    printf '%s' "$line"
}

CONTAINER="${MONGODB_CONTAINER_NAME:-$(read_env_value MONGODB_CONTAINER_NAME || printf 'letuandat_mongodb')}"
DB_NAME="${MONGODB_DB:-$(read_env_value MONGODB_DB || printf 'Metadata-Edu')}"

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
if docker exec "$CONTAINER" sh -c "find /tmp/mongo_restore -maxdepth 2 -name '*.json' | grep -q ."; then
    echo "  Detected JSON export layout"
    docker exec "$CONTAINER" sh -c "
      set -eu
      found=0
      for file in /tmp/mongo_restore/*.json; do
        [ -f \"\$file\" ] || continue
        found=1
        name=\$(basename \"\$file\" .json)
        collection=\${name#${DB_NAME}.}
        if [ \"\$collection\" = \"\$name\" ]; then
          collection=\$name
        fi
        if grep -Eq '^[[:space:]]*\\[[[:space:]]*\\][[:space:]]*$' \"\$file\"; then
          echo \"  -> skipping empty array file \$(basename \"\$file\")\"
          mongo \"$DB_NAME\" --quiet --eval \"db.getCollection('\$collection').drop()\" >/dev/null 2>&1 || true
          continue
        fi
        echo \"  -> importing \$collection from \$(basename \"\$file\")\"
        mongo \"$DB_NAME\" --quiet --eval \"db.getCollection('\$collection').drop()\" >/dev/null 2>&1 || true
        mongoimport --db \"$DB_NAME\" --collection \"\$collection\" --file \"\$file\" --jsonArray || \
        mongoimport --db \"$DB_NAME\" --collection \"\$collection\" --file \"\$file\"
      done
      [ \"\$found\" -eq 1 ] || { echo 'ERROR: No JSON files found for import.'; exit 1; }
    "
elif docker exec "$CONTAINER" test -d "/tmp/mongo_restore/$DB_NAME"; then
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
