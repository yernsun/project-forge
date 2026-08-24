from app.db.migration_engine import Migration

AUTH_ITEMS = Migration(
    migration_id="0022_auth_items",
    dependencies=("0010_items", "0021_auth_security"),
    up_sql="""
    ALTER TABLE items
        ADD CONSTRAINT fk_items_workspace
        FOREIGN KEY (workspace_id)
        REFERENCES workspaces (workspace_id)
        ON DELETE CASCADE
        NOT VALID;
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1
            FROM items i
            LEFT JOIN workspaces w ON w.workspace_id = i.workspace_id
            WHERE i.workspace_id IS NOT NULL AND w.workspace_id IS NULL
        ) THEN
            ALTER TABLE items VALIDATE CONSTRAINT fk_items_workspace;
        END IF;
    END
    $$;
    """,
)
