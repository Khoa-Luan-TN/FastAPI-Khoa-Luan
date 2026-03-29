#!/usr/bin/env bash
# docker/import-neo4j.sh
# Loads a Neo4j dump into the neo4j container's data volume.
#
# Expected backup file: database/stem_kg_neo4j/<database>.dump
# Default database name: neo4j  →  file: database/stem_kg_neo4j/neo4j.dump
#
# How to create the dump:
#   neo4j-admin database dump neo4j --to-path=database/stem_kg_neo4j/
#
# IMPORTANT: The neo4j container is stopped during this operation so Neo4j can
# load into an offline database.  It is restarted automatically at the end.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="$PROJECT_ROOT/database/stem_kg_neo4j"

# Load .env for variable overrides
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

CONTAINER="${NEO4J_CONTAINER_NAME:-stem_kg_neo4j}"
NEO4J_DB="${NEO4J_DATABASE:-neo4j}"
NEO4J_IMAGE="neo4j:5"
DUMP_FILE="$BACKUP_DIR/${NEO4J_DB}.dump"

# ── Validate dump file ────────────────────────────────────────────────────────
if [ ! -f "$DUMP_FILE" ]; then
    echo "ERROR: Neo4j dump not found: $DUMP_FILE"
    echo ""
    echo "  Expected filename : ${NEO4J_DB}.dump"
    echo "  Expected location : database/stem_kg_neo4j/${NEO4J_DB}.dump"
    echo ""
    echo "  To create the dump (run against a running Neo4j instance):"
    echo "    neo4j-admin database dump $NEO4J_DB --to-path=database/stem_kg_neo4j/"
    echo ""
    echo "  Then re-run this script."
    exit 1
fi

# ── Resolve the data volume from the running container ───────────────────────
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running."
    echo "  Start it first so we can find its data volume:"
    echo "    docker compose up -d neo4j"
    exit 1
fi

DATA_VOLUME=$(docker inspect "$CONTAINER" \
    --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Name }}{{ end }}{{ end }}')

if [ -z "$DATA_VOLUME" ]; then
    echo "ERROR: Could not find /data volume for container '$CONTAINER'."
    echo "  Ensure docker-compose.yml mounts a named volume at /data."
    exit 1
fi

echo "Neo4j data volume : $DATA_VOLUME"
echo "Dump file         : $DUMP_FILE"
echo "Target database   : $NEO4J_DB"
echo ""

# ── Stop the container so Neo4j is offline for the load ──────────────────────
echo "[1/3] Stopping container '$CONTAINER'..."
docker stop "$CONTAINER"

# ── Load dump via a temporary container sharing the same data volume ──────────
echo "[2/3] Loading dump into volume '$DATA_VOLUME'..."
docker run --rm \
    -v "${DATA_VOLUME}:/data" \
    -v "${BACKUP_DIR}:/backups:ro" \
    "$NEO4J_IMAGE" \
    neo4j-admin database load \
        --from-path=/backups \
        --overwrite-destination=true \
        "$NEO4J_DB"

# ── Restart the Neo4j container ───────────────────────────────────────────────
echo "[3/3] Restarting container '$CONTAINER'..."
docker start "$CONTAINER"

echo ""
echo "SUCCESS: Neo4j database '$NEO4J_DB' loaded."
echo "  Neo4j browser will be available at http://localhost:7474 once ready."
