import os
import sys
import argparse
import glob
import re
import datetime
import urllib.request
import shutil

WIKI_DIR = os.path.expanduser("~/wiki")
LOBBY_FILE = os.path.join(WIKI_DIR, "Lobby.md")
LOG_FILE = os.path.join(WIKI_DIR, "log.md")


def log_action(command, target):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(WIKI_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {command} | {target}\n")


def _ensure_lobby():
    """Create Lobby.md if it doesn't exist."""
    os.makedirs(WIKI_DIR, exist_ok=True)
    if not os.path.exists(LOBBY_FILE):
        with open(LOBBY_FILE, "w", encoding="utf-8") as f:
            f.write("# Lobby\n")


def _read_file(path):
    """Read a file, handling BOM and encoding variants (UTF-8, UTF-16, latin-1)."""
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise UnicodeDecodeError(f"Cannot decode {path} with any known encoding")


def _write_file(path, content):
    """Write a file with UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _append_file(path, content):
    """Append to a file with UTF-8 encoding."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)


def _note_path(title):
    """Find a note by title. Checks root then subfolders. Falls back to root for new files."""
    root = os.path.join(WIKI_DIR, f"{title}.md")
    if os.path.exists(root):
        return root
    for p in glob.glob(os.path.join(WIKI_DIR, "**", f"{title}.md"), recursive=True):
        return p
    return root


def _all_md_files():
    """Get all .md files recursively, excluding the assets folder."""
    all_files = glob.glob(os.path.join(WIKI_DIR, "**", "*.md"), recursive=True)
    return [f for f in all_files if "assets" not in os.path.relpath(f, WIKI_DIR).split(os.sep)]


def _find_links(content):
    """Extract all [[wikilinks]] from content."""
    return re.findall(r"\[\[(.*?)\]\]", content)


def _strip_frontmatter(content):
    """Remove YAML frontmatter from content, return (frontmatter, body)."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) > 2:
            return parts[1].strip(), parts[2]
    return "", content


def build_room(room_name):
    os.makedirs(WIKI_DIR, exist_ok=True)

    room_file = os.path.join(WIKI_DIR, f"{room_name}.md")
    if not os.path.exists(room_file):
        _write_file(room_file, f"# {room_name}\n")

    # Link from Lobby (read first, then append if needed)
    _ensure_lobby()
    lobby_content = _read_file(LOBBY_FILE)
    if f"[[{room_name}]]" not in lobby_content:
        _append_file(LOBBY_FILE, f"\n- [[{room_name}]]")

    log_action("build-room", room_name)


def add_note(title, room, template=None):
    note_file = _note_path(title)
    frontmatter = f"---\ntitle: {title}\n---\n"

    template_content = f"# {title}\n"
    if template:
        template_path = os.path.join(WIKI_DIR, "templates", f"{template}.md")
        if os.path.exists(template_path):
            template_content = _read_file(template_path)

    _write_file(note_file, frontmatter + template_content)

    # Add link in room file (check for duplicates)
    room_file = _note_path(room)
    if os.path.exists(room_file):
        room_content = _read_file(room_file)
        if f"[[{title}]]" not in room_content:
            _append_file(room_file, f"\n- [[{title}]]")

    log_action("add", f"{title} in {room} (template: {template})")


def remove_note(title):
    # 1. Remove file
    note_file = _note_path(title)
    if os.path.exists(note_file):
        os.remove(note_file)

    # 2. Cleanup backlinks (remove full lines containing the link)
    link_str = f"[[{title}]]"
    for md_file in _all_md_files():
        content = _read_file(md_file)
        if link_str in content:
            # Remove entire lines that are just a list item with this link
            lines = content.splitlines(keepends=True)
            cleaned = [line for line in lines if link_str not in line]
            _write_file(md_file, "".join(cleaned))

    log_action("remove", title)


def link_notes(source, target):
    source_file = _note_path(source)
    if os.path.exists(source_file):
        # Check for duplicate links
        content = _read_file(source_file)
        if f"[[{target}]]" not in content:
            _append_file(source_file, f"\n- [[{target}]]")

    log_action("link", f"{source} to {target}")


def add_asset(source_path, subfolder=None):
    if not os.path.exists(source_path):
        print(f"Error: Source file or directory '{source_path}' does not exist.")
        return

    # Determine target directory
    target_dir = os.path.join(WIKI_DIR, "assets")
    if subfolder:
        target_dir = os.path.join(target_dir, subfolder)
    os.makedirs(target_dir, exist_ok=True)

    # Handle collisions
    filename = os.path.basename(source_path.rstrip("/\\"))
    target_path = os.path.join(target_dir, filename)

    if os.path.isdir(source_path):
        name = filename
        counter = 1
        while os.path.exists(target_path):
            filename = f"{name}_{counter}"
            target_path = os.path.join(target_dir, filename)
            counter += 1
        try:
            shutil.copytree(source_path, target_path)
            # Use relative path from wiki root for the link
            rel_path = os.path.relpath(target_path, WIKI_DIR)
            link = f"`{rel_path}/`"
        except Exception as e:
            print(f"Error copying directory: {e}")
            return
    else:
        name, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(target_path):
            filename = f"{name}_{counter}{ext}"
            target_path = os.path.join(target_dir, filename)
            counter += 1

        # Copy file
        try:
            shutil.copy2(source_path, target_path)
        except Exception as e:
            print(f"Error copying file: {e}")
            return

        # Determine Obsidian embed syntax
        embed_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".mp4", ".webm", ".mp3", ".wav", ".ogg"}
        if ext.lower() in embed_exts:
            link = f"![[{filename}]]"
        else:
            link = f"[[{filename}]]"

    log_action("add-asset", f"{filename} to assets/{subfolder or ''}")
    print(f"Asset added successfully. Use this link in your notes:\n{link}")


def lint_wiki():
    all_files = [os.path.basename(f)[:-3] for f in _all_md_files()]
    backlinks = {f: 0 for f in all_files}
    broken_links = []
    # Files to skip in orphan detection
    skip_orphan = {"Lobby", "log"}

    for md_file in _all_md_files():
        content = _read_file(md_file)
        links = _find_links(content)
        for link in links:
            if link in all_files:
                backlinks[link] += 1
            else:
                broken_links.append((os.path.basename(md_file), link))

    for file, count in backlinks.items():
        if count == 0 and file not in skip_orphan:
            print(f"Orphan note: {file}")

    for file, target in broken_links:
        print(f"Broken link: {target} (found in {file})")


def analyze_graph(find_bridges=False):
    all_files = _all_md_files()
    link_counts = {}

    # 1. Hub detection
    for md_file in all_files:
        content = _read_file(md_file)
        links = _find_links(content)
        for link in links:
            link_counts[link] = link_counts.get(link, 0) + 1

    if not find_bridges:
        print("Knowledge Graph Analysis (Hubs):")
        sorted_hubs = sorted(link_counts.items(), key=lambda x: x[1], reverse=True)
        for title, count in sorted_hubs[:5]:
            print(f"- {title}: {count} links")
    else:
        # 2. Bridge detection (notes in multiple rooms)
        print("Cross-Room Bridges Detected:")
        if not os.path.exists(LOBBY_FILE):
            print("No Lobby found. Build rooms first.")
            return

        lobby_content = _read_file(LOBBY_FILE)
        rooms = _find_links(lobby_content)

        note_to_rooms = {}
        for room in rooms:
            room_path = _note_path(room)
            if os.path.exists(room_path):
                room_content = _read_file(room_path)
                notes = _find_links(room_content)
                for note in notes:
                    if note not in note_to_rooms:
                        note_to_rooms[note] = []
                    note_to_rooms[note].append(room)

        bridges_found = False
        for note, rooms_found in note_to_rooms.items():
            if len(rooms_found) > 1:
                print(f"- {note} connects: {', '.join(rooms_found)}")
                bridges_found = True

        if not bridges_found:
            print("No bridges found. Knowledge is isolated.")

    log_action("analyze", f"graph (bridges={find_bridges})")


def ingest_url(url, title, room):
    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode('utf-8')

        # Simple regex-based tag stripping for zero-dependency
        text = re.sub(r'<script.*?>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style.*?>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        note_file = _note_path(title)
        frontmatter = f"---\ntitle: {title}\nsource: {url}\n---\n"
        content = f"# {title}\n\n{text}\n"

        _write_file(note_file, frontmatter + content)

        room_file = _note_path(room)
        if os.path.exists(room_file):
            room_content = _read_file(room_file)
            if f"[[{title}]]" not in room_content:
                _append_file(room_file, f"\n- [[{title}]]")

        log_action("ingest-url", f"{title} from {url}")
        print(f"Ingested {url} as {title}")
    except Exception as e:
        print(f"Error ingesting {url}: {e}")


def rename_note(old_title, new_title):
    old_file = _note_path(old_title)
    new_file = os.path.join(os.path.dirname(old_file), f"{new_title}.md")

    if os.path.exists(old_file):
        os.rename(old_file, new_file)

        # Update content (header)
        content = _read_file(new_file)
        new_content = content.replace(f"# {old_title}", f"# {new_title}").replace(f"title: {old_title}", f"title: {new_title}")
        _write_file(new_file, new_content)

        # Update backlinks across all files
        old_link = f"[[{old_title}]]"
        new_link = f"[[{new_title}]]"
        for md_file in _all_md_files():
            content = _read_file(md_file)
            if old_link in content:
                updated = content.replace(old_link, new_link)
                _write_file(md_file, updated)

        log_action("rename", f"{old_title} to {new_title}")
        print(f"Renamed {old_title} to {new_title}")


def auto_link_notes():
    all_titles = [os.path.basename(f)[:-3] for f in _all_md_files()]
    all_titles.sort(key=len, reverse=True)

    for md_file in _all_md_files():
        title_of_file = os.path.basename(md_file)[:-3]
        if title_of_file in ("Lobby", "log"):
            continue

        content = _read_file(md_file)

        # Split off frontmatter to avoid linking inside YAML
        fm, body = _strip_frontmatter(content)

        modified = False
        new_body = body

        for target in all_titles:
            if target == title_of_file:
                continue

            # Regex to find title not already in brackets
            pattern = rf"(?<!\[\[)\b{re.escape(target)}\b(?!\]\])"
            if re.search(pattern, new_body):
                new_body = re.sub(pattern, f"[[{target}]]", new_body)
                modified = True

        if modified:
            if fm:
                _write_file(md_file, f"---\n{fm}\n---{new_body}")
            else:
                _write_file(md_file, new_body)

    log_action("auto-link", "all files")
    print("Auto-linked all files.")


def search_notes(query):
    print(f"Searching for: {query}")
    count = 0
    for md_file in _all_md_files():
        lines = _read_file(md_file).splitlines()
        for i, line in enumerate(lines):
            if query.lower() in line.lower():
                print(f"{os.path.basename(md_file)}:{i+1}: {line.strip()}")
                count += 1
    print(f"Found {count} matches.")
    log_action("search", query)


def export_room(room_name):
    room_file = _note_path(room_name)
    if not os.path.exists(room_file):
        print(f"Room {room_name} not found.")
        return

    content = _read_file(room_file)
    notes = _find_links(content)

    export_file = f"export_{room_name}.md"
    with open(export_file, "w", encoding="utf-8") as out:
        out.write(f"# Export: {room_name}\n\n")
        for note in notes:
            note_path = _note_path(note)
            if os.path.exists(note_path):
                n_content = _read_file(note_path)
                # Strip frontmatter
                _, body = _strip_frontmatter(n_content)
                out.write(f"## {note}\n{body.strip()}\n\n---\n\n")

    log_action("export", room_name)
    print(f"Exported {room_name} to {export_file}")


def print_tree():
    print("Lobby (Vault Root)")
    # Show filesystem structure
    for entry in sorted(os.listdir(WIKI_DIR)):
        if entry == "assets":
            continue
        path = os.path.join(WIKI_DIR, entry)
        if os.path.isdir(path):
            print(f"|-- {entry}/")
            for sf in sorted(os.listdir(path)):
                if sf.endswith('.md'):
                    print(f"    |-- {sf[:-3]}")
        elif entry.endswith('.md') and entry not in ('Lobby.md', 'log.md'):
            print(f"|-- {entry[:-3]}")

    log_action("tree", "viewed")


def find_backlinks(title):
    print(f"Backlinks for: [[{title}]]")
    link_str = f"[[{title}]]"
    count = 0
    for md_file in _all_md_files():
        if link_str in _read_file(md_file):
            print(f"- {os.path.basename(md_file)}")
            count += 1
    print(f"Total backlinks: {count}")
    log_action("backlinks", title)


def show_recent():
    print("Most Recent Knowledge Modifications:")
    all_files = _all_md_files()
    all_files.sort(key=os.path.getmtime, reverse=True)

    for f in all_files[:10]:
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"- {os.path.basename(f)} ({mtime})")

    log_action("recent", "viewed")


def write_note_content(title, text=None, append=False, from_stdin=False, from_file=None):
    note_file = _note_path(title)
    if not os.path.exists(note_file):
        print(f"Note {title} not found.")
        return

    # Resolve content source: --stdin > --file > positional text
    if from_stdin:
        text = sys.stdin.read()
    elif from_file:
        if not os.path.exists(from_file):
            print(f"File not found: {from_file}")
            return
        text = _read_file(from_file)

    if text is None:
        print("No content provided. Use text arg, --stdin, or --file.")
        return

    if append:
        _append_file(note_file, f"\n{text}")
    else:
        _write_file(note_file, text)

    log_action("write", f"{title} (append={append})")
    print(f"Updated {title}")


def auto_organize(min_links=3):
    """Organize notes into subfolders by wikilink hub detection. No AI needed."""
    skip = {"Lobby", "log"}

    # 1. Build link graph
    graph = {}
    file_paths = {}
    for md_file in _all_md_files():
        title = os.path.splitext(os.path.basename(md_file))[0]
        if title in skip:
            continue
        content = _read_file(md_file)
        links = [l for l in _find_links(content) if l not in skip]
        graph[title] = links
        file_paths[title] = md_file

    # 2. Score and identify hubs (notes with >= min_links outgoing)
    hub_scores = {t: len(links) for t, links in graph.items()}
    hubs = set(t for t, s in hub_scores.items() if s >= min_links)

    if not hubs:
        print("No hubs found (no note has >= {min_links} outgoing links). Nothing to organize.")
        return

    # 3. Assign each non-hub note to the most specific hub that links to it
    assignments = {h: [] for h in hubs}
    for title in graph:
        if title in hubs or title in skip:
            continue
        # Find all hubs that link TO this note
        candidates = [(h, hub_scores[h]) for h in hubs if title in graph.get(h, [])]
        if candidates:
            # Pick the most specific hub (fewest outgoing links)
            best_hub = min(candidates, key=lambda x: x[1])[0]
            assignments[best_hub].append(title)

    # 4. Move files into subfolders
    moved = 0
    for hub_title, notes in assignments.items():
        if not notes:
            continue

        folder = os.path.join(WIKI_DIR, hub_title)
        os.makedirs(folder, exist_ok=True)

        # Move hub file itself
        if hub_title in file_paths:
            src = os.path.abspath(file_paths[hub_title])
            dst = os.path.abspath(os.path.join(folder, f"{hub_title}.md"))
            if src != dst:
                shutil.move(src, dst)
                print(f"  [{hub_title}/] Hub moved")
                moved += 1

        # Move child notes
        for note in notes:
            if note in file_paths:
                src = os.path.abspath(file_paths[note])
                dst = os.path.abspath(os.path.join(folder, f"{note}.md"))
                if src != dst:
                    shutil.move(src, dst)
                    print(f"  [{hub_title}/] {note}")
                    moved += 1

    print(f"\nOrganized {moved} files into {sum(1 for v in assignments.values() if v)} folders.")
    log_action("auto-organize", f"{moved} files moved into {sum(1 for v in assignments.values() if v)} folders")


def main():
    parser = argparse.ArgumentParser(description="Wiki Manager")
    subparsers = parser.add_subparsers(dest="command")

    room_parser = subparsers.add_parser("build-room")
    room_parser.add_argument("name")

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("title")
    add_parser.add_argument("--room", required=True)
    add_parser.add_argument("--template")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("title")

    link_parser = subparsers.add_parser("link")
    link_parser.add_argument("source")
    link_parser.add_argument("target")

    asset_parser = subparsers.add_parser("add-asset")
    asset_parser.add_argument("source")
    asset_parser.add_argument("--folder", help="Optional subfolder inside assets/")

    subparsers.add_parser("lint")

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--bridges", action="store_true")

    ingest_parser = subparsers.add_parser("ingest-url")
    ingest_parser.add_argument("url")
    ingest_parser.add_argument("--title", required=True)
    ingest_parser.add_argument("--room", required=True)

    rename_parser = subparsers.add_parser("rename")
    rename_parser.add_argument("old")
    rename_parser.add_argument("new")

    subparsers.add_parser("auto-link")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--room", required=True)

    subparsers.add_parser("tree")

    backlinks_parser = subparsers.add_parser("backlinks")
    backlinks_parser.add_argument("title")

    subparsers.add_parser("recent")

    organize_parser = subparsers.add_parser("auto-organize")
    organize_parser.add_argument("--min-links", type=int, default=3, help="Min outgoing links to be a hub")

    write_parser = subparsers.add_parser("write")
    write_parser.add_argument("title")
    write_parser.add_argument("text", nargs="?", default=None)
    write_parser.add_argument("--append", action="store_true")
    write_parser.add_argument("--stdin", action="store_true", help="Read content from stdin (pipe)")
    write_parser.add_argument("--file", dest="from_file", help="Read content from a file path")

    args = parser.parse_args()

    if args.command == "build-room":
        build_room(args.name)
    elif args.command == "add":
        add_note(args.title, args.room, args.template)
    elif args.command == "remove":
        remove_note(args.title)
    elif args.command == "link":
        link_notes(args.source, args.target)
    elif args.command == "add-asset":
        add_asset(args.source, args.folder)
    elif args.command == "lint":
        lint_wiki()
    elif args.command == "analyze":
        analyze_graph(args.bridges)
    elif args.command == "ingest-url":
        ingest_url(args.url, args.title, args.room)
    elif args.command == "rename":
        rename_note(args.old, args.new)
    elif args.command == "auto-link":
        auto_link_notes()
    elif args.command == "search":
        search_notes(args.query)
    elif args.command == "export":
        export_room(args.room)
    elif args.command == "tree":
        print_tree()
    elif args.command == "backlinks":
        find_backlinks(args.title)
    elif args.command == "recent":
        show_recent()
    elif args.command == "write":
        write_note_content(args.title, args.text, args.append, args.stdin, args.from_file)
    elif args.command == "auto-organize":
        auto_organize(args.min_links)


if __name__ == "__main__":
    main()
