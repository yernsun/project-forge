from app.db.migration_engine import Migration

AUTH = Migration(
    migration_id="0020_auth",
    dependencies=("0001_core",),
    up_sql="""
    CREATE TABLE users (
        user_id uuid PRIMARY KEY,
        email text NOT NULL UNIQUE,
        password_hash text NOT NULL,
        created_at timestamptz NOT NULL
    );
    CREATE TABLE workspaces (
        workspace_id uuid PRIMARY KEY,
        name text NOT NULL,
        created_at timestamptz NOT NULL
    );
    CREATE TABLE workspace_members (
        workspace_id uuid NOT NULL REFERENCES workspaces (workspace_id) ON DELETE CASCADE,
        user_id uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
        created_at timestamptz NOT NULL,
        PRIMARY KEY (workspace_id, user_id)
    );
    CREATE TABLE sessions (
        session_id uuid PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
        token_hash text NOT NULL UNIQUE,
        csrf_hash text NOT NULL,
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL
    );
    CREATE INDEX idx_sessions_user_expires ON sessions (user_id, expires_at);
    """,
)
