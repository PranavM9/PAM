-- SPEC §7.8 Index schema (M4 writes; M5/M6 read), verbatim. Derived data: `pam index --rebuild` recreates it.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- keys: schema_version, embedding_model, embedding_dim, index_version, last_indexed_commit

CREATE TABLE IF NOT EXISTS documents (
  doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL CHECK (doc_type IN ('episode','fact','project','skill')),
  scope TEXT NOT NULL, path TEXT NOT NULL UNIQUE, title TEXT, created_at TEXT,
  content_sha256 TEXT NOT NULL, token_count INTEGER NOT NULL, indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  rowid INTEGER PRIMARY KEY,               -- shared with chunks_fts and chunks_vec
  chunk_id TEXT NOT NULL UNIQUE,           -- "<doc_id>:<ordinal>"
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  ordinal INTEGER NOT NULL, text TEXT NOT NULL, token_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(embedding float[384]);
CREATE TABLE IF NOT EXISTS doc_vectors (doc_id TEXT PRIMARY KEY, embedding BLOB NOT NULL);       -- mean of chunk vectors, L2-normalized
CREATE TABLE IF NOT EXISTS project_centroids (project_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, updated_at TEXT NOT NULL);
