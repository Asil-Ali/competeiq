-- CompeteIQ — Supabase Database Setup
-- Run this ONCE in Supabase → SQL Editor → New query → Run

-- Enable pgvector extension for semantic memory
CREATE EXTENSION IF NOT EXISTS vector;

-- ── ANALYSES HISTORY ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS analyses (
    id               BIGSERIAL PRIMARY KEY,
    business_name    TEXT,
    industry         TEXT DEFAULT 'general',
    quality_score    FLOAT DEFAULT 0,
    competitor_count INT   DEFAULT 0,
    reflection_count INT   DEFAULT 0,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_analyses_industry ON analyses(industry);
CREATE INDEX IF NOT EXISTS idx_analyses_created  ON analyses(created_at);

-- ── SUCCESSFUL SEARCH QUERIES ──────────────────────────────
CREATE TABLE IF NOT EXISTS search_queries (
    id         BIGSERIAL PRIMARY KEY,
    query      TEXT UNIQUE NOT NULL,
    industry   TEXT DEFAULT 'general',
    use_count  INT  DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_queries_industry ON search_queries(industry);
CREATE INDEX IF NOT EXISTS idx_queries_use      ON search_queries(use_count DESC);

-- ── AGENT LEARNINGS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS learnings (
    id         BIGSERIAL PRIMARY KEY,
    learning   TEXT UNIQUE NOT NULL,
    industry   TEXT DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_learnings_industry ON learnings(industry);

-- ── KNOWN COMPETITORS ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS known_competitors (
    id           BIGSERIAL PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    industry     TEXT DEFAULT 'general',
    seen_count   INT  DEFAULT 1,
    last_pricing TEXT DEFAULT '',
    last_threat  TEXT DEFAULT '',
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitors_industry ON known_competitors(industry);
CREATE INDEX IF NOT EXISTS idx_competitors_seen     ON known_competitors(seen_count DESC);

-- ── RATE LIMITING ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limits (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_limits(user_id, created_at);

-- Auto-cleanup old rate limit records (older than 2 days)
CREATE OR REPLACE FUNCTION cleanup_rate_limits()
RETURNS void AS $$
BEGIN
    DELETE FROM rate_limits WHERE created_at < NOW() - INTERVAL '2 days';
END;
$$ LANGUAGE plpgsql;

-- ── ROW LEVEL SECURITY (allow anon key to read/write) ─────
ALTER TABLE analyses         ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_queries   ENABLE ROW LEVEL SECURITY;
ALTER TABLE learnings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE known_competitors ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limits      ENABLE ROW LEVEL SECURITY;

-- Allow all operations for anon key (the bot uses anon key)
CREATE POLICY "allow_all_analyses"          ON analyses          FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_queries"           ON search_queries    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_learnings"         ON learnings         FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_competitors"       ON known_competitors FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "allow_all_rate_limits"       ON rate_limits       FOR ALL USING (true) WITH CHECK (true);

-- Done! Your database is ready.
-- Now get your credentials from: Settings → API → URL + anon key
