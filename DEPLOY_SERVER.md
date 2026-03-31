# Server Deployment Guide

## Service overview

| Service            | Container                      | Port(s)         | Description                                  |
|--------------------|--------------------------------|-----------------|----------------------------------------------|
| Backend            | `letuandat_backend`            | 8100 → 8000     | FastAPI REST API                             |
| Frontend           | `letuandat_frontend`           | 3040 → 80       | React SPA served by nginx                   |
| PostgreSQL         | `letuandat_postgres`           | 5434 → 5432     | Structural metadata store                   |
| MongoDB            | `letuandat_mongodb`            | 27019 → 27017   | Document/content store                      |
| Neo4j              | `letuandat_neo4j`              | 18474, 18687    | Graph for topic/keyword search              |
| MinIO              | `letuandat_minio`              | 9100, 9101      | Object storage (PDFs/assets)                |
| neo4j-bootstrap    | `letuandat_neo4j_bootstrap`    | —               | One-shot: loads Neo4j dump before neo4j starts (fresh volume only) |
| minio-init         | `letuandat_minio_init`         | —               | One-shot: creates MinIO bucket              |
| auto-restore       | `letuandat_auto_restore`       | —               | One-shot: restores PG/Mongo/MinIO when `AUTO_RESTORE=true` |
| restore-postgres   | *(profile: restore)*           | —               | Manual one-shot PostgreSQL restore          |
| restore-mongo      | *(profile: restore)*           | —               | Manual one-shot MongoDB restore             |
| restore-neo4j      | *(profile: restore)*           | —               | Manual one-shot Neo4j restore               |
| restore-minio      | *(profile: restore)*           | —               | Manual one-shot MinIO restore               |

## Folder structure

```
FastAPI-Khoa-Luan/
├── app/                    ← FastAPI backend source
├── frontend/               ← React/Vite frontend source
├── gemini_pipeline/        ← Offline ML extraction pipeline (not in Docker)
├── database/
│   ├── stem_kg_mongo/      ← MongoDB backup (JSON exports or mongodump output)
│   ├── stem_kg_neo4j/      ← Neo4j dump (*.dump — loaded automatically on fresh start)
│   ├── stem_kg_backup/     ← PostgreSQL backup (backup.dump or backup.sql)
│   └── stem_kg_minio/      ← MinIO backup (<bucket>/ tree or minio-data.tar.gz)
├── docker/
│   ├── import-mongo.sh     ← MongoDB restore script (manual)
│   ├── import-postgre.sh   ← PostgreSQL restore script (manual)
│   ├── import-neo4j.sh     ← Neo4j restore script (manual re-restore)
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
- `CORS_ORIGINS` — add your server IP/domain to allow browser requests:
  - Example: `CORS_ORIGINS=http://<server-ip>:3040,https://your-domain.com`
- `GEMINI_API_KEYS` — comma-separated Gemini API keys for AI features
- Keep `VITE_API_BASE`, `VITE_API_URL`, `VITE_API_BASE_URL` as `/api` — the nginx
  container proxies `/api/*` to the backend internally; no change needed.

> **Note:** `VITE_API_BASE` is a build-time variable. After changing it you must
> rebuild the frontend image: `docker compose build frontend`

### 3. Build and start all services

```bash
docker compose up -d --build
```

First build takes several minutes (downloads torch + sentence-transformers).
Watch startup with: `docker compose logs -f backend`

**What happens automatically on first startup:**

| Step                  | Handled by          | Condition                                    |
|-----------------------|---------------------|----------------------------------------------|
| MinIO data restored   | `minio-bootstrap`   | `database/stem_kg_minio/minio-data/` exists AND volume is fresh |
| MinIO bucket ensured  | `minio-init`        | Always (idempotent)                          |
| Neo4j dump loaded     | `neo4j-bootstrap`   | Dump exists in `database/stem_kg_neo4j/` AND volume is fresh |
| PG + MongoDB restore  | `auto-restore`      | `AUTO_RESTORE=true` (default) AND backup files present       |

No manual restore commands are required after `docker compose up -d --build`.

**Failure behavior:** If `AUTO_RESTORE=true` and a PostgreSQL or MongoDB restore fails,
`auto-restore` exits non-zero and the backend will not start. This surfaces the failure
clearly rather than starting the app with missing data. MinIO and Neo4j failures surface
by their respective services not becoming healthy (blocking the backend).

---

## Access points

| Service        | URL                           |
|----------------|-------------------------------|
| Frontend       | http://localhost:3040         |
| Backend API    | http://localhost:8100         |
| API docs       | http://localhost:8100/docs    |
| MinIO console  | http://localhost:9101         |
| Neo4j browser  | http://localhost:18474        |

Replace `localhost` with your server IP when deploying remotely.

---

## Database restore — backup file locations

| Database   | Backup location                              | Expected file(s)                     |
|------------|----------------------------------------------|--------------------------------------|
| PostgreSQL | `database/stem_kg_backup/`                   | `backup.dump` or `backup.sql`        |
| MongoDB    | `database/stem_kg_mongo/`                    | BSON files (mongodump output)        |
| Neo4j      | `database/stem_kg_neo4j/`                    | `*.dump` (neo4j-admin dump)          |
| MinIO      | `database/stem_kg_minio/`                    | `<bucket>/` tree or `minio-data.tar.gz` |

---

## Auto-restore (PostgreSQL, MongoDB)

`AUTO_RESTORE=true` is the default in `.env.example`. With backups present in
`database/`, the `auto-restore` service restores PostgreSQL and MongoDB automatically
after `docker compose up -d --build`.

MinIO is restored by `minio-bootstrap` (before MinIO starts — see above).
Neo4j is restored by `neo4j-bootstrap` (before Neo4j starts — see above).

```bash
# In .env
AUTO_RESTORE=true   # default — no change needed
```

**What gets restored automatically:**

| Database   | Service             | Condition                                             |
|------------|---------------------|-------------------------------------------------------|
| PostgreSQL | `auto-restore`      | `database/stem_kg_backup/backup.dump` or `.sql` found |
| MongoDB    | `auto-restore`      | `database/stem_kg_mongo/` is non-empty                |
| MinIO      | `minio-bootstrap`   | `database/stem_kg_minio/minio-data/` found AND fresh volume |
| Neo4j      | `neo4j-bootstrap`   | `database/stem_kg_neo4j/*.dump` found AND fresh volume |

**Failure behavior:** If a restore step fails when backup files are present, the
responsible service exits non-zero. This causes dependent services (including the
backend) to not start, making the failure visible immediately. Skipped steps (no
backup found) are not failures.

> **Idempotent but destructive:** restores drop existing data in the target databases.
> Set `AUTO_RESTORE=false` after the initial restore if you have live production data.

> **Auto-restore requires Docker socket access.**
> The `auto-restore` service mounts `/var/run/docker.sock` to call `docker exec`/`docker cp`
> on the running database containers.

---

## Neo4j — automatic bootstrap on fresh volume

The `neo4j-bootstrap` service runs before `neo4j` starts. On a fresh `neo4j_data`
volume it loads the dump from `database/stem_kg_neo4j/` automatically. No manual
steps required for a first-time deployment.

**Behavior:**
- Fresh volume + dump present → dump is loaded before neo4j starts ✓
- Volume already has data → bootstrap skips (data preserved) ✓
- No dump file present → bootstrap skips, neo4j starts empty ✓

### Re-restoring Neo4j (after data has already been loaded)

If you need to overwrite existing Neo4j data with a new dump:

```bash
docker compose stop neo4j
bash docker/import-neo4j.sh
docker compose start neo4j
```

Or via compose profile:

```bash
docker compose stop neo4j
docker compose --profile restore run --rm restore-neo4j
docker compose start neo4j
```

---

## Manual restore (individual databases)

### Option A — restore via Docker Compose profile

```bash
# PostgreSQL — requires: database/stem_kg_backup/backup.dump or backup.sql
docker compose --profile restore run --rm restore-postgres

# MongoDB — requires: database/stem_kg_mongo/ with BSON files
docker compose --profile restore run --rm restore-mongo

# MinIO — requires: database/stem_kg_minio/<bucket>/ tree or minio-data.tar.gz
docker compose --profile restore run --rm restore-minio

# Neo4j — stop neo4j first (load requires offline database)
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

To verify or manage buckets: open the MinIO console at http://localhost:9101
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

- **Neo4j search**: Graph data is loaded automatically on first start if a dump is present.
  Search endpoints are immediately available after the stack is healthy.

- **gemini_pipeline**: The extraction pipeline is independent and is not part of Docker
  Compose. It runs locally via its own Python venv. See `gemini_pipeline/readme.md`.
