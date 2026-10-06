"""Repository guard and installer checks; all side effects stay in temp dirs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[4]


class SourceGuardTests(unittest.TestCase):
    def check_candidate(self, candidate, blocked, ignored=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(REPO / "scripts/check-no-sources.sh", root / "scripts/check-no-sources.sh")
            shutil.copy2(REPO / ".gitignore", root / ".gitignore")
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            git = ["git", "-C", str(root), "-c", "core.excludesFile=/dev/null"]
            target = root / candidate
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Original synthetic guard fixture.\n")
            if ignored is not None:
                result = subprocess.run(git + ["check-ignore", "-q", "--", candidate])
                self.assertEqual(result.returncode, 0 if ignored else 1, candidate)
            # Test tracked paths even when .gitignore already shields them.
            subprocess.run(git + ["add", "-N", "-f", "--", candidate], check=True, capture_output=True)
            result = subprocess.run(["bash", str(root / "scripts/check-no-sources.sh")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1 if blocked else 0, result.stdout + result.stderr)
            if blocked:
                self.assertIn(candidate, result.stderr)

    def test_books_markdown_is_blocked(self):
        for candidate in ("books/x/a.md", "books/a.MARKDOWN", "BOOKS/x/a.Md"):
            with self.subTest(candidate=candidate):
                self.check_candidate(candidate, blocked=True, ignored=True)

    def test_docx_outside_books_is_blocked(self):
        self.check_candidate("notes/a.docx", blocked=True, ignored=True)

    def test_new_extensions_are_case_insensitive(self):
        for suffix in ("azw", "kfx", "docx", "doc", "rtf", "fb2"):
            with self.subTest(suffix=suffix):
                self.check_candidate("notes/a." + suffix.upper(), blocked=True, ignored=True)

    def test_root_readme_is_allowed(self):
        self.check_candidate("README.md", blocked=False, ignored=False)

    def test_skill_markdown_is_allowed(self):
        self.check_candidate(".agents/skills/x/SKILL.md", blocked=False, ignored=False)

    def test_other_documentation_markdown_is_allowed(self):
        for candidate in (".sopify/plan/plan.md", "notes/a.markdown"):
            with self.subTest(candidate=candidate):
                self.check_candidate(candidate, blocked=False, ignored=False)

    def test_original_extension_and_sources_rules_remain(self):
        for candidate in ("a.EPUB", "a.PDF", "a.MOBI", "a.AZW3", "a.DJVU", "a.TXT", "nested/sources/data.json"):
            with self.subTest(candidate=candidate):
                self.check_candidate(candidate, blocked=True)

    def test_python_caches_are_ignored(self):
        for candidate in ("cache/a.pyc", ".agents/skills/x/__pycache__/entry.bin"):
            with self.subTest(candidate=candidate):
                self.check_candidate(candidate, blocked=False, ignored=True)


class CloudInstallTests(unittest.TestCase):
    def test_optional_failure_warns_and_pillow_remains_required(self):
        command = json.loads((REPO / ".cursor/environment.json").read_text())["install"]
        warning = "WARNING: cairosvg unavailable; fireworks PNG export disabled"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stubs = {
                "git": '#!/bin/sh\nexit 0\n',
                "sudo": '#!/bin/sh\nexit "$TASK_SYSTEM"\n',
                "python3": '''#!/bin/sh
case "$*" in
  '-c import cairosvg') exit "$TASK_IMPORT" ;;
  *pillow*) case "$*" in
    *--break-system-packages*) exit "$TASK_PILLOW_BREAK" ;;
    *) exit "$TASK_PILLOW_NORMAL" ;;
    esac ;;
  *cairosvg*) exit "$TASK_CAIRO_PIP" ;;
esac
exit 9
''',
            }
            for name, content in stubs.items():
                target = root / name
                target.write_text(content)
                target.chmod(0o755)
            scenarios = [
                ("all available", 0, 0, 0, 0, 0, 0, False),
                ("libcairo2 failure", 1, 0, 0, 0, 0, 0, True),
                ("cairosvg failure", 0, 1, 0, 0, 0, 0, True),
                ("cairosvg import failure", 0, 0, 1, 0, 0, 0, True),
                ("old pip fallback", 0, 0, 0, 2, 0, 0, False),
                ("pillow required", 1, 1, 1, 1, 1, 1, False),
            ]
            for label, system, pip, imported, pillow_break, pillow_normal, expected, warned in scenarios:
                with self.subTest(scenario=label):
                    env = os.environ.copy()
                    env.update(PATH=str(root), TASK_SYSTEM=str(system), TASK_CAIRO_PIP=str(pip),
                               TASK_IMPORT=str(imported), TASK_PILLOW_BREAK=str(pillow_break),
                               TASK_PILLOW_NORMAL=str(pillow_normal))
                    result = subprocess.run(["/bin/sh", "-c", command], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stderr)
                    self.assertEqual(warning in result.stdout, warned, result.stdout)


if __name__ == "__main__":
    unittest.main()
