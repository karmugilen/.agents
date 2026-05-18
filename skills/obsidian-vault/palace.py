import sys
import os
import re
import subprocess
from datetime import datetime
from collections import Counter

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VAULT = os.path.abspath(os.path.join(SCRIPT_DIR, "../../../obsidian-vault/"))
VAULT_PATH = os.getenv("PALACE_VAULT", DEFAULT_VAULT)

if not os.path.exists(VAULT_PATH):
    VAULT_PATH = os.path.abspath("obsidian-vault/")

DONT_ADD_PATH = os.path.join(VAULT_PATH, "dontadd.md")
HOME_PATH = os.path.join(VAULT_PATH, "Home.md")
COMPLETED_PATH = os.path.join(VAULT_PATH, "Completed.md")
HISTORY_PATH = os.path.join(SCRIPT_DIR, ".palace_history")

# Files that live in the vault but are not knowledge notes.
META_FILES = {"Home.md", "dontadd.md", "Completed.md"}

# Caps for dashboard sections.
CAP_HOT = 7
CAP_CORE = 7
CAP_ORPHANS = 7
CAP_DISCOVERY = 7
CAP_QUESTIONS = 5
CAP_BROKEN = 5
CAP_HUBS = 3
CAP_BREADCRUMBS = 5
CAP_TODO = 7

TEMPLATE = """---
updated: {{updated}}
recall_count: 0
type: permanent
status: seedling
tags: []
---
# {{title}}

Enter atomic knowledge here.
"""

# --- CORE LOGIC ---
def parse_metadata(content):
    match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match: return {}
    metadata = {}
    for line in match.group(1).split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            metadata[key.strip()] = val.strip()
    return metadata

def update_metadata(content, updates):
    current_meta = parse_metadata(content)
    current_meta.update(updates)
    meta_lines = ["---"]
    for k, v in current_meta.items():
        meta_lines.append(f"{k}: {v}")
    meta_lines.append("---")
    new_meta_str = "\n".join(meta_lines)
    header, body = split_note(content)
    if header:
        return new_meta_str + "\n" + body
    return new_meta_str + "\n\n" + content

def split_note(content):
    """Safely split note into frontmatter and body."""
    match = re.search(r'^---\s*\n.*?\n---\s*\n', content, re.DOTALL)
    if match:
        header = match.group(0)
        body = content[match.end():]
        return header, body
    return "", content

def get_dont_add():
    if not os.path.exists(DONT_ADD_PATH): return set()
    with open(DONT_ADD_PATH, 'r') as f:
        return {line.strip().lower() for line in f if line.strip()}

def add_to_dont_add(keyword):
    keywords = get_dont_add()
    if keyword.lower() not in keywords:
        with open(DONT_ADD_PATH, 'a') as f:
            f.write(f"{keyword.lower()}\n")

def _create_note(title):
    """Create a vault note from TEMPLATE. Returns the path, or None if it already exists."""
    slug = title.replace(" ", "_")
    file_path = os.path.join(VAULT_PATH, slug + ".md")
    if os.path.exists(file_path):
        return None
    updated = datetime.now().strftime("%Y-%m-%d-%H:%M")
    content = TEMPLATE.replace("{{title}}", title).replace("{{updated}}", updated)
    with open(file_path, 'w') as f: f.write(content)
    record_event('create', slug)
    return file_path

_DONE_TASK_RE = re.compile(r'^(\s*)([-*])\s*\[[xX]\]\s+(.+?)\s*$')

# Matches a line in Home's ✅ TODO section. Captures: state ([ ] or [x]),
# task text, and optional `— [[Source]]` attribution suffix.
_HOME_TODO_LINE = re.compile(
    r'^- \[([ xX])\]\s+(.+?)(?:\s+—\s+\[\[([^\]]+)\]\])?\s*$'
)

def process_home_todos():
    """Sync user edits in Home's ✅ TODO section back to source notes.

    - User-typed `- [ ]` line (no matching open task in source) → appended to TODO.md.
    - User-ticked `- [x]` line → matching `- [ ]` line in source flipped to `- [x]`,
      which process_completed_todos then archives on the same refresh.

    This is what makes Home feel interactive even though it's regenerated."""
    if not os.path.exists(HOME_PATH): return
    with open(HOME_PATH, 'r') as f:
        home = f.read()
    section_match = re.search(r'### ✅ TODO\n(.*?)(?:\n---|\Z)', home, re.DOTALL)
    if not section_match: return
    for line in section_match.group(1).splitlines():
        m = _HOME_TODO_LINE.match(line)
        if not m: continue
        state, task, source = m.group(1), m.group(2).strip(), m.group(3)
        if not task: continue
        source = source.strip() if source else "TODO"
        ticked = state.lower() == 'x'
        src_path = os.path.join(VAULT_PATH, source + ".md")
        if not os.path.isfile(src_path):
            src_path = os.path.join(VAULT_PATH, "TODO.md")
        _sync_home_task(src_path, task, ticked)

def _sync_home_task(src_path, task, ticked):
    """Reconcile a single Home TODO line with its source file."""
    if not os.path.exists(src_path):
        # TODO.md doesn't exist yet — create it with frontmatter.
        updated = datetime.now().strftime("%Y-%m-%d-%H:%M")
        with open(src_path, 'w') as f:
            f.write(
                f"---\nupdated: {updated}\nrecall_count: 0\n"
                "type: permanent\nstatus: active\ntags: [meta]\n---\n# TODO\n\n"
            )
    with open(src_path, 'r') as f:
        content = f.read()
    open_line = f"- [ ] {task}"
    done_line = f"- [x] {task}"
    if ticked:
        if done_line in content: return  # already ticked
        if open_line in content:
            with open(src_path, 'w') as f:
                f.write(content.replace(open_line, done_line, 1))
        else:
            # Brand-new task the user ticked on Home in one step.
            with open(src_path, 'a') as f:
                if not content.endswith('\n'): f.write('\n')
                f.write(done_line + '\n')
    else:
        if open_line in content or done_line in content: return
        with open(src_path, 'a') as f:
            if not content.endswith('\n'): f.write('\n')
            f.write(open_line + '\n')

def process_completed_todos():
    """Strip ticked `- [x]` lines from every source note and append them to
    Completed.md. Runs every refresh, so the watcher archives within ~1s of
    ticking a task in Obsidian. Source attribution is preserved via the same
    `— [[Source]]` convention used on Home."""
    archived = []  # list of (source_title, task_text)
    for f_name in sorted(os.listdir(VAULT_PATH)):
        if not f_name.endswith(".md") or f_name in META_FILES:
            continue
        path = os.path.join(VAULT_PATH, f_name)
        try:
            with open(path, 'r') as f:
                lines = f.readlines()
        except: continue
        kept = []
        changed = False
        for line in lines:
            m = _DONE_TASK_RE.match(line.rstrip('\n'))
            if m:
                archived.append((f_name[:-3], m.group(3).strip()))
                changed = True
            else:
                kept.append(line)
        if changed:
            with open(path, 'w') as f:
                f.writelines(kept)
    if archived:
        _append_completed(archived)

def _append_completed(items):
    ts_section = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_file = not os.path.exists(COMPLETED_PATH)
    with open(COMPLETED_PATH, 'a') as f:
        if new_file:
            updated = datetime.now().strftime("%Y-%m-%d-%H:%M")
            f.write(
                f"---\nupdated: {updated}\nrecall_count: 0\n"
                "type: permanent\nstatus: evergreen\ntags: [meta]\n---\n"
                "# Completed\n\n"
                "Auto-archive of ticked `- [x]` tasks from across the vault.\n"
                "Newest entries at the bottom.\n\n"
            )
        f.write(f"## {ts_section}\n")
        for source, task in items:
            suffix = "" if source == "TODO" else f" — [[{source}]]"
            f.write(f"- [x] {task}{suffix}\n")
        f.write("\n")

def process_home_checkboxes():
    if not os.path.exists(HOME_PATH): return
    with open(HOME_PATH, 'r') as f: content = f.read()
    matches = re.findall(r'^\|\s*\[([ xX])\]\s*\|\s*\[([ xX])\]\s*\|\s*([^|]+?)\s*\|', content, re.MULTILINE)
    for add_check, ignore_check, keyword in matches:
        keyword = keyword.strip()
        add = add_check.lower() == 'x'
        ignore = ignore_check.lower() == 'x'
        if ignore:
            add_to_dont_add(keyword)
        elif add:
            # Auto-create a stub hub if the target note doesn't exist yet.
            # This makes the Discovery "Add" checkbox a one-step promote-to-hub.
            # Discovery keywords are always lowercase — Title-Case the stub so
            # the new hub matches vault convention (Entropy, Steganography…).
            if not _resolve_note_filename(keyword):
                _create_note(keyword[:1].upper() + keyword[1:])
            palace_link(keyword, refresh=False)

def record_event(action, title):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with open(HISTORY_PATH, 'a') as f:
            f.write(f"{ts}\t{action}\t{title}\n")
    except: pass

def load_history(limit=500):
    if not os.path.exists(HISTORY_PATH): return []
    try:
        with open(HISTORY_PATH, 'r') as f:
            lines = f.readlines()[-limit:]
    except: return []
    out = []
    for line in lines:
        parts = line.rstrip('\n').split('\t')
        if len(parts) == 3:
            out.append({'ts': parts[0], 'action': parts[1], 'title': parts[2]})
    return out

# --- Dashboard section helpers ----------------------------------------------

def _today_str(): return datetime.now().strftime("%Y-%m-%d")

def section_today_streak(history):
    today = _today_str()
    today_events = [h for h in history if h['ts'].startswith(today)]
    created = sum(1 for h in today_events if h['action'] == 'create')
    reads = sum(1 for h in today_events if h['action'] == 'read')
    # Streak: walk back day-by-day.
    days = sorted({h['ts'][:10] for h in history}, reverse=True)
    streak = 0
    cursor = datetime.strptime(today, "%Y-%m-%d")
    for d in days:
        d_dt = datetime.strptime(d, "%Y-%m-%d")
        delta = (cursor - d_dt).days
        if delta == 0:
            streak += 1
            cursor = d_dt
        elif delta == 1:
            streak += 1
            cursor = d_dt
        else:
            break
    return created, reads, streak

def section_status_tags(notes_metadata):
    statuses = Counter()
    tags = Counter()
    for n in notes_metadata:
        s = (n.get('status') or '').strip()
        if s: statuses[s] += 1
        raw = (n.get('tags') or '').strip()
        if raw.startswith('[') and raw.endswith(']'):
            for t in raw[1:-1].split(','):
                t = t.strip().strip('"\'')
                if t: tags[t] += 1
    return statuses, tags

def section_breadcrumbs(history):
    seen = []
    for h in reversed(history):
        if h['action'] in ('read', 'create') and h['title'] not in seen:
            seen.append(h['title'])
            if len(seen) >= CAP_BREADCRUMBS: break
    return seen

def section_top_hubs(notes_metadata, vault_content):
    # Only count incoming links into notes that actually exist on disk.
    incoming = Counter()
    for content in vault_content.values():
        for link in re.findall(r'\[\[([^\]|#]+)', content):
            incoming[link.strip().lower().replace(' ', '_')] += 1
    ranked = []
    for n in notes_metadata:
        key = n['title'].lower().replace(' ', '_')
        c = incoming.get(key, 0)
        if c > 0: ranked.append((n['title'], c))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:CAP_HUBS]

def section_open_questions(vault_content):
    out = []
    for f_name, content in vault_content.items():
        _, body = split_note(content)
        for line in body.splitlines():
            stripped = line.strip().lstrip('-*> ').strip()
            if stripped.endswith('?') and 5 < len(stripped) < 140:
                out.append((f_name[:-3], stripped))
                if len(out) >= CAP_QUESTIONS * 3: break
    return out[:CAP_QUESTIONS]

def section_broken_links(vault_content):
    existing = {f[:-3].lower() for f in vault_content.keys()}
    broken = Counter()
    sources = {}
    display = {}
    # Reject targets that start with '[' (likely an outer markdown link like `[[[Source]] Code](url)`).
    for f_name, content in vault_content.items():
        for raw in re.findall(r'(?<!\[)\[\[([^\[\]]+)\]\]', content):
            target = raw.split('|')[0].split('#')[0].strip()
            key = target.lower().replace(' ', '_')
            if key and key not in existing:
                broken[key] += 1
                sources.setdefault(key, f_name[:-3])
                display.setdefault(key, target)
    return [(display[k], c, sources[k]) for k, c in broken.most_common(CAP_BROKEN)]

def section_aliases(notes_metadata):
    out = []
    for n in notes_metadata:
        raw = (n.get('aliases') or '').strip()
        if raw.startswith('[') and raw.endswith(']'):
            aliases = [a.strip().strip('"\'') for a in raw[1:-1].split(',') if a.strip()]
            for a in aliases:
                out.append((a, n['title']))
    return out

def section_stale_drift(notes_metadata):
    drift = []
    for n in notes_metadata:
        title = n.get('title', '')
        path = os.path.join(VAULT_PATH, title + ".md")
        if not os.path.isfile(path): continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            updated_raw = (n.get('updated') or '').strip()
            updated = datetime.strptime(updated_raw, "%Y-%m-%d-%H:%M") if updated_raw else None
            if updated and (mtime - updated).total_seconds() > 120:
                drift.append((title, updated_raw, mtime.strftime("%Y-%m-%d %H:%M")))
        except: continue
    return drift

def section_open_todos(vault_content):
    """Open task lines (`- [ ]`) across the vault, with their source note.

    Tasks in TODO.md surface without a source suffix (it's the canonical home);
    tasks in any other note carry a `— [[Source]]` pointer so the user can jump
    back to context. Completed `- [x]` lines are skipped.
    """
    todo_re = re.compile(r'^\s*[-*]\s*\[ \]\s+(.+?)\s*$')
    out = []
    for f_name, content in vault_content.items():
        _, body = split_note(content)
        source = f_name[:-3]
        for line in body.splitlines():
            m = todo_re.match(line)
            if m:
                task = m.group(1).strip()
                if 0 < len(task) < 200:
                    out.append((source, task))
                    if len(out) >= CAP_TODO * 3: break
    return out[:CAP_TODO]

def section_random_rediscover(notes_metadata):
    candidates = [n for n in notes_metadata
                  if int(n.get('recall_count', 0) or 0) == 0 and n.get('updated')]
    if not candidates:
        candidates = [n for n in notes_metadata if n.get('updated')]
    if not candidates: return None
    candidates.sort(key=lambda x: (int(x.get('recall_count', 0) or 0), x.get('updated', '')))
    return candidates[0]

def find_common_keywords(vault_content):
    stop_words = get_dont_add()
    # Skip words that are already linked or that already match a note title —
    # existing titles surface through Linking Opportunities instead.
    skip = set(stop_words)
    for f_name, content in vault_content.items():
        for link in re.findall(r'\[\[(.*?)\]\]', content):
            skip.add(link.lower())
        skip.add(f_name[:-3].replace('_', ' ').lower())
        skip.add(f_name[:-3].lower())

    words = []
    for content in vault_content.values():
        _, body = split_note(content)
        for w in re.findall(r'\b[A-Za-z]{6,}\b', body):
            w_low = w.lower()
            if w_low not in skip:
                words.append(w_low)
    return [w for w, _ in Counter(words).most_common(10)]

def generate_dashboard(notes_metadata, vault_content):
    def _recall(n): return int(n.get('recall_count', 0) or 0)
    history = load_history()

    newest = sorted(notes_metadata, key=lambda x: x.get('updated', ''), reverse=True)[:CAP_HOT]
    strongest = sorted(notes_metadata, key=lambda x: _recall(x), reverse=True)[:CAP_CORE]
    fresh_titles = {n['title'] for n in newest[:5]}
    stagnant = sorted(
        [n for n in strongest if _recall(n) > 0 and n['title'] not in fresh_titles],
        key=lambda x: x.get('updated', '')
    )[:5]
    titles_map = {n['title'].replace('_', ' '): n['title'] for n in notes_metadata}
    total_notes = len(notes_metadata)
    total_links = sum(len(re.findall(r'\[\[.*?\]\]', c)) for c in vault_content.values())

    # Incoming-link graph (Counter feeds both Orphans and Top Hubs).
    incoming = Counter()
    for content in vault_content.values():
        for link in re.findall(r'\[\[([^\]|#]+)', content):
            incoming[link.strip().lower().replace(' ', '_')] += 1
    orphans = [n['title'] for n in notes_metadata
               if incoming.get(n['title'].lower().replace(' ', '_'), 0) == 0]
    density = total_links / total_notes if total_notes > 0 else 0

    linking_opps = {}
    for display_title, actual_title in titles_map.items():
        search_pattern = re.escape(display_title).replace(r'\ ', r'[\ _]')
        pattern = rf'(?<!\[\[)\b{search_pattern}\b(?!\]\])'
        count = 0
        for f_name, content in vault_content.items():
            if f_name != f"{actual_title}.md":
                _, body = split_note(content)
                count += len(re.findall(pattern, body, re.IGNORECASE))
        if count > 0: linking_opps[actual_title] = count
    sorted_opps = sorted(linking_opps.items(), key=lambda x: x[1], reverse=True)[:5]

    common_keywords = find_common_keywords(vault_content)[:CAP_DISCOVERY]
    created, reads, streak = section_today_streak(history)
    statuses, tags = section_status_tags(notes_metadata)
    crumbs = section_breadcrumbs(history)
    hubs = section_top_hubs(notes_metadata, vault_content)
    questions = section_open_questions(vault_content)
    broken = section_broken_links(vault_content)
    aliases = section_aliases(notes_metadata)
    drift = section_stale_drift(notes_metadata)
    rediscover = section_random_rediscover(notes_metadata)
    todos = section_open_todos(vault_content)

    def fmt_counter(c, n=4):
        return " ".join(f"{k}({v})" for k, v in c.most_common(n)) or "—"

    def hhmm(ts):
        # `YYYY-MM-DD-HH:MM` → `HH:MM`; passthrough for anything shorter.
        return ts[-5:] if ts and len(ts) >= 5 else (ts or "—")

    L = ["# 🏛️ Foyer"]

    # ─── HEADER ────────────────────────────────────────────────────────────
    L.append("")
    L.append(
        f"📊 **{total_notes} notes** · {density:.1f} links/note · "
        f"{len(orphans)} orphans · today +{created}/{reads}r · streak {streak}d"
    )
    if statuses or tags:
        L.append(f"🏷️  {fmt_counter(statuses, 3)} · {fmt_counter(tags, 4)}")
    if crumbs:
        L.append("🧭 " + " → ".join(f"[[{t}]]" for t in crumbs))

    # ─── TODO: open tasks across the vault ────────────────────────────────
    if todos:
        L.append("\n---\n\n### ✅ TODO")
        for source, task in todos:
            suffix = "" if source == "TODO" else f" — [[{source}]]"
            L.append(f"- [ ] {task}{suffix}")
        L.append("\n_Tick boxes in the source note (open via the wikilink) — Home is regenerated._")

    # ─── ACTIVE: Hot ‖ Core ───────────────────────────────────────────────
    if newest or strongest:
        L.append("\n---\n\n### Active")
        L.append("| 🔥 Hot (recent) | 💎 Core (recall) |")
        L.append("| :-- | :-- |")
        rows = max(min(len(newest), 5), min(len(strongest), 5))
        for i in range(rows):
            if i < len(newest) and i < 5:
                n = newest[i]
                left = f"[[{n['title']}]] · {hhmm(n.get('updated', ''))}"
            else:
                left = "—"
            if i < len(strongest) and i < 5:
                n = strongest[i]
                right = f"[[{n['title']}]] · {n.get('recall_count', 0)}"
            else:
                right = "—"
            L.append(f"| {left} | {right} |")

    # ─── STRUCTURE: Hubs ‖ Orphans ────────────────────────────────────────
    if hubs or orphans:
        L.append("\n---\n\n### Structure")
        L.append("| 🌟 Top Hubs | 🏚️ Orphans |")
        L.append("| :-- | :-- |")
        rows = max(len(hubs), min(len(orphans), CAP_ORPHANS))
        for i in range(rows):
            left = f"[[{hubs[i][0]}]] · {hubs[i][1]}↩" if i < len(hubs) else "—"
            right = f"[[{orphans[i]}]]" if i < min(len(orphans), CAP_ORPHANS) else "—"
            L.append(f"| {left} | {right} |")

    # ─── REVIEW: Stagnant + Rediscover (single block) ─────────────────────
    if stagnant or rediscover or questions:
        L.append("\n---\n\n### Review")
        if stagnant:
            joined = ", ".join(f"[[{n['title']}]] ({hhmm(n.get('updated', ''))})" for n in stagnant[:3])
            L.append(f"🧊 **Stagnant**: {joined}")
        if rediscover:
            L.append(
                f"🎲 **Rediscover**: [[{rediscover['title']}]] "
                f"(recall {rediscover.get('recall_count', 0)})"
            )
        if questions:
            L.append("❓ **Open Questions**:")
            for title, q in questions:
                L.append(f"- [[{title}]] — {q}")

    # ─── DISCOVERY + LINKING ──────────────────────────────────────────────
    if common_keywords or sorted_opps:
        L.append("\n---")
    if common_keywords:
        L.append("\n### 🏷️ Discovery  — tick **Add** (auto-creates hub) or **Ignore**")
        L.append("| Add | Ignore | Keyword |")
        L.append("| :-: | :----: | :------ |")
        for word in common_keywords:
            L.append(f"| [ ] |  [ ]   | {word} |")
    if sorted_opps:
        L.append("\n### 🔗 Linking Opportunities")
        L.append(" · ".join(f"[[{title}]] ({count}×)" for title, count in sorted_opps))

    # ─── MAINTENANCE ──────────────────────────────────────────────────────
    if broken or drift or aliases:
        L.append("\n---\n\n### 🩺 Maintenance")
        if broken:
            joined = ", ".join(f"[[{t}]]×{c} (in [[{s}]])" for t, c, s in broken)
            L.append(f"- **Broken** ({len(broken)}): {joined}")
        if drift:
            shown = ", ".join(f"[[{t}]]" for t, _, _ in drift[:5])
            extra = f" +{len(drift) - 5}" if len(drift) > 5 else ""
            L.append(f"- **Stale** ({len(drift)}){extra}: {shown} — `palace.py read <note>`")
        if aliases:
            shown = "; ".join(f"{a} → [[{t}]]" for a, t in aliases[:5])
            L.append(f"- **Aliases**: {shown}")

    L.append("\n`palace.py [read|search|create|link|ignore|refresh]`")
    return "\n".join(L)

def refresh_dashboard():
    process_home_checkboxes()
    process_home_todos()
    process_completed_todos()
    all_meta = []
    vault_content = {}
    for f_name in os.listdir(VAULT_PATH):
        if f_name.endswith(".md") and f_name not in META_FILES:
            path = os.path.join(VAULT_PATH, f_name)
            try:
                with open(path, 'r') as f:
                    content = f.read()
                    meta = parse_metadata(content[:1000])
                    meta['title'] = f_name.replace(".md", "")
                    all_meta.append(meta)
                    vault_content[f_name] = content
            except: continue
    dashboard = generate_dashboard(all_meta, vault_content)
    # Only write when content changes — prevents an infinite watcher loop now
    # that Home edits also trigger a refresh.
    try:
        with open(HOME_PATH, 'r') as f: current = f.read()
    except: current = None
    if dashboard != current:
        with open(HOME_PATH, 'w') as f: f.write(dashboard)

def resolve_note_path(target):
    """Accept a full path, vault-relative path, or bare filename (with or without .md)."""
    if os.path.isfile(target):
        return target
    candidate = target if target.endswith(".md") else target + ".md"
    vault_candidate = os.path.join(VAULT_PATH, os.path.basename(candidate))
    if os.path.isfile(vault_candidate):
        return vault_candidate
    return target  # let the caller raise a clear FileNotFoundError

def palace_read(file_path):
    file_path = resolve_note_path(file_path)
    if os.path.basename(file_path) in META_FILES:
        sys.exit(f"Refusing to read meta file '{os.path.basename(file_path)}'. Use 'palace.py refresh' for Home.md.")
    with open(file_path, 'r') as f: content = f.read()
    meta = parse_metadata(content)
    recall = int(meta.get('recall_count', 0)) + 1
    updated = datetime.now().strftime("%Y-%m-%d-%H:%M")
    new_content = update_metadata(content, {'recall_count': recall, 'updated': updated})
    with open(file_path, 'w') as f: f.write(new_content)
    title = os.path.basename(file_path)[:-3] if file_path.endswith('.md') else os.path.basename(file_path)
    record_event('read', title)
    refresh_dashboard()
    return new_content

def palace_search(query):
    refresh_dashboard()
    matches = set()
    # Content matches via grep (fast path).
    result = subprocess.run(
        ["grep", "-rilF", "--include=*.md", query, VAULT_PATH],
        capture_output=True, text=True,
    )
    matches.update(result.stdout.splitlines())
    # Title matches (so queries find notes whose body doesn't mention the term).
    q_low = query.lower()
    for f_name in os.listdir(VAULT_PATH):
        if f_name.endswith(".md") and q_low in f_name.lower():
            matches.add(os.path.join(VAULT_PATH, f_name))

    ranked = []
    for f_path in matches:
        if os.path.basename(f_path) in META_FILES: continue
        try:
            with open(f_path, 'r') as f:
                meta = parse_metadata(f.read(1000))
            mtime = os.path.getmtime(f_path)
            ranked.append((meta.get('updated', '1970-01-01-00:00'), mtime, int(meta.get('recall_count', 0) or 0), f_path))
        except: continue
    ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [x[3] for x in ranked]

def palace_create(title):
    file_path = _create_note(title)
    if file_path is None:
        existing = os.path.join(VAULT_PATH, title.replace(" ", "_") + ".md")
        return print(f"Error: {existing} exists.")
    refresh_dashboard()
    print(f"Created: {file_path}")

# Segments that palace_link must NOT touch: code fences, inline code,
# existing wikilinks, markdown link constructs, and ATX headings. Splitting
# the body on this regex yields alternating plain/protected parts.
_PROTECTED_SEGMENT = re.compile(
    r'(```.*?```'              # fenced code block
    r'|`[^`\n]+`'              # inline code
    r'|\[\[[^\[\]]+\]\]'       # existing wikilink
    r'|\[[^\[\]\n]+\]\([^)\n]+\)'  # markdown [text](url)
    r'|^\#{1,6}[^\n]*$)',      # ATX heading line
    re.DOTALL | re.MULTILINE,
)

def _link_in_plain_text(body, pattern, replacement):
    """Apply pattern → replacement only in plain prose (not code / links / headings)."""
    parts = _PROTECTED_SEGMENT.split(body)
    total = 0
    for i, part in enumerate(parts):
        if i % 2 == 0:
            parts[i], n = re.subn(pattern, replacement, part, flags=re.IGNORECASE)
            total += n
    return "".join(parts), total

def _resolve_note_filename(keyword):
    """Return the on-disk filename for `keyword` if a note exists, else None.
    Matches by exact slug (spaces→underscores) case-insensitively."""
    slug = keyword.strip().replace(" ", "_").lower()
    for f_name in os.listdir(VAULT_PATH):
        if f_name.endswith(".md") and f_name[:-3].lower() == slug:
            return f_name
    return None

def palace_link(keyword, refresh=True):
    target = _resolve_note_filename(keyword)
    if not target:
        slug = keyword.strip().replace(" ", "_")
        print(
            f"Refusing to link '{keyword}': no note '{slug}.md' exists. "
            f"Create it first with: palace.py create \"{keyword}\""
        )
        return
    canonical = target[:-3]  # filename minus .md is the canonical wikilink target
    pattern = rf'\b({re.escape(keyword)})\b'
    replacement = f"[[{canonical}]]"
    count = 0
    for f_name in os.listdir(VAULT_PATH):
        if f_name.endswith(".md") and f_name not in META_FILES:
            path = os.path.join(VAULT_PATH, f_name)
            with open(path, 'r') as f: content = f.read()
            header, body = split_note(content)
            new_body, n = _link_in_plain_text(body, pattern, replacement)
            if n > 0:
                with open(path, 'w') as f: f.write(header + new_body)
                count += n
    if refresh: refresh_dashboard()
    print(f"Linked '{keyword}' in {count} places (→ [[{canonical}]]).")

def palace_ignore(keyword):
    add_to_dont_add(keyword.lower())
    refresh_dashboard()
    print(f"Ignored keyword: {keyword}")

def palace_watch(debounce=1.0):
    """Watch the vault for changes and refresh the dashboard. Requires `inotifywait`."""
    import time, shutil
    if not shutil.which("inotifywait"):
        sys.exit("inotifywait not found — install `inotify-tools`.")
    print(f"[palace] watching {VAULT_PATH} (debounce={debounce}s) …", flush=True)
    refresh_dashboard()
    proc = subprocess.Popen(
        ["inotifywait", "-m", "-q", "-r",
         "-e", "close_write", "-e", "moved_to", "-e", "moved_from", "-e", "delete", "-e", "create",
         "--exclude", r"(\.obsidian/|\.trash/|/\.palace_history$|/\..*\.swp$)",
         "--format", "%w%f",
         VAULT_PATH],
        stdout=subprocess.PIPE, text=True,
    )
    pending = False
    last_event = 0.0
    try:
        import select
        assert proc.stdout is not None
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], debounce)
            now = time.time()
            if ready:
                line = proc.stdout.readline()
                if not line: break
                if not line.strip().endswith(".md"): continue
                pending = True
                last_event = now
            elif pending and (now - last_event) >= debounce:
                try:
                    refresh_dashboard()
                    print(f"[palace] refreshed {datetime.now().strftime('%H:%M:%S')}", flush=True)
                except Exception as e:
                    print(f"[palace] refresh error: {e}", flush=True)
                pending = False
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()

if __name__ == "__main__":
    no_arg = {"refresh", "watch"}
    if len(sys.argv) < 2 or (sys.argv[1] not in no_arg and len(sys.argv) < 3):
        sys.exit("Usage: palace.py [read|search|create|link|ignore|refresh|watch] [target]")
    cmd = sys.argv[1]
    if cmd == "refresh": refresh_dashboard()
    elif cmd == "watch": palace_watch()
    else:
        target = sys.argv[2]
        if cmd == "read": print(palace_read(target))
        elif cmd == "search": print("\n".join(palace_search(target)))
        elif cmd == "create": palace_create(target)
        elif cmd == "link": palace_link(target)
        elif cmd == "ignore": palace_ignore(target)
