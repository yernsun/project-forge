from app.db.migration_engine import Migration

CORE = Migration(
    migration_id="0001_core",
    dependencies=(),
    up_sql="""
    CREATE TABLE app_metadata (
        key text PRIMARY KEY,
        value jsonb NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now()
    );
    """,
)
