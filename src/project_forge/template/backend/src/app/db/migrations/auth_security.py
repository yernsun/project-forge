from app.db.migration_engine import Migration

AUTH_SECURITY = Migration(
    migration_id="0021_auth_security",
    dependencies=("0020_auth",),
    up_sql="""
    ALTER TABLE users
        ADD COLUMN status text NOT NULL DEFAULT 'ACTIVE'
            CHECK (status IN ('ACTIVE', 'DISABLED')),
        ADD COLUMN version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
        ADD COLUMN updated_at timestamptz,
        ADD COLUMN password_updated_at timestamptz;
    UPDATE users
        SET updated_at = created_at,
            password_updated_at = created_at
        WHERE updated_at IS NULL OR password_updated_at IS NULL;
    ALTER TABLE users
        ALTER COLUMN updated_at SET NOT NULL,
        ALTER COLUMN password_updated_at SET NOT NULL;
    UPDATE users SET email = lower(email) WHERE email <> lower(email);
    CREATE UNIQUE INDEX uq_users_email_canonical ON users ((lower(email)));
    CREATE INDEX idx_workspace_members_user_workspace
        ON workspace_members (user_id, workspace_id);

    ALTER TABLE sessions
        ADD CONSTRAINT ck_sessions_expiry CHECK (expires_at > created_at);
    CREATE INDEX idx_sessions_expires_at ON sessions (expires_at);

    CREATE TABLE auth_rate_limits (
        scope text NOT NULL,
        subject_hash char(64) NOT NULL,
        window_started_at timestamptz NOT NULL,
        attempt_count integer NOT NULL CHECK (attempt_count >= 1),
        expires_at timestamptz NOT NULL,
        PRIMARY KEY (scope, subject_hash, window_started_at),
        CHECK (expires_at > window_started_at)
    );
    CREATE INDEX idx_auth_rate_limits_expires_at ON auth_rate_limits (expires_at);
    """,
)
