# PostgreSQL Backup — stem_kg_backup

Place your PostgreSQL backup file here before running `bash docker/import-postgre.sh`.

## Expected layout

```
database/stem_kg_backup/
├── backup.dump     ← pg_dump custom format (preferred)
OR
└── backup.sql      ← pg_dump plain SQL
```

The import script checks for `backup.dump` first, then falls back to `backup.sql`.

## How to create a backup

Custom format (preferred — smaller, supports parallel restore):
```bash
pg_dump -Fc -U postgres data-edu > database/stem_kg_backup/backup.dump
```

Plain SQL:
```bash
pg_dump -U postgres data-edu > database/stem_kg_backup/backup.sql
```

From the running Docker container:
```bash
docker exec stem_kg_postgres pg_dump -Fc -U postgres data-edu > database/stem_kg_backup/backup.dump
```

## Schema

The PostgreSQL database stores the structural metadata (Class → Subject → Topic →
Lesson → Chunk → Keyword) that mirrors the MongoDB document hierarchy.
The backend auto-creates all tables on startup via SQLAlchemy, so a fresh empty
database is valid for a first deployment — only import if restoring existing data.

## Notes
- Database name: `data-edu` (set via `PG_NAME` in `.env`)
- User: `postgres` (set via `PG_USER` in `.env`)
- The import script uses `--clean --if-exists` (drops existing objects before restore)
- Do not commit actual backup files to git
