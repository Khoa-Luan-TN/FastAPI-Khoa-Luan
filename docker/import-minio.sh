#!/usr/bin/env bash
# docker/import-minio.sh
# Restores MinIO object backup into the running MinIO container.
#
# Supported backup layouts (place in database/stem_kg_minio/):
#   database/stem_kg_minio/<bucket-name>/...   ← extracted object tree (preferred)
#   database/stem_kg_minio/minio-data.tar.gz   ← compressed archive

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_minio"

# Load .env for variable overrides
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

CONTAINER="${MINIO_CONTAINER_NAME:-stem_kg_minio}"
MINIO_ACCESS="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET="${MINIO_SECRET_KEY:-changeme}"
BUCKET="${MINIO_BUCKET:-data-edu}"
TARBALL="$BACKUP_DIR/minio-data.tar.gz"
BUCKET_DIR="$BACKUP_DIR/$BUCKET"

# ── Validate backup exists ────────────────────────────────────────────────────
if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
    echo "ERROR: No backup found in: $BACKUP_DIR"
    echo ""
    echo "  Supported layouts:"
    echo "    database/stem_kg_minio/$BUCKET/...       (extracted object tree)"
    echo "    database/stem_kg_minio/minio-data.tar.gz (compressed archive)"
    exit 1
fi

# ── Validate MinIO container is running ──────────────────────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    echo "  Start services first: docker compose up -d minio"
    exit 1
fi

# ── Wait for MinIO to be healthy ──────────────────────────────────────────────
echo "[1/3] Waiting for MinIO to be ready..."
_RETRIES=20
for _i in $(seq 1 "$_RETRIES"); do
    if docker exec "$CONTAINER" curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; then
        echo "  MinIO is ready."
        break
    fi
    if [ "$_i" -eq "$_RETRIES" ]; then
        echo "ERROR: MinIO did not become healthy after ${_RETRIES} attempts."
        exit 1
    fi
    echo "  Waiting... (attempt $_i/$_RETRIES)"
    sleep 3
done

# ── Detect backup layout and resolve host-side source directory ───────────────
TEMP_DIR=""
HOST_SRC=""

if [ -d "$BUCKET_DIR" ]; then
    echo "Backup layout  : object tree"
    echo "Source         : $BUCKET_DIR"
    HOST_SRC="$BACKUP_DIR"
elif [ -f "$TARBALL" ]; then
    echo "Backup layout  : compressed archive"
    echo "Archive        : $TARBALL"
    TEMP_DIR="$(mktemp -d)"
    echo "Extracting to  : $TEMP_DIR"
    tar -xzf "$TARBALL" -C "$TEMP_DIR"
    if [ ! -d "$TEMP_DIR/$BUCKET" ]; then
        echo "ERROR: Bucket directory '$BUCKET' not found inside archive."
        echo "  Archive top-level: $(ls "$TEMP_DIR" 2>/dev/null | head -10 | tr '\n' ' ')"
        rm -rf "$TEMP_DIR"
        exit 1
    fi
    HOST_SRC="$TEMP_DIR"
else
    echo "ERROR: Could not find restore source."
    echo "  Expected:"
    echo "    $BUCKET_DIR   (object tree)"
    echo "    $TARBALL   (compressed archive)"
    exit 1
fi

# ── Detect MinIO container network ───────────────────────────────────────────
MINIO_NETWORK=$(docker inspect "$CONTAINER" \
    --format '{{range $k,$_ := .NetworkSettings.Networks}}{{$k}} {{end}}' \
    | awk '{print $1}')

if [ -z "$MINIO_NETWORK" ]; then
    echo "ERROR: Could not detect Docker network for container '$CONTAINER'."
    exit 1
fi

echo "Target bucket  : $BUCKET"
echo "MinIO network  : $MINIO_NETWORK"
echo ""

# ── Run restore via temporary mc container on the same network ────────────────
echo "[2/3] Restoring objects into MinIO bucket '$BUCKET'..."
docker run --rm \
    --network "$MINIO_NETWORK" \
    -v "${HOST_SRC}:/restore:ro" \
    minio/mc \
    /bin/sh -c "
    mc alias set local http://${CONTAINER}:9000 ${MINIO_ACCESS} ${MINIO_SECRET} &&
    mc mb --ignore-existing local/${BUCKET} &&
    mc mirror --overwrite /restore/${BUCKET} local/${BUCKET} &&
    echo '[mc] Mirror complete.'
    "

# ── Cleanup temp dir if used ──────────────────────────────────────────────────
echo "[3/3] Cleaning up..."
if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
fi

echo ""
echo "SUCCESS: MinIO bucket '$BUCKET' restored into container '$CONTAINER'."
