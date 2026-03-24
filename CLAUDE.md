# Services Cleanup Notes

## Changes Applied

- `document_service.py`: Added clarifying file-level comment explaining its role as the create
  orchestration layer and noting the intentional duplication of helper functions with the router.
- `sync_service.py`: Added clarifying file-level comment documenting the Mongo → PG → Neo4j
  pipeline and its callers.
- `neo_sync_service.py`: Added clarifying file-level comment. Added note that
  `ensure_neo_vector_indexes()` is defined but not called from any production path.
- `neo_search_service.py`: Added clarifying file-level comment (read-only, called by search_service
  only).
- `search_service.py`: Added clarifying file-level comment documenting the full search pipeline and
  that `run_topic_probe` is the sole entry point.
- `search_description_service.py`: Added clarifying file-level comment (Gemini description
  generator, called by search_service only).
- `entity_embedding_service.py`: Added clarifying file-level comment explaining the dispatch model
  and that lesson/chunk/keyword embedding is handled outside this shared pipeline.
- `topic_embedding_text_service.py`: Added clarifying file-level comment (no Gemini, no filtering).
- `keyword_alias_service.py`: Added clarifying file-level comment and noted the intentional
  `_slugify_vi` duplication with mongo_import_service.
- `mongo_minio_service.py`: Added clarifying file-level comment (event mirror, not a MinIO client).
- `mongo_reference_backfill_service.py`: Added clarifying top comment that it is a maintenance
  utility not called from any router or production path.

## Intentionally Kept Separate

- **search_service / neo_search_service / search_description_service**: Different layers.
  `neo_search_service` owns Neo4j vector queries. `search_description_service` owns Gemini text
  generation. `search_service` is the pipeline orchestrator that calls both. Merging would create
  a god-object.

- **sync_service / neo_sync_service / entity_embedding_service / topic_embedding_text_service**:
  Different responsibilities in the Mongo → PG → Neo sync chain. `sync_service` orchestrates.
  `neo_sync_service` owns all Neo4j write Cypher. `entity_embedding_service` owns PG vector upserts.
  `topic_embedding_text_service` owns the topic keyword text assembly (no Gemini, no embeddings).
  All four are called in a strict dependency order; merging would obscure the transaction boundaries.

- **mongo_import_service / mongo_minio_service / mongo_reference_backfill_service / document_service**:
  `document_service` handles single-document CRUD with full validation (used by REST endpoints).
  `mongo_import_service` handles bulk Excel import with its own import_key upsert logic and MinIO
  folder scaffolding. `mongo_minio_service` mirrors MinIO file events into the asset collection
  (event-driven, no business entity logic). `mongo_reference_backfill_service` is a one-off
  maintenance script. All four have non-overlapping responsibilities.

- **gemini_alias_service / gemini_keyword_service / keyword_alias_service**:
  `gemini_alias_service` owns raw Gemini prompt/parse logic for alias generation and screening.
  `gemini_keyword_service` owns raw Gemini prompt/parse logic for query keyword extraction.
  `keyword_alias_service` owns DB read/write for aliases and orchestrates the two-stage batch
  refresh by calling gemini_alias_service. These are three distinct abstraction layers; merging
  them would mix DB concerns with AI prompt concerns.

- **minio_client / minio_marker_service**: `minio_client` returns a raw Minio SDK client (no
  business logic). `minio_marker_service` contains stateless folder marker helpers that accept a
  client as a parameter. The separation allows minio_marker_service to be tested or reused without
  holding a client singleton.

## Suspicious / Left Untouched

- **`ensure_neo_vector_indexes()` in neo_sync_service.py**: Defined but never called from any
  router or startup hook. The inline `_ensure_vector_index_for_col()` (called from `sync_upsert`)
  handles index creation at sync time. Left untouched — may be intended for a manual admin
  endpoint or future startup hook.

- **`backfill_mongo_references()` in mongo_reference_backfill_service.py**: Never called from any
  router or startup code. Its own docstring says "call manually". Left untouched — it is a
  maintenance utility, not dead code.

- **`_now()` private helper duplicated in 6 files** (import_job_service, keyword_alias_service,
  mongo_import_service, document_service, mongo_minio_service, routers/mongo/documents.py):
  Each is a one-liner `datetime.now(timezone.utc)`. Extracting to a shared module would add an
  import dependency for a trivial function. Left as-is — not a meaningful duplication risk.

- **`_normalize_collection_name` / `_check_collection_exist` duplicated** across
  routers/mongo/documents.py, routers/mongo/imports.py, routers/mongo/collections.py, and
  document_service.py: The router copies use `status.HTTP_404_NOT_FOUND`, the service copy uses a
  plain integer. These are router-layer guards that should not depend on the service layer. Left
  as-is — consolidating into a shared helper would require either a new shared module or a circular
  import risk.

- **`_user_normalize_and_validate` duplicated** in document_service.py (create path) and
  routers/mongo/documents.py (update path): The two copies have identical logic but different
  callers. The router's copy is private (`_` prefix) and the service's copy is also private. The
  router cannot import from the service for this particular helper without coupling the router to
  the service implementation. Left as-is — the duplication is ~25 lines and low-risk.

- **`_slugify_vi` duplicated** in keyword_alias_service.py (accepts `str`) and
  mongo_import_service.py (accepts `Any`): Different type signatures; both are private and
  internally used. Left as-is.

---

## Second Pass — Real Deduplication

### New file created: `app/services/_utils.py`

Contains two shared pure helpers moved out of individual service files:

- `utc_now() -> datetime` — replaces the identical `_now()` one-liner in all service files
- `slugify_vi(text: Any) -> str` — replaces both private `_slugify_vi` copies; uses `Any` input
  (strict superset of the `str`-only version in keyword_alias_service); logic is identical to both
  prior copies

### `_now()` deduplication

**Removed** the local `_now()` definition from and replaced all calls with `utc_now()` in:
- `app/services/import_job_service.py`
- `app/services/keyword_alias_service.py`
- `app/services/mongo_import_service.py`
- `app/services/document_service.py`
- `app/services/mongo_minio_service.py`

**Left untouched** (as instructed):
- `app/routers/mongo/documents.py` — router keeps its own `_now()` to avoid any service→router
  coupling

### `_slugify_vi` result: unified into `slugify_vi` in `_utils.py`

Both copies had identical logic. The only difference was the type annotation (`str` vs `Any`).
The unified `slugify_vi(text: Any)` covers both call sites without any behavioral change:
- `app/services/keyword_alias_service.py` — removed private `_slugify_vi`, now calls `slugify_vi`
- `app/services/mongo_import_service.py` — removed private `_slugify_vi`, now calls `slugify_vi`
- Removed stale imports (`re`, `unicodedata`, `datetime/timezone`) from both files where no longer
  needed after the move

### `_normalize_collection_name` / `_check_collection_exist` result: left separate

All four copies (routers/mongo/documents.py, routers/mongo/imports.py, routers/mongo/collections.py,
app/services/document_service.py) are functionally identical. However:
- Routers must not be touched (task constraint)
- The service copy uses plain `404` integer; router copies use `status.HTTP_404_NOT_FOUND` (same
  value, different import)
- Moving the service copy to `_utils.py` gains nothing without also consolidating the router copies,
  which are off-limits
- Left as-is: each file's copy is self-contained and the duplication is low-risk (~6 lines each)

### `_user_normalize_and_validate` result: left separate

The copies in `document_service.py` (create path) and `routers/mongo/documents.py` (update path)
are logically identical but each accesses its own module-level `db` reference. Moving to `_utils.py`
would require passing `db` as a parameter — a signature change that would affect callers in both
the service and the router. Since routers must not be touched, this consolidation is not safe.
Left as-is.

### `ensure_neo_vector_indexes` result: kept with comment

Confirmed never called from any production path (only the definition appears in grep results).
Added `# NOTE: Not called from production startup. Intended for manual admin use.` directly above
the function definition in `app/services/neo_sync_service.py`.
