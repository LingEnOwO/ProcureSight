-- NextAuth.js Authentication Tables
-- These tables are used by the frontend (apps/web) for authentication via NextAuth.js
-- They are SEPARATE from business logic tables (orgs, users, vendors, etc.)
-- 
-- SOLUTION: Use a separate PostgreSQL schema "nextauth" to avoid table name collision
-- The business "users" table stays in the "public" schema
-- The NextAuth "users" table goes in the "nextauth" schema

-- Create nextauth schema
CREATE SCHEMA IF NOT EXISTS nextauth;

-- Set search path to create tables in nextauth schema
SET search_path TO nextauth, public;

-- users table: Stores authenticated identities (email-based)
-- Note: @auth/pg-adapter expects camelCase column names
CREATE TABLE IF NOT EXISTS nextauth.users (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    name TEXT,
    email TEXT UNIQUE,
    "emailVerified" TIMESTAMPTZ,
    image TEXT
);

-- accounts table: Stores OAuth provider accounts (Google, GitHub, etc.)
-- Not used for email magic-link login, but included for future OAuth support
CREATE TABLE IF NOT EXISTS nextauth.accounts (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId" TEXT NOT NULL,
    type TEXT NOT NULL,
    provider TEXT NOT NULL,
    "providerAccountId" TEXT NOT NULL,
    refresh_token TEXT,
    access_token TEXT,
    expires_at BIGINT,
    token_type TEXT,
    scope TEXT,
    id_token TEXT,
    session_state TEXT,
    
    CONSTRAINT accounts_user_id_fkey 
        FOREIGN KEY ("userId") REFERENCES nextauth.users(id) 
        ON DELETE CASCADE,
    CONSTRAINT provider_provider_account_id_unique 
        UNIQUE (provider, "providerAccountId")
);

-- sessions table: Stores active sessions (optional with JWT strategy)
CREATE TABLE IF NOT EXISTS nextauth.sessions (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "sessionToken" TEXT UNIQUE NOT NULL,
    "userId" TEXT NOT NULL,
    expires TIMESTAMPTZ NOT NULL,
    
    CONSTRAINT sessions_user_id_fkey 
        FOREIGN KEY ("userId") REFERENCES nextauth.users(id) 
        ON DELETE CASCADE
);

-- verification_token table: One-time tokens for email magic-link login
-- Note: Table name is singular (verification_token, not verification_tokens)
CREATE TABLE IF NOT EXISTS nextauth.verification_token (
    identifier TEXT NOT NULL,
    token TEXT NOT NULL,
    expires TIMESTAMPTZ NOT NULL,
    
    PRIMARY KEY (identifier, token)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS accounts_user_id_idx ON nextauth.accounts("userId");
CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON nextauth.sessions("userId");
CREATE INDEX IF NOT EXISTS sessions_session_token_idx ON nextauth.sessions("sessionToken");

-- Reset search path to default
SET search_path TO public;
