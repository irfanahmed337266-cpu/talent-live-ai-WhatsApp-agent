# Talent Live AI Telegram Agent — Handoff / Architecture

An AI-driven candidate screening bot. A candidate talks to a Telegram bot,
goes through a fixed interview flow, gets a deterministic 0–100 fit score,
and — if they score high enough — shows up on a small owner-only dashboard
with their contact info.

This document explains how the pieces fit together, why they're built the
way they are, and what to watch out for. It assumes no prior context.

---

## 1. High-level architecture

```
Candidate (Telegram)
       │
       ▼
┌─────────────────────────┐        ┌──────────────────────────┐
│ app/telegram_polling.py │◄──────►│  Telegram Bot API          │
│ (long-polling loop)     │  HTTPS │  (api.telegram.org)        │
└───────────┬─────────────┘        └──────────────────────────┘
            │ reuses parse_update() / process_message()
            ▼
┌─────────────────────────┐
│ app/api/telegram.py     │  (also exposes POST /telegram/webhook —
│                         │   an alternate, currently-unused transport)
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐        ┌──────────────────────────┐
│ app/agents/graph.py     │◄──────►│  Google Gemini (optional) │
│ run_agent(state)        │        │  used only for name/age/  │
│ LangGraph state machine │        │  etc. extraction if       │
└───────────┬─────────────┘        │  USE_GEMINI_EXTRACTION=1  │
            │                      └──────────────────────────┘
            ▼
┌─────────────────────────┐
│ app/services/supabase.py│──────► Supabase Postgres (candidates,
└─────────────────────────┘        interviews, interview_messages,
                                    interview_scores, candidate_materials,
                                    agent_sessions)
            ▲
            │
┌─────────────────────────┐
│ app/api/dashboard.py    │  Owner-only: GET /owner/dashboard, /owner/candidates
└─────────────────────────┘
```

Two things run independently in production:

1. **The Telegram bot** (`app/telegram_polling.py`) — a long-running process
   that polls Telegram for messages and drives the interview. This is a
   Render **Background Worker** (no public URL).
2. **The dashboard** (`app/main.py` via `uvicorn`) — a normal web service
   serving `/health` and `/owner/dashboard`. This is a Render **Web
   Service** (has a public `onrender.com` URL).

They share the same codebase and the same Supabase database, but are
deployed and scaled separately. See [§7 Deployment](#7-deployment).

---

## 2. Why polling instead of webhooks

Telegram (and Meta/WhatsApp) webhooks require a public HTTPS URL that
Telegram pushes messages to. Getting that locally means a tunnel (ngrok)
plus signature verification, and in production it means a domain + TLS +
an exposed endpoint that must authenticate every inbound request.

Long-polling flips this: **the bot calls Telegram**, not the other way
around. `app/services/telegram.py::get_updates()` calls Telegram's
`getUpdates` endpoint in a loop; Telegram just holds the HTTP connection
open (`timeout=30`) until a message arrives or it times out, then the loop
calls again immediately (`app/telegram_polling.py::run_polling_loop`).
This needs zero inbound configuration — it's a normal outbound HTTPS
client, so it works identically on a laptop, on Render, anywhere.

The webhook code path (`app/api/telegram.py`'s `POST /telegram/webhook`)
still exists and works if you ever want to switch — `deleteWebhook()` is
called at poller startup specifically so the two transports never run at
once (Telegram refuses `getUpdates` while a webhook is registered).

---

## 3. The conversation flow (state machine)

`app/agents/graph.py` implements a fixed 6-stage LangGraph state machine.
`STAGE_*` constants (0–5) live in both `graph.py` and `interview.py`
(see the **duplication warning** in §6) — the numbers:

| Stage | Constant | What happens |
|---|---|---|
| 0 | `STAGE_INITIAL` | Just-created state, before the first message |
| 1 | `STAGE_BASIC` | An opening message (`_opening_message()`, sent once, `greeting_sent` flag) explains up front that this is a multi-step, ~15-20 message conversation — prepended to the very first question, no extra round-trip. Then collects `name`, `age`, `location`, `experience`, `contact_phone` one at a time, skipping any the candidate already volunteered |
| 2 | `STAGE_MATERIALS` | One invitation ("send a CV/GitHub/portfolio, or just talk") — nothing is required |
| 3 | `STAGE_INTERVIEW` | **13 fixed questions**, always in this order and count: skills (3), work (3), education (2), **availability/work-stability (4 — see naming note below)**, open_talk (1) |
| 4 | `STAGE_MODEL_EXPLANATION` | **The message actually delivered on the completing turn.** Explains what Talent Live/Connect is, what happens next, **and — critically — the closing/pass-fail line too** (see the architecture note right below; this is not where you'd expect it) |
| 5 | `STAGE_SCORING` | Runs the deterministic scorer (also called early, from Stage 4 — see below), persists results to Supabase, ends |

### ⚠️ Architecture note: why the "closing message" lives in Stage 4, not Stage 5

This isn't how it looks like it should work, so it's worth being explicit.
The graph's edges are `model_explanation → response → (scoring | end)` —
`response` (which composes the actual outgoing text) runs **once**, and
has no edge back into it after `scoring` runs. Combined with
`run_agent()`'s short-circuit (`if stage == STAGE_SCORING and
scoring_completed: return state unchanged`), this means: **once the
interview completes, exactly one more message ever gets composed, and
`scoring` finishing a fraction of a second later doesn't get a second
chance to say anything new.**

So `_closing_addendum()` (in `graph.py`) — the "if we think you're a fit,
we'll contact you" text, or the pass-specific WhatsApp line — is merged
directly into the model explanation, in `model_explanation_stage_node()`,
which calls `apply_score(state)` **early** (before `scoring_stage_node`
would otherwise run) specifically so `score_band` is available in time.
`response_node`'s own `STAGE_SCORING` branch still has a copy of this
logic too, but it's a rare fallback (only reachable if `ai_response`
somehow ended up empty when stage was already 5) — the real path is
Stage 4. If you need to change the closing text, **edit
`model_explanation_stage_node`**, not the Stage 5 branch, or your change
will silently never be sent.

**`PASSED_CANDIDATE_WHATSAPP`** (env var): when set, and only for
candidates who scored `"strong"` (`score_band`, see `scoring.py`), the
closing line invites them to reach out on that WhatsApp number directly —
a concrete next step for a pass, instead of the generic "we'll contact
you" everyone else gets. Verified directly (not just read): ran the
graph through a full mocked interview twice, confirmed the number only
appears when `score_band == "strong"`, and confirmed `_closing_addendum()`
returns the generic text for `"borderline"`, `"weak"`, and unset.

**Naming note on the "family" category**: it's still called `"family"` internally (category key, `family_evidence` field, `CATEGORY_REQUIRED_FIELDS["family"]`) but the questions were reworded away from personal-family topics (father's job, siblings, living arrangement) to professional availability/work-stability topics (weekly availability, other commitments, setup stability, internet/workspace reliability). This was a deliberate word-for-word edit applied identically to **both** `interview.py` and `graph.py`'s duplicate copy (see §6) — if you touch this again, edit both.

**Stage 3 detail** — worth understanding because it's non-obvious from
the code: a "vague" one-word answer (`is_vague_answer()`) does **not**
add extra questions. Whether an answer is vague or not, the next question
asked is the next unused entry in that category's fixed list
(`QUESTION_BANK` in `interview.py`). Vagueness is only recorded
(`vague_probe_categories`) as a signal for scoring — it never changes the
question count or order.

**End-to-end length**: roughly 15–18 candidate messages total
(1–4 for basic info, depending on what they volunteer up front, + 1 for
materials + 13 fixed interview questions).

All three languages (English, Urdu, Roman Urdu) are supported throughout;
language is auto-detected from the candidate's first message
(`detect_language()`) and locked for the rest of the conversation.

---

## 4. State persistence — the part that makes this work at all

`run_agent(state)` (`graph.py`) is **stateless per call**: give it a
complete `AgentState` dict plus a new `state["message"]`, it returns the
updated dict. It keeps nothing in memory between calls, and Telegram
messages arrive as independent events — so something has to persist the
full state between every single message.

That's `agent_sessions` (Supabase table, one row per `phone_number` —
which for Telegram actually holds the **chat ID**, not a real phone
number; see §8 naming gotcha). Every message:

1. `get_agent_session(chat_id)` loads the previous full state (or
   `create_initial_state()` if none exists yet).
2. `state["message"] = <incoming text>`, then `run_agent(state)`.
3. `save_agent_session(chat_id, state, message_id=...)` persists the
   *entire* returned state back as JSON, and records the message ID.

That `last_whatsapp_message_id`/`message_id` field is also the
idempotency guard (`has_processed_message()`) — Telegram/WhatsApp-style
webhooks can redeliver, and even the polling loop could theoretically
double-process on a crash/restart, so nothing runs twice for the same
message ID.

Separately, `graph.py` itself lazily creates rows in `candidates` and
`interviews` the *first* time Stage 3 (interview) is reached — it checks
`state["candidate_id"]`/`state["interview_id"]` first, so it only creates
these once per candidate, using `upsert_candidate(..., on_conflict=
"telegram_chat_id")`.

---

## 5. Scoring (`app/agents/scoring.py`)

Fully deterministic — **no LLM call**, just rule-based text analysis over
everything collected in `state["candidate"]` and `state["interview"]`.

| Component | Max points |
|---|---|
| Hunger | 40 |
| Skill ability | 25 |
| Engagement | 15 |
| Consistency / honesty | 15 |
| Stability | 5 |
| **Base total** | **100** |

Deductions (subtracted from the base):

| Deduction | Points |
|---|---|
| Minor dishonesty | −20 |
| Major dishonesty | −40 |
| Careless / disrespectful | −25 |
| Asked about salary early | −10 |
| Repeated disengagement | −10 |

**Score bands** (`get_score_band()`): `strong` ≥ 80, `borderline` 50–79,
`weak` < 50. **"Passed" = `strong`**, i.e. final score ≥ 80 — that's the
exact filter `get_passed_candidates()` uses for the dashboard.

### 5.1 Critical review — objectivity issues

Requested explicitly during handoff. Two items were fixed directly (the
stability-score bugfix, and the deduction logic — see §5.2). The rest are
**design-level concerns**, deliberately left alone rather than silently
rewritten, since they affect real hiring outcomes:

1. **Almost every sub-score is presence-based, not quality-based.**
   `calculate_hunger_score`, `calculate_skill_score`, and
   `calculate_engagement_score` mostly check "is this list/field
   non-empty?", not "how good/substantive was the answer?". A candidate
   who answers every question with minimal, low-effort text scores
   nearly as well as one who gives genuinely strong answers, as long as
   they technically respond to everything.
2. **Skill scoring rewards keyword matches from a fixed, narrow list**
   (`skill_terms` in `_local_extract_candidate`: sales, marketing,
   coding, python, shopify, etc.) rather than assessing actual
   competency. A candidate whose real skill isn't on that list gets zero
   credit for `skills`, regardless of depth; a candidate who name-drops
   3 listed buzzwords with no substance gets the max (+9).
3. **Consistency/honesty starts at the max (15) and is barely
   deductible** (at most −4, only from vague-answer-probe counts). It
   doesn't verify honesty or cross-check facts at all — the name
   overstates what the mechanism does.
4. ~~**The five deduction flags are structurally dead code.**~~ **Fixed
   — see §5.2.** They used to be read from `state["dishonesty_minor"]`
   etc., which nothing ever set.
5. **Axes double-count the same underlying facts.** `work_evidence` and
   `skills_evidence` each contribute to *both* the hunger score and the
   skill score. `current_job` contributes to *both* hunger and
   stability. The five "independent" score dimensions aren't
   independent — they're correlated by construction.
6. **Several helper functions suggest an abandoned, more rigorous
   design.** `_combined_text()`, `_count_answers()`, and
   `_count_questions()` are all defined but never called by any
   `calculate_*` function — they read like the start of a real text-
   analysis approach that was never finished/wired in.
7. **`total_score = max(1, ...)`** means a candidate who answers nothing
   is still reported as "1/100," not 0 — cosmetic, but slightly
   misleading if anyone reads raw scores.

**Everything else was left alone** because it involves judgment calls with
real consequences — e.g. "should keyword-based skill matching be replaced
with something else" isn't a purely technical decision. Worth a
deliberate follow-up conversation before changing.

### 5.2 Deduction detection (`detect_deduction_flags` in `scoring.py`)

`calculate_deductions()` now computes each flag directly from
conversation evidence instead of reading externally-set state keys that
nothing ever set. Every check is a literal, auditable text match — not a
tone/sentiment judgment — so a triggered flag can always be traced back
to the exact phrase that caused it:

| Flag | Trigger |
|---|---|
| `early_salary_question` | Candidate's own text (answers + `conversation_history` user turns) contains a salary/pay/compensation keyword (English + Roman Urdu + Urdu script), anywhere in the conversation. The bot itself never raises pay, so any mention is candidate-initiated. |
| `careless_disrespectful` | Text contains one of a short, deliberately narrow list of unambiguous insults/profanity (`_DISRESPECT_PHRASES`). Tone/sarcasm is *not* attempted — too unreliable from text alone. |
| `dishonesty_minor` | Candidate claims "never worked"/"no experience" (`_NO_EXPERIENCE_PHRASES`) while `current_job` or `work_history` is also populated in the same conversation — a narrow, objectively-checkable contradiction. |
| `dishonesty_major` | **Never triggers.** No heuristic here was judged reliable enough to responsibly support that level of accusation from keyword matching alone. |
| `repeated_disengagement` | `vague_probe_categories` has 2+ entries — probing already happened more than once and didn't produce a substantive answer either time. |

All five keyword/phrase lists are small module-level constants in
`scoring.py` (`_SALARY_KEYWORDS`, `_DISRESPECT_PHRASES`,
`_NO_EXPERIENCE_PHRASES`) — extend them there if you notice real
conversations using phrasing that should trigger but doesn't (or vice
versa).

---

## 6. ⚠️ Known code-quality issue: duplicated logic in `graph.py`

`app/agents/graph.py` is the single largest file in the project (~5300
lines) and it's large partly because **it duplicates most of
`app/agents/interview.py` inside itself**, then imports from
`interview.py` too:

```python
from app.agents.interview import (
    process_answer, interview_node, generate_next_question,
)
```

...followed, later in the same file, by graph.py's **own** local
`def interview_node(...)` and `def generate_next_question(...)` — which
silently shadow the imported ones for anything called from within
`graph.py`. There's also a second `_local_extract_candidate()` defined
twice in `graph.py` itself (the second one, with an `expected_field`
parameter, is the one actually used).

**Practical consequence for future edits**: if you need to change Stage 1
basic-info logic (extraction, required fields, question text), the *live*
code is in `graph.py` — its own local copies, not `interview.py`. If you
need to change Stage 3 deep-interview logic (question bank, vague-answer
handling, category order), the *live* code is `interview.py`'s
`process_answer()` and friends, which `graph.py` imports unshadowed. When
in doubt, `grep -n "^def <name>"` across both files first — if a name
appears twice, the *later* definition in the file that actually calls it
wins.

This wasn't refactored during this handoff to avoid touching working
interview logic. It's a good candidate for cleanup if anyone has time.

---

## 7. Deployment

**The bot** runs locally via long-polling, started hidden at Windows
logon (`scripts/launch_telegram_bot_hidden.vbs` in the Startup folder +
`scripts/run_telegram_polling_forever.ps1` as a self-restarting
supervisor — see `scripts/setup_telegram_task.ps1` for the Scheduled
Task variant, though Task Scheduler creation was blocked by this
machine's security policy when tried; the Startup-folder `.vbs` is what's
actually in use). Deliberate: polling needs no public URL, so there's
nothing to host for a single-owner bot. Tradeoff: it goes offline
whenever this machine is off or logged out.

**The dashboard** is deployed to Render (`render.yaml`, a "Blueprint") —
local-only was tried first, but coworkers needing easy access without
being on the same machine/network made a real public URL necessary.

### `talent-live-dashboard` (Web Service, `render.yaml`)
- **Start command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Plan: free** — an internal, on-demand tool doesn't need to be
  always-warm. Tradeoff: spins down after ~15 min idle, ~30-50s cold
  start on the next visit. Switch to `starter` in the Render dashboard
  any time if that delay bothers your coworkers.
- Public `*.onrender.com` URL — this is what makes "send a link to a
  coworker" actually work; nothing local-only can do that without also
  handing out your home/office network access.
  Also exposes `/telegram/webhook`, unused in this deployment — harmless.
- Env vars: `DASHBOARD_TOKEN`, `TELEGRAM_BOT_TOKEN` (needed to resolve
  material download links via `getFile` — see §9), `SUPABASE_URL`,
  `SUPABASE_KEY`.
- **Security note**: the dashboard's only protection is `DASHBOARD_TOKEN`,
  checked via either an `Authorization: Bearer <token>` header or a
  `?token=<token>` query param (added for plain-browser access). Anyone
  with the URL + token can read every passed candidate's name, score, and
  phone number. Use a long random value, and treat the full dashboard URL
  (with token) as the thing you're actually sharing with coworkers —
  don't post it somewhere wider than intended.

**Deploy steps**: push to GitHub (already done) → Render dashboard →
**New +** → **Blueprint** → select the repo → Render reads `render.yaml`
and proposes the one service → fill in the 4 secret env vars above
(copied from your local `.env`) → **Apply**. Once live, share
`https://<your-service>.onrender.com/owner/dashboard?token=<DASHBOARD_TOKEN>`
with coworkers directly — that link is the whole access mechanism.

### If the bot ever needs to move off the laptop too
Add a service like this to `render.yaml`:
```yaml
  - type: worker
    name: talent-live-telegram-bot
    runtime: python
    plan: starter   # Background Workers have no free tier
    buildCommand: pip install -r requirements.txt
    startCommand: python -m app.telegram_polling
    envVars:
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_KEY
        sync: false
      - key: GEMINI_API_KEY
        sync: false
      - key: OWNER_CONTACT_PHONE
        sync: false
```
Then stop the local Windows poller (delete the Startup `.vbs` entry) —
two pollers on the same bot token will conflict.

---

## 8. Environment variables reference

| Variable | Used by | Required | Notes |
|---|---|---|---|
| `SUPABASE_URL` | everything | Yes | REST API endpoint |
| `SUPABASE_KEY` | everything | Yes | API key (anon or service role) |
| `SUPABASE_DB_URL` | one-off local scripts only | No | Direct Postgres connection, for running migrations from a terminal (`scripts/run_migration.py`). Use the **Session pooler** URI, not "Direct connection" — the direct host is IPv6-only and fails to resolve on many networks. Never used at app runtime. |
| `TELEGRAM_BOT_TOKEN` | bot (poller + webhook) | Yes | From @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | `app/api/telegram.py` webhook only | No | Only matters if you switch to webhook transport |
| `DASHBOARD_TOKEN` | dashboard | Yes (for dashboard) | Long random string, see §7 security note |
| `OWNER_CONTACT_PHONE` | closing message (actually composed in Stage 4, see §3) | No | If blank, closing message omits the "reach us at..." sentence |
| `PASSED_CANDIDATE_WHATSAPP` | closing message, "strong" scores only | No | If blank, passing candidates get the same generic closing as everyone else |
| `GEMINI_API_KEY` | optional extraction | No | Only used if `USE_GEMINI_EXTRACTION=true` |
| `GEMINI_MODEL` | optional extraction | No | Defaults to `gemini-2.5-flash` |
| `USE_GEMINI_EXTRACTION` | `graph.py` | No | Default `false` — extraction is regex-based by default (see `_local_extract_candidate`) |

---

## 9. Database schema

Migrations live in `supabase/migrations/`, run in numeric order via the
Supabase SQL editor (or `python scripts/run_migration.py <file>` with
`SUPABASE_DB_URL` set):

- **`0000_initial_schema.sql`** — `candidates`, `interviews`,
  `interview_messages`, `interview_scores`, `candidate_materials`.
- **`0001_agent_sessions.sql`** — `agent_sessions` (the full-state
  persistence table, §4).
- **`0002_telegram_transport.sql`** — compatibility shim: renames
  WhatsApp-era column names (`whatsapp_number`, `whatsapp_message_id`,
  etc.) to their Telegram equivalents *if* they're found, for a database
  that ran an older pre-Telegram version of `0000`/`0001`. No-op on a
  fresh install using the current `0000`/`0001` (they already use
  Telegram-native names). Guarded with `if exists ... and not exists`
  checks, safe to run unconditionally.
- **`0003_rls_policies.sql`** — enables Row Level Security on every
  table and adds a `service_role`-only access policy. The app connects
  with `SUPABASE_KEY` (service role), so this doesn't change app
  behavior — it just blocks any hypothetical browser/anon-key client
  from reading candidate data directly.
- **`0004_add_contact_phone.sql`** — adds `candidates.contact_phone`.
- **`0005_rename_material_media_column.sql`** — renames
  `candidate_materials.telegram_media_id` to the transport-agnostic
  `media_file_id` (this was renamed *before* the materials pipeline was
  ever actually wired up — see below — so no data migration risk).

All six have already been applied, in some order, to the live database
this project uses — verified directly via `information_schema.columns`
and `pg_policies` rather than assumed. They're mutually order-independent
(every rename/policy is idempotent and guarded), so running them 0000→0005
against a fresh project reaches the same end state.

Two things worth knowing about this schema:

- **`candidates` only stores a handful of summary columns** (`name`,
  `contact_phone`, `language`, `current_stage`, `status`, `engaged`) —
  the *entire* candidate profile (age, skills, education, family
  answers, everything) lives inside `agent_sessions.state_json`, not as
  queryable columns. If you want to report on/query candidate answers
  directly in SQL, you're querying JSON, not columns.
- **`candidate_materials` is now actually wired up** (it wasn't at first —
  `app/api/telegram.py` used to detect attachment *type* but discard the
  Telegram `file_id` entirely). `parse_update()` now extracts
  `media_file_id`/`mime_type`/`file_name` per attachment type, and
  `process_message()` calls `save_candidate_material()` for it. To make
  this possible, a `candidates` row is now created on the **first**
  message (via `upsert_candidate`), not lazily at Stage 3 — materials can
  arrive as early as Stage 2, before graph.py's own lazy creation would
  otherwise run.
- **Materials shown on the dashboard aren't verified to be a résumé
  specifically.** Stage 2 is one open invitation ("CV, GitHub, portfolio,
  certificates, past work, or anything else") — there's no structural way
  to know which attachment (if any) is actually a résumé. The dashboard's
  "Resume/Materials" column shows *whatever* was attached, labeled by
  filename/type, or "Not submitted" if nothing came through.
- **Material links embed the bot token.** `get_file_url()` (in
  `app/services/telegram.py`) resolves a `file_id` to a real download URL
  via Telegram's `getFile`, which requires embedding
  `TELEGRAM_BOT_TOKEN` directly in the returned URL (Telegram's design,
  not something this code can avoid) — valid for about an hour, resolved
  fresh on every dashboard load. This is fine as long as the dashboard
  stays behind `DASHBOARD_TOKEN` and its links aren't screenshotted/
  shared further, but don't put this link pattern anywhere less trusted.
- **`interview_messages.sender`** is unconstrained free text (currently
  written as `"candidate"`/`"assistant"`) — no enum/check constraint
  exists, tighten it if you want to lock that vocabulary down.
- **Nothing currently reads `interview_messages`.** It's written on
  every turn but `get_interview_messages(interview_id)` in
  `supabase.py` has no caller — there's no UI for viewing a raw
  conversation transcript, only the pass/fail summary dashboard. Would
  be a natural next feature (a per-candidate transcript view).

---

## 10. Known issues / rough edges

- ~~**"/start" as a candidate name**~~ **Fixed.** `_local_extract_candidate`
  (the live copy) now returns immediately for any message starting with
  `/`, before any field extraction runs. This mattered more than it
  sounds like it should: `/start` is the literal text Telegram sends
  when someone taps "Start," so it was the first message of nearly
  every real conversation - it was silently eating the name question
  for essentially everyone, not just an edge case.
- **Duplicated logic in `graph.py`** — see §6.
- **`phone_number` vs `contact_phone`** naming: `state["phone_number"]`
  (and the `candidates.telegram_chat_id`-keyed lookups) actually hold the
  **Telegram chat ID**, inherited from when this was a WhatsApp
  integration and `phone_number` meant an actual phone number. The new
  `contact_phone` field is the real, candidate-provided phone number.
  Don't confuse the two when reading code — `phone_number` is an
  internal chat identifier, `contact_phone` is for actually calling
  someone.
- **No materials file storage** — attachments (CV, portfolio, etc.) are
  acknowledged and their Telegram media ID is recorded, but the actual
  file is never downloaded/stored anywhere. Needs a decision on a
  storage destination (Supabase Storage bucket, S3, etc.) if actual file
  review is wanted.

---

## 11. Quick pointers for common changes

- **Change/add an interview question**: `QUESTION_BANK` in
  `app/agents/interview.py` (all 3 languages, keep parallel).
- **Change scoring weights/deductions**: constants at the top of
  `app/agents/scoring.py`.
- **Change the closing message or model explanation**: `graph.py`,
  `model_explanation_stage_node()` — see §3's architecture note for why
  this is where the closing text actually lives, not Stage 5.
  `_closing_addendum()` is the shared pass/fail logic.
- **Add a new candidate field to collect**: add it to `CandidateState` in
  `state.py`, to `CANDIDATE_FIELDS`/`BASIC_REQUIRED_FIELDS` in
  `graph.py` if it should be asked in Stage 1, add an extraction
  regex/branch, and add a DB column via a new migration if you want it
  queryable outside the JSON blob.
- **Switch back to webhooks instead of polling**: the code already
  exists (`app/api/telegram.py`'s `POST /telegram/webhook`) — just stop
  running `app/telegram_polling.py`, deploy the web service, and call
  Telegram's `setWebhook` pointing at `https://<host>/telegram/webhook`
  with `secret_token=TELEGRAM_WEBHOOK_SECRET`.

---

## 12. Abuse protection / "is this safe from API attacks"

Two concrete protections in `app/api/telegram.py`, both added after
observing the bot re-send its closing message on every single message
received after an interview had already finished:

- **Post-completion silence**: once `state["scoring_completed"]` is
  `True`, the bot replies with a short "already complete" notice exactly
  once, then goes fully silent for that chat — no more Telegram sends, no
  more Supabase writes, regardless of how many further messages arrive.
  Before this fix, every post-completion message re-ran the full
  send/log pipeline (cheap per message, but unbounded and pointless).
- **Per-chat rate limit** (`_is_rate_limited()`): messages from the same
  chat closer together than `MIN_SECONDS_BETWEEN_MESSAGES` (1.5s) are
  dropped before any DB read happens at all — no real person types that
  fast, so this only affects scripted flooding. It's in-memory and
  per-process (resets on restart, doesn't coordinate across multiple
  worker processes) — a flood throttle, not a hard security boundary.

What this deployment does **not** have, and why that's an acceptable
tradeoff at this scale rather than an oversight:
- No CAPTCHA or allowlist — any Telegram user who finds the bot can start
  a conversation. Reasonable for a screening bot meant to be found and
  used; not reasonable if this needs to resist a targeted flood from many
  different chat IDs at once (the rate limit above is per-chat, not
  global).
- `USE_GEMINI_EXTRACTION` defaults to `false`, so even sustained use
  costs Supabase reads/writes (cheap, generous free tier) and Telegram
  API calls (free, Telegram enforces its own send-rate limits as a
  backstop) — not LLM tokens. Turning that flag on changes this
  calculation: at that point, a flood maps directly to Gemini API cost,
  and the per-chat rate limit above is the only thing standing between a
  flood and that cost.
- Supabase queries go through `supabase-py`/PostgREST with typed
  filters, not raw string-built SQL, so standard SQL injection isn't a
  realistic vector here regardless of what a candidate types.
- RLS (`0003_rls_policies.sql`) means even if a browser or anon key ever
  got hold of `SUPABASE_URL`, it couldn't read candidate data without the
  service-role key — only `SUPABASE_KEY` (used server-side) can.
