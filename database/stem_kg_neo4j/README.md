# Neo4j Backup — stem_kg_neo4j

Place your Neo4j dump file here before running `bash docker/import-neo4j.sh`.

## Expected layout

```
database/stem_kg_neo4j/
└── neo4j.dump          ← filename must match the database name + .dump
```

If your Neo4j database is named something other than `neo4j`, set `NEO4J_DATABASE`
in `.env` and rename the file accordingly (e.g. `stem.dump` for database `stem`).

## How to create a backup

From a running local Neo4j instance:
```bash
# Stop Neo4j first (dump requires offline database)
neo4j stop
neo4j-admin database dump neo4j --to-path=database/stem_kg_neo4j/
neo4j start
```

From the running Docker container (using a temporary container on the same volume):
```bash
# Find the volume name
docker inspect stem_kg_neo4j --format '{{ range .Mounts }}{{ if eq .Destination "/data" }}{{ .Name }}{{ end }}{{ end }}'

# Stop container and dump
docker stop stem_kg_neo4j
docker run --rm \
  -v <volume_name>:/data \
  -v "$(pwd)/database/stem_kg_neo4j:/backups" \
  neo4j:5 \
  neo4j-admin database dump neo4j --to-path=/backups
docker start stem_kg_neo4j
```

## Notes
- Default database name: `neo4j` (set via `NEO4J_DATABASE` in `.env`)
- The import script stops the Neo4j container during the load operation
- The Neo4j graph powers topic/keyword search — the app starts without it but
  search endpoints will return empty results until the graph is populated
- Do not commit actual dump files to git (they can be large)
