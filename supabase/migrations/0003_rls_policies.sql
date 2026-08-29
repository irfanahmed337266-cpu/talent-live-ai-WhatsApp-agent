-- Lock recruitment data behind the backend service role.
-- The application uses SUPABASE_KEY server-side; no browser client should
-- access candidate or interview records directly.

alter table candidates enable row level security;
alter table interviews enable row level security;
alter table interview_messages enable row level security;
alter table interview_scores enable row level security;
alter table candidate_materials enable row level security;
alter table agent_sessions enable row level security;

do $$
begin
    if not exists (select 1 from pg_policies where tablename = 'candidates' and policyname = 'backend service role access') then
        create policy "backend service role access" on candidates to service_role using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where tablename = 'interviews' and policyname = 'backend service role access') then
        create policy "backend service role access" on interviews to service_role using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where tablename = 'interview_messages' and policyname = 'backend service role access') then
        create policy "backend service role access" on interview_messages to service_role using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where tablename = 'interview_scores' and policyname = 'backend service role access') then
        create policy "backend service role access" on interview_scores to service_role using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where tablename = 'candidate_materials' and policyname = 'backend service role access') then
        create policy "backend service role access" on candidate_materials to service_role using (true) with check (true);
    end if;
    if not exists (select 1 from pg_policies where tablename = 'agent_sessions' and policyname = 'backend service role access') then
        create policy "backend service role access" on agent_sessions to service_role using (true) with check (true);
    end if;
end $$;
