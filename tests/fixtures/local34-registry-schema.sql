CREATE TABLE IF NOT EXISTS desktop_registry_values (
    value_hash TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS desktop_registry_baselines (
    filename TEXT NOT NULL,
    root_id TEXT NOT NULL,
    group_name TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL,
    PRIMARY KEY (filename, root_id, group_name),
    FOREIGN KEY (value_hash) REFERENCES desktop_registry_values(value_hash)
);
