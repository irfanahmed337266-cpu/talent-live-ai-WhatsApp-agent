-- Base schema for the Talent Live AI Telegram Talent Agent.
--
-- Reverse-engineered from how app/services/supabase.py and app/agents/graph.py
-- read and write these tables (no prior schema existed in this repo).
-- Run this before 0001_agent_sessions.sql on a fresh Supabase project.

create extension if not exists pgcrypto;

-- ============================================================================
-- CANDIDATES
-- ============================================================================
-- graph.py upserts on telegram_chat_id and only ever writes:
-- name, language, current_stage, status, engaged.
-- The full candidate profile (age, skills, education, etc.) lives in
-- agent_sessions.state_json, not as columns here.

create table if not exists candidates (
    id uuid primary key default gen_random_uuid(),
    telegram_chat_id text not null unique,
    telegram_username text,
    name text,
    language text,
    current_stage integer,
    status text,
    engaged boolean,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ============================================================================
-- INTERVIEWS
-- ============================================================================
-- create_interview() reads back "id" and "started_at". get_active_interview()
-- filters status = 'active' ordered by created_at desc.

create table if not exists interviews (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references candidates(id) on delete cascade,
    status text not null default 'active',
    current_stage integer,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    completion_reason text,
    created_at timestamptz not null default now()
);

create index if not exists interviews_candidate_id_idx on interviews(candidate_id);
create index if not exists interviews_status_idx on interviews(status);

-- ============================================================================
-- INTERVIEW MESSAGES
-- ============================================================================
-- save_interview_message() always writes: interview_id, sender, message_text,
-- message_type, stage, telegram_message_id, metadata.
--
-- "sender" is left as free text (no check constraint) since the integration
-- layer currently writes "candidate"/"assistant" but nothing in the existing
-- code fixes that vocabulary — tighten this once you confirm the convention.

create table if not exists interview_messages (
    id uuid primary key default gen_random_uuid(),
    interview_id uuid not null references interviews(id) on delete cascade,
    sender text not null,
    message_text text not null,
    message_type text not null default 'text',
    stage integer not null default 0,
    telegram_message_id text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists interview_messages_interview_id_idx on interview_messages(interview_id);

-- ============================================================================
-- INTERVIEW SCORES
-- ============================================================================
-- save_interview_score() upserts on_conflict="interview_id", so interview_id
-- must be unique.

create table if not exists interview_scores (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references candidates(id) on delete cascade,
    interview_id uuid not null unique references interviews(id) on delete cascade,
    total_score integer not null,
    hunger_score integer not null,
    skill_score integer not null,
    engagement_score integer not null,
    consistency_score integer not null,
    stability_score integer not null,
    deductions_total integer not null,
    score_band text not null,
    score_note text,
    score_rationale jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- ============================================================================
-- CANDIDATE MATERIALS
-- ============================================================================
-- NOTE: nothing called save_candidate_material() until it was wired up in
-- app/api/telegram.py (see 0003_rename_material_media_column.sql for a
-- follow-up column rename). Adjust freely if you want a different
-- materials model than "metadata only, no file download."

create table if not exists candidate_materials (
    id uuid primary key default gen_random_uuid(),
    candidate_id uuid not null references candidates(id) on delete cascade,
    material_type text,
    telegram_media_id text,
    mime_type text,
    file_name text,
    caption text,
    created_at timestamptz not null default now()
);

create index if not exists candidate_materials_candidate_id_idx on candidate_materials(candidate_id);
