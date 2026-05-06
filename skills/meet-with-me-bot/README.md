# meet-with-me-bot

**Category:** Operations

**What it does:** Surfaces meeting requests you've sent that haven't been answered or scheduled, in a refreshable Cowork artifact with paste-ready follow-up notes.

## Who this is for

Anyone whose job involves a lot of "would love to find time to chat" outreach — campaign and movement work, fundraising, coalition-building, sales, hiring. The kind of person who sends a dozen scheduling-link emails a week and can't reliably remember which ones got responses.

## What it does, in detail

On demand and on a recurring schedule (Mondays and Thursdays at 10am works well), it scans your sent mail for the last 30 days, finds emails where you proposed a meeting, and decides for each one whether the meeting actually got booked. The check uses two signals:

- **Calendar event with that person, or anyone at their org.** If you have a non-recurring event on the calendar after the date of your request, the meeting is handled.
- **Email reply with a clear answer.** A confirmed time, a decline, or a redirect to a colleague. A vague "let me check and get back to you" doesn't count — that's still in flight.

What's left is the list of meetings that genuinely fell through. The skill renders them in a Cowork artifact with:

- The recipient's name, plus a separate scheduler line if they handed off to one (e.g. "Mike Berkowitz, scheduling via Jade Neal")
- How long it's been waiting and how long since you last reached out
- A link to the Gmail thread
- The verbatim sentence you used to offer times — so the follow-up uses your own scheduling link and your own voice
- A 1–2 sentence paste-ready follow-up
- A "Don't follow up" button that snoozes the entry for 60 days

## Folder structure

This skill ships as a folder, not just a `SKILL.md` file. The full structure:

```
meet-with-me-bot/
  SKILL.md                          # Skill instructions for Claude
  README.md                         # This file
  scripts/
    manage_snooze.py                # Reads, writes, and prunes the snooze JSON
  assets/
    artifact_template.html          # The HTML template for the Cowork artifact
```

**Keep the four parts together.** `SKILL.md` references `scripts/manage_snooze.py` and `assets/artifact_template.html` by relative path. If you separate them, the skill won't run.

## Install

### Cowork (Claude desktop app)

The Cowork install flow expects a single `.skill` zip file, not a loose folder.

1. Zip the entire `meet-with-me-bot/` folder (including `scripts/` and `assets/`):
   ```
   cd /path/to/meet-with-me-bot/..
   zip -r meet-with-me-bot.skill meet-with-me-bot/
   ```
2. In Cowork: click **Customize** in the left sidebar → click **+** → open the **Skills** tab → upload the `meet-with-me-bot.skill` file you just created.
3. New conversations pick it up immediately — no restart needed.

After install, Cowork stores the skill internally; you don't need to know the exact path. But if you ever want to inspect or edit the installed copy, look under your Claude application support directory for a `skills/` folder.

### Claude Code (CLI)

Claude Code reads skills directly from disk. Place the **whole folder** (with its `scripts/` and `assets/` subdirectories intact) at one of these locations:

**User scope** (available across all projects):
```
~/.claude/skills/meet-with-me-bot/
```

So after install you should see:
```
~/.claude/skills/meet-with-me-bot/SKILL.md
~/.claude/skills/meet-with-me-bot/README.md
~/.claude/skills/meet-with-me-bot/scripts/manage_snooze.py
~/.claude/skills/meet-with-me-bot/assets/artifact_template.html
```

**Project scope** (only available inside one project):
```
.claude/skills/meet-with-me-bot/
```

End your current Claude Code session and start a new one to load the skill.

## Configure before first run

Three places hold user-specific values. Edit all three to match your setup:

1. **`SKILL.md`** — the YAML config block at the top of the body. Set `USER_EMAIL`, `INTERNAL_DOMAINS` (the email domains of your own org and anyone you treat as a colleague rather than an external networking target), and `SNOOZE_FILE_PATH` (where the JSON snooze list lives — pick a path that's stable and writable from your scheduled-task environment).
2. **`scripts/manage_snooze.py`** — update the `DEFAULT_SNOOZE_PATH` constant to match `SNOOZE_FILE_PATH`.
3. **`assets/artifact_template.html`** — update the `SNOOZE_FILE_PATH` JS constant to match.

All three references must point at the same file. The skill reads from it, the artifact's "Don't follow up" button writes to it.

## Required tools / MCPs

- **Gmail MCP** — for `search_threads` and `get_thread`
- **Google Calendar MCP** — for `list_events`
- **Cowork artifact tools** — `create_artifact`, `update_artifact`, `list_artifacts`
- **`mcp__workspace__bash`** — used by the artifact's "Don't follow up" button to write the snooze file

If you're not on Gmail or Google Calendar, you can swap the search calls in `SKILL.md` Step 2 and Step 4 for your provider's equivalents.

## Schedule (recommended)

Twice a week, weekday morning. Cron: `0 10 * * 1,4` (Monday and Thursday, 10am local). Scheduled-task prompt:

> Run the meet-with-me-bot skill.

The skill description handles the rest.

## Trigger phrases (on-demand)

Say any of these to invoke without waiting for the schedule:

- "check meeting follow-ups"
- "outstanding meeting requests"
- "who haven't I heard back from"
- "ghosted meetings"
- "follow-up sweep"
- "who do I need to nudge"

## How the snooze works

Two writers share the snooze file (they read each other's output cleanly):

- **The artifact's "Don't follow up" button** writes a new entry via inline Python (no separate script call needed).
- **`scripts/manage_snooze.py`** reads the file at the start of each scheduled run, with auto-pruning of entries older than 60 days.

The snooze key is `(principal_email, original_request_date)`. So if you re-engage someone six months later with a fresh ask, that new request gets a different `original_request_date` and surfaces normally — the snooze doesn't permanently bury anyone.

`snooze.json` shape on disk:

```json
{
  "snoozed": [
    {
      "email": "principal@example.com",
      "request_date": "2026-04-21",
      "thread_id": "abc123",
      "snoozed_at": "2026-05-05"
    }
  ]
}
```

## Limitations

- **Verbal-yes-without-a-calendar-invite is treated as handled.** If a thread reaches "let's grab lunch on the 13th" but you never sent a calendar invite, the skill won't surface it as outstanding. That's the design — but if you want a separate "verbal yes, no invite yet" view, extend Step 4.
- **Bulk-template intro emails sometimes leak through.** The skill tries to skip mass-send "I'd like to invite you to a recurring funder roundtable" templates, but if your template language doesn't match the heuristics, you'll get false positives. Tighten the filter in Step 3.
- **Non-Gmail / non-Google Calendar isn't supported out of the box.** Replace the MCP calls with your provider's equivalents.
- **The principal/scheduler detection is heuristic.** It looks for hand-off phrases like "my colleague <Name> will consult your schedule." Unusual phrasings may be missed.

## Troubleshooting

**"Inbox zero on follow-ups" but you know there are pending requests.**
Two likely causes: the recent ones are inside the 24-hour staleness window (they'll surface tomorrow), or the skill thinks they're handled because you have a calendar event with them or someone at their org. Run the skill on demand and ask Claude to explain why a specific thread isn't surfaced.

**Items keep reappearing after I click "Don't follow up."**
The snooze write may be failing silently. Check that the path in `SNOOZE_FILE_PATH` is reachable from the Cowork session at click-time. If the folder isn't connected/mounted, the bash call won't be able to write.

**Artifact says it needs `mcp__workspace__bash` but the button does nothing.**
Make sure `mcp__workspace__bash` is in the `mcp_tools` list when you call `create_artifact` / `update_artifact`. The skill specifies this; if you've forked, double-check.

## License

MIT (matches the parent repo). Use, modify, and share — attribution appreciated but not required.
