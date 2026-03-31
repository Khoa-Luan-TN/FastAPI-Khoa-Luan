# Deployment Guide

## Project structure

```
FastAPI-Khoa-Luan/
  app/                  ← FastAPI backend
  frontend/             ← React/Vite UI
  gemini_pipeline/      ← Textbook extraction pipeline (runs independently)
    Input/              ← Source PDFs
    Output/             ← Processed bundles (imported via /admin/book-bundle)
    sgk_extract/        ← Core pipeline code
    scripts/            ← Entry points + Kaggle helpers
```

`gemini_pipeline/` is self-contained and runs separately from the FastAPI app.
The FastAPI app only consumes already-generated bundles from `gemini_pipeline/Output/`
via the admin page at `/admin/book-bundle`.
See `gemini_pipeline/readme.md` for pipeline setup and usage.

---


## Prerequisites

- Docker Engine ≥ 24 and Docker Compose ≥ 2.20
- At least 6 GB free disk space (torch CPU wheel is large)

---

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set strong passwords for `PG_PASSWORD`, `NEO4J_PASSWORD`, `MINIO_SECRET_KEY`.

> For the `ers.etechs.vn` deployment, keep `VITE_API_BASE`, `VITE_API_URL`,
> and `VITE_API_BASE_URL` as `/api`. The frontend nginx container forwards
> `/api/*` to the FastAPI backend so the site stays on one domain.

---

## 2. Build and start all services

```bash
docker compose up --build -d
```

First build will take several minutes — torch (~800 MB) and sentence-transformers are downloaded.

---

## 3. Expected URLs

| Service          | URL                              |
|------------------|----------------------------------|
| Frontend         | http://localhost:3040            |
| Backend API      | http://localhost:8100            |
| API docs         | http://localhost:8100/docs       |
| MinIO console    | http://localhost:9101            |
| Neo4j browser    | http://localhost:18474           |
| PostgreSQL       | localhost:5434                   |
| MongoDB          | localhost:27019                  |

---

## 4. Stop

```bash
docker compose down
```

To also remove all data volumes:

```bash
docker compose down -v
```

## 4a. Cloudflare Tunnel for `ers.etechs.vn`

1. Copy `.env.example` to `.env` and fill:
   `CLOUDFLARE_TUNNEL_ID`, `CLOUDFLARE_TUNNEL_CREDENTIALS_FILE`
2. Put the Cloudflare tunnel credentials JSON in `cloudflared/`
3. Create a DNS/public hostname in Cloudflare for `ers.etechs.vn`
4. Start the extra profile:

```bash
docker compose --profile tunnel up -d
```

The tunnel sends `ers.etechs.vn` to the frontend container, and frontend nginx
forwards `/api/*` to the backend container internally.

---

## 5. Known first-start notes

- **Neo4j graph data**: On a fresh volume the `neo4j-bootstrap` service automatically loads
  `database/stem_kg_neo4j/*.dump` before Neo4j starts. No manual step required.
  If no dump is present Neo4j starts empty; graph-dependent search features will return no results
  until data is imported.

- **ML model download**: `sentence-transformers` downloads `intfloat/multilingual-e5-base`
  from Hugging Face the first time the backend starts. Ensure internet access during first boot.

- **MinIO data**: The `minio-bootstrap` service copies `database/stem_kg_minio/minio-data/`
  into the MinIO volume before MinIO starts, on a fresh volume. The `minio-init` service then
  ensures the bucket exists (idempotent). No manual action needed.

- **VITE_API_BASE is a build-time variable**: Changing it requires rebuilding the frontend image
  (`docker compose build frontend`). It cannot be changed at runtime. Keep the default `/api`
  unless you need direct access to the backend without the nginx proxy.

---

## 6. Rebuild individual services

```bash
docker compose build backend   # after changing Python code
docker compose build frontend  # after changing React code or VITE_API_BASE
docker compose up -d           # restart with new images
```
