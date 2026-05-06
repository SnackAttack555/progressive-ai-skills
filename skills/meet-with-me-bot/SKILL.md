---
name: meet-with-me-bot
description: Find meeting requests the user has sent in the last ~30 days that haven't been answered or scheduled, and present them in a live Cowork artifact with paste-ready follow-up notes. Use this skill whenever the user says anything like "check meeting follow-ups," "outstanding meeting requests," "who haven't I heard back from," "who do I need to nudge," "ghosted meetings," "follow-up sweep," "pending meeting requests," or any variant suggesting they want to see who they've invited to meet but who hasn't gotten on the calendar yet. Also runs automatically on a schedule via a scheduled task. Default to triggering on any phrase about checking on, nudging, or following up with people they've tried to schedule with — undertriggering is the bigger risk.
---

# Meet With Me Bot

## What this skill does

On demand (and on whatever schedule you wire up), scan the user's sent mail for meeting requests that are still hanging — emails where they proposed to meet someone but no time was ever locked in and no calendar event exists. Render the result in a Cowork artifact with: the original thread link, age, last activity in the thread, the exact scheduling sentence the user wrote (so they can re-send it), and a "Don't follow up" button that snoozes the request.

The artifact is a *living page* — opening it again any day reflects the most recent scan.

## When to use

Trigger on any phrasing that means "who am I waiting on for a meeting":
- "check meeting follow-ups", "follow-up sweep", "who haven't I heard back from"
- "outstanding meeting requests", "pending meetings", "ghosted meeting requests"
- "who do I need to nudge / poke / chase"
- "did anyone respond to my meeting requests"
- bare references like "meeting follow-ups" or "ping the people I'm waiting on"

Also runs from a scheduled task. The scheduled task's prompt just invokes this skill.

## Configuration — customize before first run

Edit these four constants in this section before installing:

```yaml
# Required: your primary email address (used to identify "from" in sent mail).
USER_EMAIL: "you@example.com"

# Required: domains to treat as internal (skip emails to colleagues).
# Anyone at these domains is considered a teammate, not an external networking target.
INTERNAL_DOMAINS:
  - "yourcompany.com"

# Required: absolute path to the snooze JSON file.
# Pick a stable, writable location accessible from your scheduled-task environment.
# Recommend: a folder you keep persistent state files in for other Cowork tools.
SNOOZE_FILE_PATH: "/Users/you/Documents/meet-with-me-bot/snooze.json"

# Optional: lookback window for sent mail. Default 30 days is a good starting point.
LOOKBACK_DAYS: 30

# Optional: how long a snooze persists. After this many days from the original
# meeting-request date, the snooze auto-expires and the recipient resurfaces.
# Prevents permanent suppression — if you re-engage 6 months later, that's a fresh request.
SNOOZE_TTL_DAYS: 60
```

**Also update** the same `SNOOZE_FILE_PATH` in:
- `scripts/manage_snooze.py` (the `DEFAULT_SNOOZE_PATH` constant near the top)
- `assets/artifact_template.html` (the `SNOOZE_FILE_PATH` JS constant)

Both writers must point at the same file.

## The workflow

### Step 1: Load and prune the snooze list

Run the helper script. It auto-prunes entries whose original request date is more than `SNOOZE_TTL_DAYS` ago, writes the cleaned file back, and prints the active entries as JSON.

```bash
python3 "${SKILL_DIR}/scripts/manage_snooze.py" list
```

Output:
```json
{"snoozed": [{"email": "alice@example.com", "request_date": "2026-04-12", "thread_id": "189f2..."}]}
```

Hold onto this list — you'll filter candidates against it at Step 7.

### Step 2: Pull sent mail from the last LOOKBACK_DAYS days

Use the Gmail MCP to search the user's sent mail. Roughly:

```
from:USER_EMAIL in:sent newer_than:30d
```

(Substitute `LOOKBACK_DAYS` for `30d` if you've changed it.)

You want the *threads*, not just individual messages, because deciding whether a request is still hanging requires reading the whole conversation.

**Paginate fully.** Gmail returns up to 50 threads per page. Loop on `nextPageToken` until exhausted.

**Watch result-size limits.** Large responses may be saved to disk by the tool runner. When that happens, parse from disk with `jq` or Python rather than pulling all of it into context.

### Step 3: Identify which threads are meeting requests

For each sent thread, decide: is the original outbound message proposing a meeting? Look for clear scheduling intent — phrases like "let's set up time," "would love to chat," "happy to find time," "here's my calendar link," "are you free," "can we grab coffee/a call," presence of a scheduling URL (Google Calendar appointment links, Calendly, Cal.com, etc.), or any explicit time proposal.

Skip threads that:
- Are responses to inbound meeting requests (the user isn't the proposer)
- Are about something else and only mention "meeting" tangentially
- Are sent to internal domains (see `INTERNAL_DOMAINS`)
- Are auto-replies, mailing list messages, or bulk sends
- **Are bulk-template intro emails inviting many people to a recurring group call.** Tell-tale signs: the same template body sent to many different recipients in the same hour, language inviting recipients to a recurring/group call. These aren't 1:1 meeting requests.

When in doubt, *include* the thread for deeper analysis — false positives are easier to dismiss than false negatives are to recover. But be deliberate. Don't surface a thread you don't believe is a real meeting request.

**Strip quoted reply chains when reading thread bodies.** Each message's `plaintextBody` typically contains the new content followed by the entire quoted history (every prior message indented with `>`). For classification, only the NEW content of each message matters. A simple heuristic: drop everything after the first occurrence of `^On [A-Z][a-z]{2,8} \d+, \d{4}` or `^----- ?Forwarded message ?-----` or `^On .+ wrote:` per message. Otherwise you'll burn tokens re-reading the same quoted text many times.

### Step 4: For each candidate, decide if it's already handled

A thread is "handled" if **any** of the following is true:

1. **Calendar event exists** with that person (or anyone from their email domain) after the date of the original request, AND that event is not part of a recurring weekly or monthly series. Use the Calendar MCP to search by attendee email or domain. Recurring exclusion matters because "we already meet weekly" doesn't mean "we resolved this specific ask."

2. **Email reply with concrete resolution**: the recipient replied with a confirmed time, an explicit decline ("can't this quarter, sorry"), a redirect ("talk to my colleague Jamie instead"), or a calendar invite acceptance. A reply that just says "let me check my calendar and circle back" is NOT resolution — that's still in flight.

3. **Domain match on calendar**: a non-recurring event with someone else from the same email domain after the request, in a context that plausibly covers the ask (i.e., meeting with their colleague is effectively the same outcome).

If a thread is handled by any of these, drop it.

### Step 5a: Identify the principal and scheduler

For each remaining thread, figure out who the **principal** is (the person the user is trying to meet with) and whether there's a **scheduler** (someone who handles timing on the principal's behalf).

Default: **principal = recipient of the user's first meeting-proposal email in the thread**. Scheduler = none.

Look for explicit scheduler hand-offs in the thread. Common patterns from the principal:
- "My colleague <Name> will consult your schedule and find us a time"
- "I'm adding my colleague <Name> to help with scheduling"
- "Cc'ing <Name> who handles my calendar / schedule"
- "+<Name> for scheduling"
- "<Name> will reach out to coordinate"

When a pattern like this appears in a reply from the principal, the **named colleague becomes the scheduler**. The principal stays the principal — even when the user's subsequent emails go to the scheduler instead.

If the principal's domain matches the scheduler's domain (most common case), treat the scheduler as legitimate. If they don't match, still use the named hand-off but flag the unusual structure.

### Step 5b: Extract the scheduling sentence

Pull the sentence (or two) the user wrote to offer times. Use the **most recent** such sentence in the thread, not necessarily the first — if the user already nudged or sent a refined ask (e.g., "Wednesday June 10th 3pm Oakland?"), that's the relevant offer to mirror.

Look for:
- The sentence containing the scheduling link, or
- The sentence proposing specific times, or
- The sentence inviting them to suggest a time

Quote it verbatim — the user wants to recycle their exact words, including whichever scheduling link they used (e.g., a 30-min vs 60-min Calendly URL). Don't rephrase.

### Step 6: Build the follow-up note

Format: a short, friendly 1-2 sentence paste-ready follow-up. Template:

> Hi [first name] — wanted to bubble this back up in case it got buried. [Most recent scheduling sentence, verbatim.]

The "[first name]" is whoever the user should *write to next*: if there's a scheduler, that's the scheduler. If not, that's the principal. The note's salutation reflects who'll receive it.

Keep it warm, not pushy. Vary the opener slightly thread-to-thread (e.g., "wanted to gently bump this," "circling back in case my last note got lost," "no worries if the timing's off — happy to revisit").

### Step 7: Apply the staleness gate, then filter against the snooze list

**24-hour staleness gate.** Drop any candidate where the user's most recent meeting-relevant action in the thread is less than 24 hours old. "Meeting-relevant action" = a sent message that proposes a meeting, sends a scheduling link, asks about a specific time, or nudges the recipient/scheduler. The point: don't surface a request when the recipient hasn't realistically had time to respond yet. Tomorrow's run will catch it.

**Snooze filter.** Drop any candidate where `(principal_email, original_request_date)` matches an entry in the snooze list from Step 1. The snooze key uses the *principal's* email (not the scheduler's) so re-engaging via a different scheduler later doesn't get suppressed.

### Step 8: Compute metadata for each remaining item

For the artifact, you need per-item:
- `principal_name`: best-effort name from the To: header on the user's first message, signature in their reply, or the body of the intro
- `principal_email`: the principal's email
- `scheduler_name`: optional — if a scheduler was identified in Step 5a, their name
- `scheduler_email`: optional — if a scheduler was identified, their email
- `original_request_date`: ISO date of the user's *first* meeting-proposal in the thread
- `last_action_date`: ISO date of the user's *most recent* meeting-relevant action
- `age_days`: integer days from `original_request_date` to today
- `last_activity`: `{date: "YYYY-MM-DD", sender: "Name or email"}` — most recent message in the thread, regardless of who sent it
- `thread_url`: `https://mail.google.com/mail/u/0/#inbox/{thread_id}`
- `original_sentence`: verbatim *most-recent* scheduling sentence
- `followup_note`: the constructed 1-2 sentence paste-ready note, addressed to whoever the user should write next
- `thread_id`: Gmail thread ID

### Step 9: Render the artifact

Read the template at `${SKILL_DIR}/assets/artifact_template.html`. Replace:
- `__DATA_PLACEHOLDER__` → JSON-stringified array of the items from Step 8
- `__SCAN_TIMESTAMP_PLACEHOLDER__` → ISO 8601 timestamp of this scan

The snooze write logic is inlined in the template — no script path needs to be substituted. The artifact's "Don't follow up" button calls `mcp__workspace__bash` with a self-contained Python that writes to the snooze file directly.

Write the rendered HTML to a file in the outputs directory, then call `create_artifact` (or `update_artifact` if one already exists with id `meet-with-me-bot`).

```
artifact id: meet-with-me-bot
mcp_tools: ["mcp__workspace__bash"]
```

If `list_artifacts` shows an existing `meet-with-me-bot` artifact, use `update_artifact` with a 1-line summary of what changed (e.g., "3 outstanding requests, 1 newly added, 1 resolved since last run").

### Step 10: Summarize in chat

Write a short chat reply: total count, oldest waiting, link to the artifact. Don't dump the full table in chat — that's what the artifact is for.

## Edge cases and gotchas

- **No outstanding requests**: still update/create the artifact with an empty state ("Inbox zero on follow-ups"). Keeps the artifact authoritative.
- **Thread with multiple recipients**: count it once, primary recipient = first To:.
- **Recently followed up**: covered by Step 7's 24-hour gate.
- **Recurring detection**: an event with `RRULE:FREQ=WEEKLY`, `FREQ=MONTHLY`, or `FREQ=DAILY` is recurring → doesn't count as handling the specific ask. One-off events do.
- **Domain match scope**: "after the request date" means event start time is later than the original email's date. Don't count events that predate the email.
- **Multi-thread campaigns**: if the user emailed the same person twice with two separate proposals, treat each thread independently. The snooze key is `(principal_email, original_request_date)`, so snoozing one doesn't suppress the other.
- **No clean scheduling sentence**: if you genuinely can't extract one, surface the item anyway with `original_sentence: null` and a generic fallback follow-up note.
- **Recipient booked the slot but never replied to the email**: real and common (someone clicks the Calendly link without sending an email reply). The calendar check catches these — Step 4 is calendar-first rather than email-reply-first.
- **Verbal agreement without a calendar invite**: if the thread reaches "let's meet at lunch on the 13th" but no calendar event exists yet, treat as handled per the spec ("agreed on a time").
- **Snooze file unreachable at runtime**: if the snooze file's parent folder isn't accessible (folder not connected to the Cowork session, permissions issue), `manage_snooze.py list` will return an empty list and the run will proceed without filtering. That's a graceful degradation — at worst a snoozed item resurfaces.

## How the snooze works

Two cooperating writers share the snooze file (read each other's output cleanly):

1. **Artifact "Don't follow up" button**: calls `mcp__workspace__bash` with a small inline Python (embedded in the template) that opens the snooze JSON, dedups by `(email, request_date)`, appends the new entry, and writes back. Self-contained — no path to a separate script needed.

2. **`manage_snooze.py` helper** (in `scripts/`): used by the skill itself to load the active list at the start of each run, with automatic TTL pruning baked in.

Both write the same JSON shape, so they coexist fine. Entries expire `SNOOZE_TTL_DAYS` after `request_date` so re-engagement months later isn't auto-suppressed.

## Why this design

- **Live artifact instead of one-shot output**: a persistent page the user can keep open or re-find, refreshed on each scan.
- **Verbatim scheduling sentence**: re-quoting the user's own words preserves whichever scheduling link they used (no need to detect 30-min vs 60-min variants).
- **Domain-level handled detection**: meeting people at an org often happens through whoever's available — "I met with their COO instead" is a real outcome, not a failure.
- **TTL on snoozes**: prevents permanent suppression. If the relationship cycles back later, that new request is its own thing.
