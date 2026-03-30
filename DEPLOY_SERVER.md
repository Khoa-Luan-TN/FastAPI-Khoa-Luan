# Server Deployment Guide

## Service overview

| Service            | Container              | Port(s)    | Description                                  |
|--------------------|------------------------|------------|----------------------------------------------|
| Backend            | `stem_kg_backend`      | 8000       | FastAPI REST API                             |
| Frontend           | `stem_kg_frontend`     | 3000       | React SPA served by nginx                   |
| PostgreSQL         | `stem_kg_postgres`     | 5432       | Structural metadata store                   |
| MongoDB            | `stem_kg_mongodb`      | 27017      | Document/content store                      |
| Neo4j              | `stem_kg_neo4j`        | 7474, 7687 | Graph for topic/keyword search              |
| MinIO              | `stem_kg_minio`        | 9000, 9001 | Object storage (PDFs/assets)                |
| MinIO init         | `stem_kg_minio_init`   | —          | One-shot bucket creator                     |
| auto-restore       | `stem_kg_auto_restore` | —          | One-shot restore (only when AUTO_RESTORE=true) |
| restore-postgres   | *(profile: restore)*   | —          | Manual one-shot PostgreSQL restore          |
| restore-mongo      | *(profile: restore)*   | —          | Manual one-shot MongoDB restore             |
| restore-neo4j      | *(profile: restore)*   | —          | Manual one-shot Neo4j restore               |
| restore-minio      | *(profile: restore)*   | —          | Manual one-shot MinIO restore               |

## Folder structure

```
FastAPI-Khoa-Luan/
├── app/                    ← FastAPI backend source
├── frontend/               ← React/Vite frontend source
├── gemini_pipeline/        ← Offline ML extraction pipeline (not in Docker)
├── database/
│   ├── stem_kg_mongo/      ← Place mongodump output here
│   ├── stem_kg_neo4j/      ← Place neo4j.dump here
│   ├── stem_kg_backup/     ← Place backup.dump / backup.sql here (PostgreSQL)
│   └── stem_kg_minio/      ← Place <bucket>/ tree or minio-data.tar.gz here
├── docker/
│   ├── import-mongo.sh     ← MongoDB restore script (manual)
│   ├── import-postgre.sh   ← PostgreSQL restore script (manual)
│   ├── import-neo4j.sh     ← Neo4j restore script (manual)
│   └── import-minio.sh     ← MinIO restore script (manual)
├── Dockerfile              ← Backend image
├── frontend/Dockerfile     ← Frontend image (multi-stage nginx)
├── docker-compose.yml      ← Orchestration
├── .env.example            ← Environment variable template
└── .env                    ← Your local config (not in git — create from example)
```

---

## First-time setup

### 1. Prerequisites

- Docker Engine ≥ 24
- Docker Compose ≥ 2.20
- At least 8 GB free disk (torch CPU wheel is ~800 MB)

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- Strong passwords for `PG_PASSWORD`, `NEO4J_PASSWORD`, `MINIO_SECRET_KEY`
- `VITE_API_BASE` — the URL where the **browser** reaches the backend:
  - Local machine: `http://localhost:8000`
  - Remote server: `http://<server-ip>:8000` or `https://api.your-domain.com`
- `CORS_ORIGINS` — add your server IP/domain to allow browser requests:
  - Example: `CORS_ORIGINS=http://<server-ip>:3000`
- `GEMINI_API_KEYS` — comma-separated Gemini API keys for AI features
- `AUTO_RESTORE=false` *(optional)* — set to `true` to automatically restore databases on startup

> **Note:** `VITE_API_BASE` is a build-time variable. After changing it you must
> rebuild the frontend image: `docker compose build frontend`

### 3. Build and start all services

```bash
docker compose up -d --build
```

First build takes several minutes (downloads torch + sentence-transformers).
Watch startup with: `docker compose logs -f backend`

---

## Access points

| Service        | URL                          |
|----------------|------------------------------|
| Frontend       | http://localhost:3000        |
| Backend API    | http://localhost:8000        |
| API docs       | http://localhost:8000/docs   |
| MinIO console  | http://localhost:9001        |
| Neo4j browser  | http://localhost:7474        |

Replace `localhost` with your server IP when deploying remotely.

---

## Database restore — backup file locations

| Database   | Backup location                              | Expected file(s)                     |
|------------|----------------------------------------------|--------------------------------------|
| PostgreSQL | `database/stem_kg_backup/`                   | `backup.dump` or `backup.sql`        |
| MongoDB    | `database/stem_kg_mongo/`                    | BSON files (mongodump output)        |
| Neo4j      | `database/stem_kg_neo4j/`                    | `neo4j.dump` (neo4j-admin dump)      |
| MinIO      | `database/stem_kg_minio/`                    | `<bucket>/` tree or `minio-data.tar.gz` |

See the `README.md` inside each subfolder for exact format and how to create backups.

---

## Auto-restore (recommended for first-time server setup)

By default, restore does **not** run automatically. To enable automatic restore on
`docker compose up`, set `AUTO_RESTORE=true` in `.env`:

```bash
# In .env
AUTO_RESTORE=true
```

Then run a normal startup:

```bash
docker compose up -d --build
```

The `auto-restore` service will run after PostgreSQL, MongoDB, and MinIO are healthy.
It calls `docker/restore-all.sh` which skips any database whose backup directory is empty.

**What gets restored automatically:**

| Database   | Condition                                             |
|------------|-------------------------------------------------------|
| PostgreSQL | `database/stem_kg_backup/backup.dump` or `.sql` found |
| MongoDB    | `database/stem_kg_mongo/` is non-empty                |
| MinIO      | `database/stem_kg_minio/<bucket>/` or `.tar.gz` found |
| Neo4j      | **Never** — must be restored manually (see below)     |

> **Auto-restore requires Docker socket access.**
> The `auto-restore` service mounts `/var/run/docker.sock` to call `docker exec`/`docker cp`
> on the running database containers.

> **Idempotent but destructive:** restores drop existing data in the target databases.
> Do not run with `AUTO_RESTORE=true` after you have real production data in the volumes.
> Set `AUTO_RESTORE=false` (or remove it) once the initial restore is done.

### Neo4j — manual restore required

Neo4j's `database load` command requires the database to be **offline**.
It cannot safely stop and restart the `neo4j` container from within a compose service.

After the rest of the stack is running, restore Neo4j manually:

```bash
docker compose stop neo4j
bash docker/import-neo4j.sh
docker compose start neo4j
```

Or use `docker/restore-all.sh` with `NEO4J_AUTO_RESTORE=true` (host-only):

```bash
# In .env
NEO4J_AUTO_RESTORE=true
# neo4j container must be stopped first
docker compose stop neo4j
bash docker/restore-all.sh
docker compose start neo4j
```

---

## Manual restore (individual databases)

### Option A — restore via Docker Compose profile

Services start with correct dependencies and run inside Docker (no host tools needed).

```bash
# PostgreSQL — requires: database/stem_kg_backup/backup.dump or backup.sql
docker compose --profile restore run --rm restore-postgres

# MongoDB — requires: database/stem_kg_mongo/ with BSON files
docker compose --profile restore run --rm restore-mongo

# MinIO — requires: database/stem_kg_minio/<bucket>/ tree or minio-data.tar.gz
docker compose --profile restore run --rm restore-minio

# Neo4j — requires: database/stem_kg_neo4j/neo4j.dump
# IMPORTANT: neo4j must be stopped first (load requires offline database)
docker compose stop neo4j
docker compose --profile restore run --rm restore-neo4j
docker compose start neo4j
```

### Option B — restore via manual scripts

```bash
# Make scripts executable (first time only)
chmod +x docker/import-mongo.sh docker/import-postgre.sh \
         docker/import-neo4j.sh docker/import-minio.sh docker/restore-all.sh

# All-in-one (skips any database with no backup; Neo4j skipped unless NEO4J_AUTO_RESTORE=true)
bash docker/restore-all.sh

# Individual databases
bash docker/import-postgre.sh
bash docker/import-mongo.sh
bash docker/import-minio.sh

# Neo4j (stops container, restores, restarts)
bash docker/import-neo4j.sh
```

---

## MinIO bucket

The `minio-init` service creates the `data-edu` bucket automatically on
`docker compose up`. No manual action needed for a fresh deployment.

To verify or manage buckets: open the MinIO console at http://localhost:9001
and log in with `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`.

---

## Rebuild individual services

```bash
# After changing backend code or requirements.txt
docker compose build backend && docker compose up -d backend

# After changing frontend code or VITE_API_BASE
docker compose build frontend && docker compose up -d frontend
```

---

## Stop / teardown

```bash
# Stop all containers (data volumes preserved)
docker compose down

# Stop and delete all data volumes (full reset)
docker compose down -v
```

---

## Known first-start notes

- **ML model download**: `sentence-transformers` downloads `intfloat/multilingual-e5-base`
  from Hugging Face on first backend startup. Ensure internet access during the first boot.
  Set `EMBEDDING_MODEL_NAME` in `.env` to use a different model.

- **Neo4j search**: The graph is empty after a fresh deployment. Search endpoints start
  working after restoring a Neo4j dump.

- **gemini_pipeline**: The extraction pipeline is independent and is not part of Docker
  Compose. It runs locally via its own Python venv. See `gemini_pipeline/readme.md`.
