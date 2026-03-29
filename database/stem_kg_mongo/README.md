# MongoDB Backup — stem_kg_mongo

Place your `mongodump` output here before running `bash docker/import-mongo.sh`.

## Expected layout

### Option A — standard `mongodump --out` output (preferred)
```
database/stem_kg_mongo/
└── Metadata-Edu/               ← directory named after the database
    ├── classes.bson
    ├── classes.metadata.json
    ├── documents.bson
    ├── documents.metadata.json
    └── ...
```

### Option B — flat layout (`mongodump --db Metadata-Edu`)
```
database/stem_kg_mongo/
├── classes.bson
├── classes.metadata.json
└── ...
```

## How to create a backup

From a running local MongoDB:
```bash
mongodump --uri "mongodb://localhost:27017" \
          --db "Metadata-Edu" \
          --out database/stem_kg_mongo
```

From the running Docker container:
```bash
docker exec stem_kg_mongodb mongodump --db Metadata-Edu --out /tmp/dump
docker cp stem_kg_mongodb:/tmp/dump/. database/stem_kg_mongo/
```

## Notes
- Database name used by the app: `Metadata-Edu` (set via `MONGODB_DB` in `.env`)
- The import script drops existing collections before restoring (`--drop`)
- Do not commit actual backup data to git
