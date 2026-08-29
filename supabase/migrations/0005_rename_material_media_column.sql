-- candidate_materials.telegram_media_id was never actually populated
-- (nothing called save_candidate_material() until now). Renaming to a
-- transport-agnostic name before first real use.

alter table candidate_materials rename column telegram_media_id to media_file_id;
