-- Adds the candidate-provided contact phone number, now asked as a
-- required Stage 1 question (see app/agents/graph.py BASIC_REQUIRED_FIELDS).
-- Distinct from telegram_chat_id, which identifies the chat, not a
-- reachable phone number.

alter table candidates add column if not exists contact_phone text;
