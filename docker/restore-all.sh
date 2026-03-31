#!/usr/bin/env bash
# docker/restore-all.sh
# Orchestrates all database / storage restores in dependency order.
# Skips any service where no backup file or directory is found (non-destructive).
#
# Usage (from project root):
#   bash docker/restore-all.sh
#
# Environment variables (auto-loaded from .env):
#   NEO4J_AUTO_RESTORE=true   — opt-in to Neo4j offline restore (host only)
#
# Notes:
#   • MinIO restore is always skipped when running inside Docker because the
#     full-data-dir backup is handled by the minio-bootstrap compose service
#     (which runs before MinIO starts and copies data directly into the volume).
#   • Neo4j restore is always skipped when running inside Docker because
#     neo4j-admin database load requires an offline database, and stopping /
#     starting containers from within a compose service is unsafe.
#   • When called by the compose auto-restore service, only PostgreSQL and
#     MongoDB are restored; MinIO and Neo4j must be bootstrapped via their
#     dedicated init services.
#   • Exit code: 0 = all required restores succeeded (or were skipped because
#     no backup was found).  Non-zero = at least one restore with a present
#     backup FAILED — the caller should treat this as a hard failure.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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

NEO4J_AUTO_RESTORE="${NEO4J_AUTO_RESTORE:-$(read_env_value NEO4J_AUTO_RESTORE || printf 'false')}"
MINIO_BUCKET="${MINIO_BUCKET:-$(read_env_value MINIO_BUCKET || printf 'data-edu')}"
NEO4J_DATABASE="${NEO4J_DATABASE:-$(read_env_value NEO4J_DATABASE || printf 'neo4j')}"

# Detect whether we are running inside a Docker container
_IN_DOCKER=false
[ -f "/.dockerenv" ] && _IN_DOCKER=true

_STATUS_PG="skipped (no backup found)"
_STATUS_MONGO="skipped (no backup found)"
_STATUS_MINIO="skipped (no backup found)"
_STATUS_NEO4J="skipped (no backup found)"

# Track whether any restore with a present backup has failed.
# Exit code mirrors this at the end.
_FAILED=0

echo "════════════════════════════════════════════════════════"
echo " restore-all — starting"
[ "$_IN_DOCKER" = "true" ] && echo " (running inside Docker: MinIO + Neo4j handled by bootstrap services)"
echo "════════════════════════════════════════════════════════"
echo ""

# ── PostgreSQL ────────────────────────────────────────────────────────────────
_PG_BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_backup"
if [ -f "$_PG_BACKUP_DIR/backup.dump" ] || [ -f "$_PG_BACKUP_DIR/backup.sql" ]; then
    echo "──── PostgreSQL ────────────────────────────────────────"
    if bash "$SCRIPT_DIR/import-postgre.sh"; then
        _STATUS_PG="restored"
    else
        _STATUS_PG="FAILED (see output above)"
        _FAILED=1
    fi
    echo ""
fi

# ── MongoDB ───────────────────────────────────────────────────────────────────
_MONGO_BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_mongo"
if [ -d "$_MONGO_BACKUP_DIR" ] && [ -n "$(ls -A "$_MONGO_BACKUP_DIR" 2>/dev/null)" ]; then
    echo "──── MongoDB ───────────────────────────────────────────"
    if bash "$SCRIPT_DIR/import-mongo.sh"; then
        _STATUS_MONGO="restored"
    else
        _STATUS_MONGO="FAILED (see output above)"
        _FAILED=1
    fi
    echo ""
fi

# ── MinIO ─────────────────────────────────────────────────────────────────────
_MINIO_BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_minio"
_MINIO_HAS_BACKUP=false
if [ -d "$_MINIO_BACKUP_DIR/$MINIO_BUCKET" ] || \
   [ -d "$_MINIO_BACKUP_DIR/minio-data" ] || \
   [ -f "$_MINIO_BACKUP_DIR/minio-data.tar.gz" ]; then
    _MINIO_HAS_BACKUP=true
fi

if [ "$_MINIO_HAS_BACKUP" = "true" ]; then
    echo "──── MinIO ─────────────────────────────────────────────"
    if [ "$_IN_DOCKER" = "true" ]; then
        # Full-data-dir MinIO restore cannot work from inside Docker because the
        # backup path inside this container is not a host path and cannot be
        # bind-mounted by docker run.  The minio-bootstrap compose service handles
        # this before MinIO starts — no action needed here.
        _STATUS_MINIO="skipped (inside Docker — handled by minio-bootstrap service)"
        echo "  MinIO backup found but skipped: handled by minio-bootstrap service."
    else
        if bash "$SCRIPT_DIR/import-minio.sh"; then
            _STATUS_MINIO="restored"
        else
            _STATUS_MINIO="FAILED (see output above)"
            _FAILED=1
        fi
    fi
    echo ""
fi

# ── Neo4j ─────────────────────────────────────────────────────────────────────
_NEO4J_DUMP="$PROJECT_ROOT/database/stem_kg_neo4j/${NEO4J_DATABASE}.dump"
if [ ! -f "$_NEO4J_DUMP" ]; then
    _MATCHING_NEO4J_DUMPS=("$PROJECT_ROOT"/database/stem_kg_neo4j/*.dump)
    if [ "${#_MATCHING_NEO4J_DUMPS[@]}" -eq 1 ] && [ -f "${_MATCHING_NEO4J_DUMPS[0]}" ]; then
        _NEO4J_DUMP="${_MATCHING_NEO4J_DUMPS[0]}"
    fi
fi
if [ -f "$_NEO4J_DUMP" ]; then
    echo "──── Neo4j ─────────────────────────────────────────────"
    if [ "$_IN_DOCKER" = "true" ]; then
        _STATUS_NEO4J="skipped (inside Docker — handled by neo4j-bootstrap service)"
        echo "  Neo4j backup found but skipped: handled by neo4j-bootstrap service."
    elif [ "$NEO4J_AUTO_RESTORE" = "true" ]; then
        echo "  NEO4J_AUTO_RESTORE=true — proceeding with offline load..."
        if bash "$SCRIPT_DIR/import-neo4j.sh"; then
            _STATUS_NEO4J="restored"
        else
            _STATUS_NEO4J="FAILED (see output above)"
            _FAILED=1
        fi
    else
        _STATUS_NEO4J="skipped — set NEO4J_AUTO_RESTORE=true to restore"
        echo "  Backup found: $_NEO4J_DUMP"
        echo "  Set NEO4J_AUTO_RESTORE=true to include Neo4j restore."
        echo "  Or restore manually:"
        echo "    docker compose stop neo4j"
        echo "    bash docker/import-neo4j.sh"
        echo "    docker compose start neo4j"
    fi
    echo ""
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════"
echo " Restore summary"
echo "════════════════════════════════════════════════════════"
echo "  PostgreSQL : $_STATUS_PG"
echo "  MongoDB    : $_STATUS_MONGO"
echo "  MinIO      : $_STATUS_MINIO"
echo "  Neo4j      : $_STATUS_NEO4J"
echo "════════════════════════════════════════════════════════"

if [ "$_FAILED" -ne 0 ]; then
    echo ""
    echo "  ERROR: One or more restores FAILED. See output above."
    echo "  The backend will not start until restores succeed."
    echo "════════════════════════════════════════════════════════"
fi

exit "$_FAILED"
