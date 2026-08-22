from app.db.migration_engine import Migration

ITEMS = Migration(
    migration_id="0010_items",
    dependencies=("0001_core",),
    up_sql="""
    CREATE TABLE items (
        item_id uuid PRIMARY KEY,
        workspace_id uuid NULL,
        name text NOT NULL,
        description text NULL,
        status text NOT NULL CHECK (status IN ('ACTIVE', 'ARCHIVED')),
        version integer NOT NULL CHECK (version >= 1),
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    );
    CREATE INDEX idx_items_workspace_created
        ON items (workspace_id, created_at DESC, item_id DESC);
    CREATE INDEX idx_items_workspace_status
        ON items (workspace_id, status, created_at DESC);
    """,
)
