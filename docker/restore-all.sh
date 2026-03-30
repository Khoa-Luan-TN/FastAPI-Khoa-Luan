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
#   • Neo4j restore is always skipped when running inside Docker because
#     neo4j-admin database load requires an offline database, and stopping /
#     starting containers from within a compose service is unsafe.
#   • When called by the compose auto-restore service, Neo4j must be restored
#     manually — see DEPLOY_SERVER.md for the exact commands.
#   • All other failures are reported but do NOT abort the script, so the
#     summary always prints and the compose service always exits 0.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env (optional — variables already present in environment take precedence)
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

NEO4J_AUTO_RESTORE="${NEO4J_AUTO_RESTORE:-false}"
MINIO_BUCKET="${MINIO_BUCKET:-data-edu}"
NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"

# Detect whether we are running inside a Docker container
_IN_DOCKER=false
[ -f "/.dockerenv" ] && _IN_DOCKER=true

_STATUS_PG="skipped (no backup found)"
_STATUS_MONGO="skipped (no backup found)"
_STATUS_MINIO="skipped (no backup found)"
_STATUS_NEO4J="skipped (no backup found)"

echo "════════════════════════════════════════════════════════"
echo " restore-all — starting"
[ "$_IN_DOCKER" = "true" ] && echo " (running inside Docker: Neo4j auto-restore unavailable)"
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
    fi
    echo ""
fi

# ── MinIO ─────────────────────────────────────────────────────────────────────
_MINIO_BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_minio"
if [ -d "$_MINIO_BACKUP_DIR/$MINIO_BUCKET" ] || [ -f "$_MINIO_BACKUP_DIR/minio-data.tar.gz" ]; then
    echo "──── MinIO ─────────────────────────────────────────────"
    if bash "$SCRIPT_DIR/import-minio.sh"; then
        _STATUS_MINIO="restored"
    else
        _STATUS_MINIO="FAILED (see output above)"
    fi
    echo ""
fi

# ── Neo4j ─────────────────────────────────────────────────────────────────────
_NEO4J_DUMP="$PROJECT_ROOT/database/stem_kg_neo4j/${NEO4J_DATABASE}.dump"
if [ -f "$_NEO4J_DUMP" ]; then
    echo "──── Neo4j ─────────────────────────────────────────────"
    if [ "$_IN_DOCKER" = "true" ]; then
        _STATUS_NEO4J="skipped — requires host-side restore (see note below)"
        echo "  Backup found: $_NEO4J_DUMP"
        echo "  Neo4j is NOT restored automatically (offline load required)."
        echo ""
        echo "  Restore Neo4j manually after containers are running:"
        echo "    docker compose stop neo4j"
        echo "    bash docker/import-neo4j.sh"
        echo "    docker compose start neo4j"
    elif [ "$NEO4J_AUTO_RESTORE" = "true" ]; then
        echo "  NEO4J_AUTO_RESTORE=true — proceeding with offline load..."
        if bash "$SCRIPT_DIR/import-neo4j.sh"; then
            _STATUS_NEO4J="restored"
        else
            _STATUS_NEO4J="FAILED (see output above)"
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
