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

> `VITE_API_BASE` must be the URL where the **browser** can reach the backend.
> For local deployment on the same machine leave it as `http://localhost:8000`.

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
| Frontend         | http://localhost:3000            |
| Backend API      | http://localhost:8000            |
| API docs         | http://localhost:8000/docs       |
| MinIO console    | http://localhost:9001            |
| Neo4j browser    | http://localhost:7474            |
| PostgreSQL       | localhost:5432                   |
| MongoDB          | localhost:27017                  |

---

## 4. Stop

```bash
docker compose down
```

To also remove all data volumes:

```bash
docker compose down -v
```

---

## 5. Manual preconditions / known blockers

- **Neo4j graph data**: The app reads from an existing Neo4j graph. After first startup the
  database will be empty. Restore a Neo4j dump into the `neo4j_data` volume before running
  searches that rely on graph nodes.

- **ML model download**: `sentence-transformers` and `BAAI/bge-reranker-v2-m3` are downloaded
  from Hugging Face the first time the backend starts. Ensure internet access during first boot,
  or pre-cache the models into the image.

- **MinIO bucket**: The bucket `data-edu` is not auto-created. Create it manually via the MinIO
  console (http://localhost:9001) after first startup, or add a bucket-init container.

- **VITE_API_BASE is a build-time variable**: Changing it requires rebuilding the frontend image
  (`docker compose build frontend`). It cannot be changed at runtime.

---

## 6. Rebuild individual services

```bash
docker compose build backend   # after changing Python code
docker compose build frontend  # after changing React code or VITE_API_BASE
docker compose up -d           # restart with new images
```
