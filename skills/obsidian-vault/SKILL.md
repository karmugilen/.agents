---
name: obsidian-vault
description: Search, create, and manage notes in the Obsidian vault (a.k.a. the user's "second brain") with wikilinks and a self-maintaining dashboard. Use when the user wants to find, create, update, or organize notes in Obsidian or refers to their "second brain".
---

# Obsidian Mind Palace (Ultra-Lean)

## Core Philosophy: Stable Atomic Knowledge
A portable, near-zero-dependency cognitive instrument. All logic lives in `palace.py`. Optional auto-refresh uses `inotifywait` + systemd; no AI calls anywhere.

## Vault Location
`/home/kar/secondBrain/obsidian-vault/`

**Alias:** the user calls this vault their **"second brain"**. Any request to "add to my second brain", "update second brain", "save to second brain", etc. → operate on this vault via `palace.py` (create / read / link / refresh). Works from any working directory because the path is absolute.

## Palace CLI (The Engine)
Every command refreshes `Home.md` (the Foyer) as a side effect.

```bash
# Discovery — ranked by (updated, mtime, recall_count) DESC. Matches by content OR title.
python3 .agents/skills/obsidian-vault/palace.py search "keyword"

# Observation — increments recall_count, updates timestamp, appends to .palace_history.
# Accepts full path, vault-relative, or bare filename (±.md). Refuses meta files.
python3 .agents/skills/obsidian-vault/palace.py read Vault_Manifest

# Crystallization — creates a new note from the standard template, logs to history.
python3 .agents/skills/obsidian-vault/palace.py create "New Note Title"

# Manual linking / ignoring (usually driven by Home.md Discovery checkboxes).
# IMPORTANT: `link` requires a note named "<keyword>.md" (case-insensitive) to
# exist — otherwise it refuses, to prevent creating broken wikilinks. It also
# skips text inside code, existing wikilinks, markdown links [text](url), and
# ATX headings (#, ##, …). Always run `create` first if you want a new hub.
python3 .agents/skills/obsidian-vault/palace.py link "keyword"
python3 .agents/skills/obsidian-vault/palace.py ignore "keyword"

# Regenerate Home.md and process pending Discovery checkboxes.
python3 .agents/skills/obsidian-vault/palace.py refresh

# Daemon: watch the vault and refresh on every save (debounce 1.0s).
python3 .agents/skills/obsidian-vault/palace.py watch
```

## Auto-Refresh (Offline, No AI)
A systemd `--user` service runs `palace.py watch` continuously, so `Home.md` stays current even when the agent isn't active.

- Unit: `~/.config/systemd/user/palace-watch.service`
- Loop: `inotifywait` on the vault → debounced refresh.
- Survives logout via `loginctl enable-linger`.
- Excludes `.obsidian/`, `.trash/`, `.palace_history`, swap files. **`Home.md` IS monitored** so user edits in the ✅ TODO section round-trip to source notes; `refresh_dashboard()` short-circuits writes when output is unchanged so the watcher doesn't self-loop.

Useful commands:
```bash
systemctl --user status palace-watch      # health
journalctl --user -u palace-watch -f      # live log
systemctl --user restart palace-watch     # after editing palace.py
systemctl --user disable --now palace-watch
```

## Metadata (Recall Engine)
`palace create` writes this header. `read` bumps `updated` and `recall_count`.
```yaml
---
updated: YYYY-MM-DD-HH:MM
recall_count: 0
type: permanent
status: seedling
tags: []
# Optional, all surfaced on Home.md when present:
aliases: [Alt Name, AN]
---
```

## Navigation (The Foyer / `Home.md`)
`Home.md` is a **Dynamic Hot Cache** — regenerated on every CLI call and on every vault save (via the watcher). Read it at the start of every session to absorb active context without grepping the vault.

Sections (all code-derived, hard-capped to keep token cost predictable):

| Section | Source | Cap |
|---|---|---|
| 📊 **Pulse** | counts + frontmatter + `.palace_history` | 3 lines (Notes/Density/Orphans · Today/Streak · Status/Tags) |
| 🧭 **Breadcrumbs** | `.palace_history` | last 5 reads |
| ✅ **TODO** | open `- [ ]` lines across the vault (interactive — see below) | 7 |
| 🔥 **Hot** | `updated:` | 7 |
| ❓ **Open Questions** | regex: body lines ending in `?` | 5 |
| 🔗 **Linking Opportunities** | unlinked title mentions | 5 |
| 🏷️ **Discovery** | common ≥6-letter words; Add/Ignore checkboxes | 7 |
| 🌟 **Top Hubs** | incoming wikilink count (existing notes only) | 3 |
| 💎 **Core** | `recall_count` | 7 |
| 🧊 **Stagnant Core** | high recall, not in freshest 5 | 5 |
| 🎲 **Rediscover** | lowest recall + oldest update | 1 |
| 🏚️ **Orphans** | zero incoming wikilinks | 7 |
| 🩺 **Maintenance** | broken links · stale frontmatter · alias index | inline |

Discovery checkboxes: tick `[x]` under **Add** to wikilink a keyword vault-wide; tick **Ignore** to append it to `dontadd.md`. Boxes are processed on the next refresh.

### ✅ TODO is interactive
The TODO section round-trips between Home and source notes:

| User action on Home | Engine behaviour |
| :-- | :-- |
| Type `- [ ] foo` (no suffix) | Appended to `TODO.md` |
| Type `- [ ] foo — [[Note]]` | Appended to `Note.md` (must exist; falls back to `TODO.md` otherwise) |
| Tick `- [x]` on any TODO line | Source line flipped to `[x]`, then stripped and appended to `Completed.md` under a `## YYYY-MM-DD HH:MM` block |
| Type `- [x] foo` in one step | Lands directly in `Completed.md` |

The line-level archive (`process_completed_todos`) runs on every refresh and scans **all** notes — ticking `- [x]` directly in any source note (e.g. inside `Paper.md` while reading it) also auto-archives within ~1s via the watcher.

## Files
- `palace.py` — engine
- `SKILL.md` — this file
- `.palace_history` — append-only event log (alongside `palace.py`)
- `obsidian-vault/Home.md` — generated dashboard. Hand-editing is allowed only in the ✅ TODO section and the Discovery checkbox table; everything else is rewritten on each refresh.
- `obsidian-vault/TODO.md` — canonical home for unattributed tasks.
- `obsidian-vault/Completed.md` — auto-archive of ticked tasks (do not hand-edit; entries are append-only with timestamps).
- `obsidian-vault/dontadd.md` — Discovery exclusion list

## Agent Execution Loop
1. **Discovery**: read `Home.md`, then `palace.py search` if needed.
2. **Observation**: `palace.py read <note>` — never `cat` / `read_file` directly (skips recall counting + history).
3. **Crystallization**: `palace.py create`.
4. **Action tracking**: surface follow-ups as `- [ ]` lines (in `TODO.md`, the source note, or directly on Home). Tick `[x]` to archive — no manual move needed.
