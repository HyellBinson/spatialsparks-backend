import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

# Define the project directory first.
BASE_DIR = Path(__file__).resolve().parents[2]

# Load environment variables.
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing from the backend .env file.")

STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_connection():
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=15,
    )


def init_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                file_size BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id)
                    ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                image_ids TEXT NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id)
        """)



                # Connect existing records to Supabase Auth users.
        connection.execute("""
            ALTER TABLE uploads
            ADD COLUMN IF NOT EXISTS user_id UUID
            REFERENCES auth.users(id) ON DELETE CASCADE
        """)

        connection.execute("""
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS user_id UUID
            REFERENCES auth.users(id) ON DELETE CASCADE
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_uploads_user
            ON uploads(user_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user
            ON conversations(user_id)
        """)

        connection.execute("""
            ALTER TABLE uploads
            ADD COLUMN IF NOT EXISTS storage_path TEXT
        """)

                # Persistent inspection history metadata
        connection.execute("""
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS title TEXT NOT NULL
            DEFAULT 'New inspection'
        """)

        connection.execute("""
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS project_type TEXT NOT NULL
            DEFAULT 'inspection'
        """)

        connection.execute("""
            ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
            NOT NULL DEFAULT NOW()
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_updated
            ON conversations(user_id, updated_at DESC)
        """)