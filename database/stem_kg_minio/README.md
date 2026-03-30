# MinIO Backup — stem_kg_minio

Place your MinIO object backup here before running `bash docker/import-minio.sh`
or the `restore-minio` compose service.

## Expected layout

### Option A — extracted object tree (preferred)
```
database/stem_kg_minio/
└── data-edu/               ← directory named after the bucket
    ├── object1.pdf
    ├── subdir/
    │   └── object2.json
    └── ...
```

### Option B — compressed archive
```
database/stem_kg_minio/
└── minio-data.tar.gz       ← must contain <bucket-name>/ at top level
```

## How to create a backup

From the running MinIO container (using mc):
```bash
# Extract object tree directly
docker run --rm \
  --network <compose_network> \
  -v "$(pwd)/database/stem_kg_minio:/backup" \
  minio/mc \
  /bin/sh -c "
    mc alias set local http://stem_kg_minio:9000 <access_key> <secret_key> &&
    mc mirror local/data-edu /backup/data-edu
  "

# Or create a tarball from the extracted tree
tar -czf database/stem_kg_minio/minio-data.tar.gz \
    -C database/stem_kg_minio data-edu
```

## Notes
- Default bucket name: `data-edu` (set via `MINIO_BUCKET` in `.env`)
- The import script and restore service both use `mc mirror --overwrite`
- Existing objects in the bucket are overwritten; unrelated objects are left intact
- Do not commit actual backup data to git (objects can be large)
