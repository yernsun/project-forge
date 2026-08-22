from app.db.migration_engine import Migration

EVENTS = Migration(
    migration_id="0030_events",
    dependencies=("0001_core",),
    up_sql="""
    CREATE TABLE outbox_events (
        event_id uuid PRIMARY KEY,
        event_type text NOT NULL,
        schema_version integer NOT NULL CHECK (schema_version >= 1),
        payload jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        available_at timestamptz NOT NULL,
        attempts integer NOT NULL DEFAULT 0,
        locked_at timestamptz NULL,
        locked_by text NULL,
        published_at timestamptz NULL
    );
    CREATE INDEX idx_outbox_pending
        ON outbox_events (available_at, created_at)
        WHERE published_at IS NULL;
    CREATE TABLE processed_messages (
        consumer_name text NOT NULL,
        message_id text NOT NULL,
        processed_at timestamptz NOT NULL,
        PRIMARY KEY (consumer_name, message_id)
    );
    """,
)
