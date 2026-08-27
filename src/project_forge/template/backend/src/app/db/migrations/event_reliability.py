from app.db.migration_engine import Migration

EVENT_RELIABILITY = Migration(
    migration_id="0032_event_reliability",
    dependencies=("0031_event_idempotency",),
    up_sql="""
    ALTER TABLE outbox_events
        ADD COLUMN failed_at timestamptz NULL,
        ADD COLUMN last_failed_at timestamptz NULL,
        ADD COLUMN last_error_code text NULL
            CHECK (last_error_code IS NULL OR length(last_error_code) <= 200);
    DROP INDEX idx_outbox_pending;
    CREATE INDEX idx_outbox_pending
        ON outbox_events (available_at, created_at, event_id)
        WHERE published_at IS NULL AND failed_at IS NULL;
    CREATE INDEX idx_outbox_failed
        ON outbox_events (failed_at, event_id)
        WHERE failed_at IS NOT NULL AND published_at IS NULL;
    """,
)
