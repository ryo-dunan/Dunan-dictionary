CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    ip_address TEXT,
    succeeded INTEGER NOT NULL CHECK (succeeded IN (0, 1)),
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup ON login_attempts(username, attempted_at);

CREATE TABLE IF NOT EXISTS entry_workflow (
    entry_id INTEGER PRIMARY KEY,
    publication_status TEXT NOT NULL DEFAULT 'unpublished'
      CHECK (publication_status IN ('unpublished', 'published', 'archived')),
    workflow_status TEXT NOT NULL DEFAULT 'unreviewed'
      CHECK (workflow_status IN ('unreviewed', 'draft', 'review_requested', 'returned', 'admin_review', 'verified')),
    created_by INTEGER,
    current_revision_id INTEGER,
    published_at TEXT,
    archived_at TEXT,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS entry_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    assignee_id INTEGER NOT NULL,
    assigned_by INTEGER NOT NULL,
    workload_score REAL NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned', 'in_progress', 'completed')),
    assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    assignment_kind TEXT NOT NULL DEFAULT 'inspection',
    UNIQUE(entry_id, assignee_id, status),
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (assignee_id) REFERENCES users(id),
    FOREIGN KEY (assigned_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS entry_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    base_revision_id INTEGER,
    snapshot_json TEXT NOT NULL,
    change_summary TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
      CHECK (status IN ('draft', 'review_requested', 'returned', 'admin_review', 'approved', 'superseded')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id),
    FOREIGN KEY (base_revision_id) REFERENCES entry_revisions(id)
);

CREATE TABLE IF NOT EXISTS review_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    revision_id INTEGER NOT NULL,
    requester_id INTEGER NOT NULL,
    reviewer_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending', 'approved', 'returned', 'escalated', 'cancelled')),
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    CHECK (requester_id != reviewer_id),
    FOREIGN KEY (revision_id) REFERENCES entry_revisions(id) ON DELETE CASCADE,
    FOREIGN KEY (requester_id) REFERENCES users(id),
    FOREIGN KEY (reviewer_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_request_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    body TEXT NOT NULL,
    field_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (review_request_id) REFERENCES review_requests(id) ON DELETE CASCADE,
    FOREIGN KEY (author_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    abbreviation TEXT,
    bibliography TEXT NOT NULL,
    url TEXT,
    source_type TEXT,
    show_on_public INTEGER NOT NULL DEFAULT 1 CHECK (show_on_public IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entry_source_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 100,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);
CREATE INDEX IF NOT EXISTS idx_source_sections_entry ON entry_source_sections(entry_id, sort_order);

CREATE TABLE IF NOT EXISTS entry_source_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    source_headword TEXT,
    source_description TEXT,
    locator TEXT,
    note TEXT,
    adopted_interpretation TEXT,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(id),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS entry_checklists (
    entry_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    checked_by INTEGER,
    checked_at TEXT,
    note TEXT,
    PRIMARY KEY(entry_id, item_key),
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY (checked_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS quarantine_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_table TEXT NOT NULL,
    source_id INTEGER,
    reason TEXT NOT NULL,
    record_json TEXT NOT NULL,
    quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    restored_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_assignment_user ON entry_assignments(assignee_id, status);
CREATE INDEX IF NOT EXISTS idx_revision_entry ON entry_revisions(entry_id, created_at);
CREATE INDEX IF NOT EXISTS idx_review_reviewer ON review_requests(reviewer_id, status);
CREATE INDEX IF NOT EXISTS idx_source_entry ON entry_source_records(entry_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id, created_at);

CREATE TABLE IF NOT EXISTS conjugation_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS entry_primary_sources (
    entry_id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE,
    FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS entry_search_index (
    entry_id INTEGER NOT NULL,
    language TEXT NOT NULL,
    normalized_headword TEXT NOT NULL DEFAULT '',
    normalized_kana TEXT NOT NULL DEFAULT '',
    normalized_ipa TEXT NOT NULL DEFAULT '',
    normalized_definition TEXT NOT NULL DEFAULT '',
    normalized_examples TEXT NOT NULL DEFAULT '',
    normalized_conjugations TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(entry_id, language),
    FOREIGN KEY(entry_id) REFERENCES entries(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_search_headword ON entry_search_index(normalized_headword);
CREATE INDEX IF NOT EXISTS idx_search_kana ON entry_search_index(normalized_kana);

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_by INTEGER NOT NULL,
    original_filename TEXT,
    status TEXT NOT NULL DEFAULT 'preview' CHECK(status IN ('preview','applied','cancelled','failed')),
    payload_json TEXT NOT NULL,
    result_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_at TEXT,
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS backup_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    integrity_result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS example_state (
    example_id INTEGER PRIMARY KEY,
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0,1)),
    archived_at TEXT,
    FOREIGN KEY(example_id) REFERENCES examples(id) ON DELETE CASCADE
);
