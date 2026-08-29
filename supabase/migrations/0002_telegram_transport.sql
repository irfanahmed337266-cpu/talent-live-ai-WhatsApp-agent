-- Migration for databases that already ran the original WhatsApp schema.
-- Fresh installations should use the Telegram names in 0000 and 0001.

do $$
begin
    if exists (select 1 from information_schema.columns
               where table_name = 'candidates' and column_name = 'whatsapp_number')
       and not exists (select 1 from information_schema.columns
                       where table_name = 'candidates' and column_name = 'telegram_chat_id') then
        alter table candidates rename column whatsapp_number to telegram_chat_id;
    end if;

    if exists (select 1 from information_schema.columns
               where table_name = 'interview_messages' and column_name = 'whatsapp_message_id')
       and not exists (select 1 from information_schema.columns
                       where table_name = 'interview_messages' and column_name = 'telegram_message_id') then
        alter table interview_messages rename column whatsapp_message_id to telegram_message_id;
    end if;

    if exists (select 1 from information_schema.columns
               where table_name = 'candidate_materials' and column_name = 'whatsapp_media_id')
       and not exists (select 1 from information_schema.columns
                       where table_name = 'candidate_materials' and column_name = 'telegram_media_id') then
        alter table candidate_materials rename column whatsapp_media_id to telegram_media_id;
    end if;

    if exists (select 1 from information_schema.columns
               where table_name = 'agent_sessions' and column_name = 'phone_number')
       and not exists (select 1 from information_schema.columns
                       where table_name = 'agent_sessions' and column_name = 'telegram_chat_id') then
        alter table agent_sessions rename column phone_number to telegram_chat_id;
    end if;

    if exists (select 1 from information_schema.columns
               where table_name = 'agent_sessions' and column_name = 'last_whatsapp_message_id')
       and not exists (select 1 from information_schema.columns
                       where table_name = 'agent_sessions' and column_name = 'last_telegram_message_id') then
        alter table agent_sessions rename column last_whatsapp_message_id to last_telegram_message_id;
    end if;
end $$;

alter table candidates add column if not exists telegram_chat_id text;
alter table candidates add column if not exists telegram_username text;
alter table interview_messages add column if not exists telegram_message_id text;
alter table candidate_materials add column if not exists telegram_media_id text;
alter table agent_sessions add column if not exists telegram_chat_id text;
alter table agent_sessions add column if not exists last_telegram_message_id text;

create unique index if not exists candidates_telegram_chat_id_idx
    on candidates (telegram_chat_id)
    where telegram_chat_id is not null;

create index if not exists agent_sessions_telegram_message_id_idx
    on agent_sessions (last_telegram_message_id);