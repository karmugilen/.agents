"""TDD harness for palace.py. Each test runs against an isolated tmp vault by
patching palace.VAULT_PATH / HOME_PATH / DONT_ADD_PATH / HISTORY_PATH.

Run: python3 .agents/skills/obsidian-vault/test_palace.py
"""
import os
import sys
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import palace  # noqa: E402


def write(path, content):
    with open(path, "w") as f:
        f.write(content)


def read(path):
    with open(path) as f:
        return f.read()


class PalaceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="palace-test-")
        self._orig = {
            "VAULT_PATH": palace.VAULT_PATH,
            "HOME_PATH": palace.HOME_PATH,
            "DONT_ADD_PATH": palace.DONT_ADD_PATH,
            "COMPLETED_PATH": palace.COMPLETED_PATH,
            "HISTORY_PATH": palace.HISTORY_PATH,
        }
        palace.VAULT_PATH = self.tmp
        palace.HOME_PATH = os.path.join(self.tmp, "Home.md")
        palace.DONT_ADD_PATH = os.path.join(self.tmp, "dontadd.md")
        palace.COMPLETED_PATH = os.path.join(self.tmp, "Completed.md")
        palace.HISTORY_PATH = os.path.join(self.tmp, ".palace_history")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k, v in self._orig.items():
            setattr(palace, k, v)

    # ---------------- palace_link ----------------

    def test_link_refuses_when_target_missing(self):
        write(os.path.join(self.tmp, "A.md"), "---\n---\nimages are everywhere.\n")
        palace.palace_link("images", refresh=False)
        self.assertNotIn("[[images]]", read(os.path.join(self.tmp, "A.md")))

    def test_link_wraps_when_target_exists(self):
        write(os.path.join(self.tmp, "Entropy.md"), "---\n---\nhub.\n")
        write(os.path.join(self.tmp, "A.md"), "---\n---\nShannon entropy matters.\n")
        palace.palace_link("Entropy", refresh=False)
        self.assertIn("[[Entropy]]", read(os.path.join(self.tmp, "A.md")))

    def test_link_skips_code_fences(self):
        write(os.path.join(self.tmp, "Foo.md"), "---\n---\n")
        write(
            os.path.join(self.tmp, "A.md"),
            "---\n---\nplain foo here.\n```\ncode foo here\n```\n",
        )
        palace.palace_link("foo", refresh=False)
        out = read(os.path.join(self.tmp, "A.md"))
        self.assertIn("[[Foo]]", out)              # canonical title used
        self.assertIn("code foo here", out)        # fenced content preserved
        self.assertNotIn("[[Foo]]", out.split("```")[1])  # no link inside fence

    def test_link_skips_markdown_link_labels(self):
        write(os.path.join(self.tmp, "Source.md"), "---\n---\nhub.\n")
        write(
            os.path.join(self.tmp, "A.md"),
            "---\n---\n[Source Code](https://example.com)\n",
        )
        palace.palace_link("Source", refresh=False)
        self.assertEqual(
            read(os.path.join(self.tmp, "A.md")),
            "---\n---\n[Source Code](https://example.com)\n",
        )

    def test_link_skips_atx_headings(self):
        write(os.path.join(self.tmp, "Foo.md"), "---\n---\n")
        write(os.path.join(self.tmp, "A.md"), "---\n---\n# foo title\nfoo body.\n")
        palace.palace_link("foo", refresh=False)
        out = read(os.path.join(self.tmp, "A.md"))
        self.assertIn("# foo title", out)
        self.assertIn("[[Foo]] body.", out)

    def test_link_skips_existing_wikilinks(self):
        write(os.path.join(self.tmp, "Foo.md"), "---\n---\n")
        write(os.path.join(self.tmp, "A.md"), "---\n---\nfoo and [[foo]] again.\n")
        palace.palace_link("foo", refresh=False)
        out = read(os.path.join(self.tmp, "A.md"))
        # Plain `foo` wrapped to canonical [[Foo]]; existing lowercase [[foo]] preserved.
        self.assertEqual(out, "---\n---\n[[Foo]] and [[foo]] again.\n")

    def test_link_does_not_touch_frontmatter(self):
        write(os.path.join(self.tmp, "Foo.md"), "---\n---\n")
        write(os.path.join(self.tmp, "A.md"), "---\ntags: [foo]\n---\nfoo body.\n")
        palace.palace_link("foo", refresh=False)
        self.assertIn("tags: [foo]", read(os.path.join(self.tmp, "A.md")))

    # ---------------- ignore / dontadd ----------------

    def test_ignore_appends_to_dontadd(self):
        palace.add_to_dont_add("xyz")
        self.assertIn("xyz", read(palace.DONT_ADD_PATH))

    def test_ignore_is_idempotent(self):
        palace.add_to_dont_add("xyz")
        palace.add_to_dont_add("xyz")
        self.assertEqual(read(palace.DONT_ADD_PATH).count("xyz"), 1)

    # ---------------- process_home_checkboxes ----------------

    def _seed_home_with_row(self, add, ignore, keyword):
        write(
            palace.HOME_PATH,
            "## 🏷️ Discovery\n"
            "| Add | Ignore | Keyword |\n"
            "| :-: | :----: | :------ |\n"
            f"| [{add}] |  [{ignore}]   | {keyword} |\n",
        )

    def test_checkbox_ignore_path(self):
        self._seed_home_with_row(" ", "x", "noise")
        palace.process_home_checkboxes()
        self.assertIn("noise", read(palace.DONT_ADD_PATH))

    def test_checkbox_add_with_existing_target_links(self):
        write(os.path.join(self.tmp, "Entropy.md"), "---\n---\nhub.\n")
        write(os.path.join(self.tmp, "A.md"), "---\n---\nentropy here.\n")
        self._seed_home_with_row("x", " ", "entropy")
        palace.process_home_checkboxes()
        # Canonical title is used regardless of the matched keyword's case.
        self.assertIn("[[Entropy]]", read(os.path.join(self.tmp, "A.md")))

    def test_checkbox_add_with_missing_target_auto_creates_stub_and_links(self):
        """Behaviour we want: ticking Add for a keyword with no hub note should
        create the hub stub (Title-Cased, spaces→underscores) and then link."""
        write(os.path.join(self.tmp, "A.md"), "---\n---\nDiffusion models rule.\n")
        self._seed_home_with_row("x", " ", "Diffusion")
        palace.process_home_checkboxes()
        stub = os.path.join(self.tmp, "Diffusion.md")
        self.assertTrue(
            os.path.isfile(stub), "expected stub Diffusion.md to be auto-created"
        )
        self.assertIn("[[Diffusion]]", read(os.path.join(self.tmp, "A.md")))

    def test_checkbox_add_titlecases_lowercase_keyword(self):
        """Discovery keywords are always lowercased; auto-create should produce
        a Title-Cased hub (Frequency.md, not frequency.md) and link with the
        canonical title."""
        write(os.path.join(self.tmp, "A.md"), "---\n---\nfrequency hopping.\n")
        self._seed_home_with_row("x", " ", "frequency")
        palace.process_home_checkboxes()
        self.assertTrue(
            os.path.isfile(os.path.join(self.tmp, "Frequency.md")),
            "expected stub Frequency.md (Title-Cased) to be auto-created",
        )
        self.assertFalse(
            os.path.isfile(os.path.join(self.tmp, "frequency.md")),
            "lowercase frequency.md should not be created",
        )
        self.assertIn("[[Frequency]]", read(os.path.join(self.tmp, "A.md")))

    # ---------------- section_open_todos ----------------

    def test_open_todos_collects_unchecked_tasks(self):
        write(
            os.path.join(self.tmp, "TODO.md"),
            "---\n---\n- [ ] write abstract\n- [x] already done\n- [ ] cite Phantasm\n",
        )
        palace.refresh_dashboard()
        home = read(palace.HOME_PATH)
        self.assertIn("### ✅ TODO", home)
        self.assertIn("- [ ] write abstract", home)
        self.assertIn("- [ ] cite Phantasm", home)
        self.assertNotIn("already done", home)

    def test_open_todos_links_back_to_non_todo_source(self):
        write(
            os.path.join(self.tmp, "Paper.md"),
            "---\n---\n- [ ] verify the DCT figure\n",
        )
        palace.refresh_dashboard()
        home = read(palace.HOME_PATH)
        self.assertIn("- [ ] verify the DCT figure — [[Paper]]", home)

    # ---------------- process_completed_todos ----------------

    def test_completed_tasks_move_to_completed_md(self):
        write(
            os.path.join(self.tmp, "TODO.md"),
            "---\n---\n- [ ] still open\n- [x] finish abstract\n",
        )
        palace.refresh_dashboard()
        # Source file: completed line gone, open line preserved.
        src = read(os.path.join(self.tmp, "TODO.md"))
        self.assertIn("- [ ] still open", src)
        self.assertNotIn("finish abstract", src)
        # Archive file: completed line landed in Completed.md.
        archive = read(palace.COMPLETED_PATH)
        self.assertIn("# Completed", archive)
        self.assertIn("- [x] finish abstract", archive)
        # Open task still surfaces on Home; completed one does not.
        home = read(palace.HOME_PATH)
        self.assertIn("- [ ] still open", home)
        self.assertNotIn("finish abstract", home)

    def test_completed_tasks_keep_source_attribution(self):
        write(
            os.path.join(self.tmp, "Paper.md"),
            "---\n---\n- [x] verify DCT figure\n",
        )
        palace.refresh_dashboard()
        archive = read(palace.COMPLETED_PATH)
        self.assertIn("- [x] verify DCT figure — [[Paper]]", archive)
        # The source note no longer carries the ticked line.
        self.assertNotIn("[x]", read(os.path.join(self.tmp, "Paper.md")))

    def test_completed_archive_is_skipped_on_subsequent_refresh(self):
        """Re-running refresh must not re-archive lines already in Completed.md
        (otherwise they'd duplicate and the file would be wiped of [x] lines)."""
        write(
            os.path.join(self.tmp, "TODO.md"),
            "---\n---\n- [x] one and done\n",
        )
        palace.refresh_dashboard()
        first = read(palace.COMPLETED_PATH)
        palace.refresh_dashboard()
        second = read(palace.COMPLETED_PATH)
        # Same content — no duplicate archival from re-reading Completed.md.
        self.assertEqual(first.count("- [x] one and done"), 1)
        self.assertEqual(second.count("- [x] one and done"), 1)

    # ---------------- process_home_todos (interactive Home edits) ----------

    def test_home_typed_open_task_lands_in_todo_md(self):
        """User types `- [ ] foo` directly in Home → palace appends it to TODO.md."""
        write(os.path.join(self.tmp, "TODO.md"), "---\n---\n# TODO\n")
        write(palace.HOME_PATH,
              "# 🏛️ Foyer\n\n---\n\n### ✅ TODO\n- [ ] buy milk\n\n---\n")
        palace.refresh_dashboard()
        self.assertIn("- [ ] buy milk", read(os.path.join(self.tmp, "TODO.md")))

    def test_home_tick_with_source_archives_via_source(self):
        """Ticking on Home with `— [[Source]]` suffix flips the source line and
        archives in one refresh."""
        write(os.path.join(self.tmp, "Paper.md"),
              "---\n---\n- [ ] cite reference\n")
        write(palace.HOME_PATH,
              "# 🏛️ Foyer\n\n---\n\n### ✅ TODO\n"
              "- [x] cite reference — [[Paper]]\n\n---\n")
        palace.refresh_dashboard()
        # Source no longer carries the task (archived away).
        self.assertNotIn("cite reference", read(os.path.join(self.tmp, "Paper.md")))
        # Completed archive received the line with attribution.
        self.assertIn("- [x] cite reference — [[Paper]]",
                      read(palace.COMPLETED_PATH))

    def test_home_tick_with_no_source_uses_todo_md(self):
        """Ticking on Home with no suffix → treat as a TODO.md task and archive."""
        write(os.path.join(self.tmp, "TODO.md"),
              "---\n---\n- [ ] pay rent\n")
        write(palace.HOME_PATH,
              "# 🏛️ Foyer\n\n---\n\n### ✅ TODO\n- [x] pay rent\n\n---\n")
        palace.refresh_dashboard()
        self.assertNotIn("pay rent", read(os.path.join(self.tmp, "TODO.md")))
        archive = read(palace.COMPLETED_PATH)
        self.assertIn("- [x] pay rent", archive)
        # No `— [[TODO]]` suffix (TODO.md is the canonical home).
        self.assertNotIn("— [[TODO]]", archive)

    def test_home_typed_ticked_task_lands_in_archive(self):
        """User types `- [x] foo` directly in Home in one step (no prior open
        line anywhere) → it still ends up in Completed.md."""
        write(os.path.join(self.tmp, "TODO.md"), "---\n---\n# TODO\n")
        write(palace.HOME_PATH,
              "# 🏛️ Foyer\n\n---\n\n### ✅ TODO\n- [x] one-shot done\n\n---\n")
        palace.refresh_dashboard()
        self.assertIn("- [x] one-shot done", read(palace.COMPLETED_PATH))

    def test_refresh_is_idempotent_no_rewrite_when_unchanged(self):
        """Two refreshes in a row must produce identical Home content and the
        mtime must not bump on the second — prevents the watcher self-loop."""
        write(os.path.join(self.tmp, "A.md"), "---\n---\nbody\n")
        palace.refresh_dashboard()
        first_mtime = os.path.getmtime(palace.HOME_PATH)
        first_content = read(palace.HOME_PATH)
        import time; time.sleep(0.05)
        palace.refresh_dashboard()
        self.assertEqual(os.path.getmtime(palace.HOME_PATH), first_mtime,
                         "Home was rewritten despite no change — watcher would loop")
        self.assertEqual(read(palace.HOME_PATH), first_content)

    def test_completed_archive_noop_when_nothing_ticked(self):
        write(os.path.join(self.tmp, "TODO.md"), "---\n---\n- [ ] still open\n")
        palace.refresh_dashboard()
        self.assertFalse(os.path.exists(palace.COMPLETED_PATH))

    def test_open_todos_section_hidden_when_no_tasks(self):
        write(os.path.join(self.tmp, "A.md"), "---\n---\nNo tasks here.\n")
        palace.refresh_dashboard()
        self.assertNotIn("### ✅ TODO", read(palace.HOME_PATH))

    def test_checkbox_ignore_takes_precedence_when_both_ticked(self):
        write(os.path.join(self.tmp, "Foo.md"), "---\n---\nhub.\n")
        write(os.path.join(self.tmp, "A.md"), "---\n---\nfoo mention.\n")
        self._seed_home_with_row("x", "x", "foo")
        palace.process_home_checkboxes()
        self.assertIn("foo", read(palace.DONT_ADD_PATH))
        # If ignore wins, no wikilink should be created.
        self.assertNotIn("[[foo]]", read(os.path.join(self.tmp, "A.md")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
