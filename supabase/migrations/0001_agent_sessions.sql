-- Persists the full LangGraph AgentState between Telegram webhook calls,
-- keyed by Telegram chat ID, plus the last processed Telegram message id for
-- idempotent webhook delivery handling.
--
-- Run 0000_initial_schema.sql first — candidate_id/interview_id reference
-- those tables. Both stay nullable because a session exists (Stage 0-2)
-- before the candidate/interview rows are lazily created in graph.py.

create table if not exists agent_sessions (
    telegram_chat_id text primary key,
    candidate_id uuid null references candidates(id) on delete set null,
    interview_id uuid null references interviews(id) on delete set null,
    state_json jsonb not null,
    last_telegram_message_id text null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists agent_sessions_last_message_id_idx
    on agent_sessions (last_telegram_message_id);

create or replace function set_agent_sessions_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists agent_sessions_set_updated_at on agent_sessions;

create trigger agent_sessions_set_updated_at
    before update on agent_sessions
    for each row
    execute function set_agent_sessions_updated_at();
