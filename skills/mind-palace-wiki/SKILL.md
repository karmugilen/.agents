---
name: mind-palace-wiki
description: Manage a "Mind Palace" Obsidian wiki with spatial indexing, automated linking, and graph analysis. Use when creating, organizing, or analyzing markdown notes, building rooms, or maintaining a personal knowledge base with wikilinks.
---

# Mind Palace Wiki

Manage a structured knowledge base using spatial architecture (Rooms, Lobby, and [[Wikilinks]]).

All file I/O uses UTF-8 encoding. Cross-platform compatible (Windows, macOS, Linux).

## Quick Start

```shell
python .agents/skills/mind-palace-wiki/scripts/wiki_manager.py tree
```

## Available Commands

| Command | Usage | Description |
| :--- | :--- | :--- |
| `build-room` | `build-room [Name]` | Create a new spatial room and link it to Lobby. |
| `add` | `add [Title] --room [Room] [--template T]` | Add note with optional template. Deduplicates links. |
| `remove` | `remove [Title]` | Delete note and clean up all backlinks (full line removal). |
| `link` | `link [Source] [Target]` | Weave a manual wikilink. Deduplicates. |
| `add-asset` | `add-asset [Source] [--folder F]` | Copy file or directory recursively to assets/ directory and return link. |
| `lint` | `lint` | Find broken links and orphaned notes (skips Lobby/log). |
| `analyze` | `analyze [--bridges]` | Hub analysis or cross-room bridge detection. |
| `ingest-url`| `ingest-url [URL] --title [T] --room [R]` | Web-to-Markdown extraction. Deduplicates room links. |
| `rename` | `rename [Old] [New]` | Rename note and update ALL wikilinks vault-wide. |
| `auto-link` | `auto-link` | Auto-wrap note titles in `[[brackets]]`. Skips frontmatter. |
| `search` | `search [Query]` | Case-insensitive keyword search with line numbers. |
| `export` | `export --room [Room]` | Merge room notes into one file (strips frontmatter). |
| `tree` | `tree` | Print hierarchical Lobby > Room > Note topology. |
| `backlinks` | `backlinks [Title]` | Find all notes that link TO a given title. |
| `recent` | `recent` | View last 10 modified notes with timestamps. |
| `write` | `write [Title] [Text] [--append] [--stdin] [--file F]` | Write/append text. Supports multiline via stdin pipe or file. |
| `auto-organize` | `auto-organize [--min-links N]` | Auto-sort notes into subfolders by hub detection (default: ≥3 links = hub). |

## Architecture

- **Lobby.md**: Root node. Auto-created on first `build-room`. Links to all rooms.
- **Room files**: Category containers. Each room links to its notes via `[[wikilinks]]`.
- **Note files**: Individual knowledge nodes with YAML frontmatter.
- **log.md**: Append-only audit trail of all operations.
- **Helper functions**: `_read_file` tries UTF-8-sig → UTF-16 → latin-1 (handles PowerShell BOM). `_write_file`, `_append_file` enforce UTF-8 output.

## Workflows

### 1. Build & Expand
- Create a Room: `build-room "Category"`
- Add a Note: `add "Title" --room "Category"`
- Write content: `write "Title" "Your text here" --append`
- Write multiline (pipe): `echo "line1\nline2" | python wiki_manager.py write "Title" --stdin --append`
- Write multiline (file): `write "Title" --file data.txt --append`
- Ingest Web Data: `ingest-url [URL] --title "Name" --room "Category"`
- Add Asset: `add-asset image.png --folder diagrams` (Returns `![[image.png]]`)

> **Table Format**: When writing data tables to the vault, use Obsidian-compatible markdown pipe tables (`| col | col |` with `| --- | --- |` separator) instead of code blocks. This ensures tables render properly in Obsidian's reading view.

### 2. Connect & Organize
- Weave Strings: `link "Source" "Target"`
- Auto-link Vault: `auto-link` (skips frontmatter, deduplicates)
- Rename Safely: `rename "Old" "New"` (updates all strings vault-wide)

### 3. Analyze & Retrieve
- Visualize: `tree` or `analyze --bridges`
- Search: `search "Query"` or `backlinks "Title"`
- Export Room: `export --room "Category"`

### 4. Maintain
- Health check: `lint` (finds broken links + orphans)
- Resume work: `recent` (last 10 edits by timestamp)

### 5. Auto-Organize
- Run: `auto-organize` (groups notes into subfolders by link density)
- **Algorithm**: Notes with ≥3 outgoing wikilinks become "hubs". Each non-hub note is placed in the folder of the most specific hub (fewest links) that references it. No AI needed.
- **Recursive**: After organizing the top level, it recurses into each new subfolder and repeats — creating infinite depth as your vault grows.
- **Obsidian safe**: Wikilinks resolve by title, not path — moving files into subfolders does NOT break any links.
- **Idempotent**: Running again when already organized prints "Already organized. Nothing to move."
- Custom threshold: `auto-organize --min-links 5` (raise to create fewer, larger groups)

See [EXAMPLES.md](EXAMPLES.md) for detailed scenarios.
