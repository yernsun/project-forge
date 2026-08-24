from app.db.migration_engine import Migration

EVENT_IDEMPOTENCY = Migration(
    migration_id="0031_event_idempotency",
    dependencies=("0030_events",),
    up_sql="""
    ALTER TABLE processed_messages
        RENAME COLUMN message_id TO event_id;
    COMMENT ON COLUMN processed_messages.event_id IS
        'Stable business event ID; legacy rows created before 0031 contain Redis message IDs';
    """,
)
