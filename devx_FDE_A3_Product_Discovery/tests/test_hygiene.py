"""Repository hygiene: no credential may be committed.

The submission ships a snapshot and a `.gitignore`, and it would be easy to
commit a `.env`, a WAL file or an API key without noticing. This test is the
check that makes "no credential is committed" a fact rather than an intention.

It is deliberately blunt: it scans the tracked tree for the shapes a leaked
credential takes, and it fails on any hit. It is not a substitute for a secret
scanner — it is a tripwire that costs nothing to run on every commit.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Files that must never be committed, by name pattern.
FORBIDDEN_NAMES = (
    ".env",
    ".env.local",
    ".env.production",
    "auth.json",
    "credentials.json",
)

#: Extensions that are runtime artefacts, not source.
FORBIDDEN_SUFFIXES = (".duckdb.wal", ".duckdb.tmp", ".previous.duckdb")

#: Text files worth scanning for a literal key. Binary and vendored paths are
#: skipped: a base64 blob in a `.zip` is not a leaked credential, and scanning
#: the venv would produce noise that trains you to ignore the check.
SCAN_SUFFIXES = (".py", ".md", ".toml", ".sh", ".json", ".cfg", ".ini", ".txt")
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", ".pytest_cache", "node_modules"}

#: Shapes a leaked credential actually takes.
SECRET_PATTERNS = (
    # OpenAI/9router-style key
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    # A bearer token assigned to a literal
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{20,}"),
    # An API key assigned a long literal (not an env-var read)
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*"
        r"[\"']([A-Za-z0-9_\-\.]{24,})[\"']"
    ),
)


def _walk() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


class TestNoCredentialsCommitted:
    """The property is "not committable", not "not present".

    A local `.env` or a displaced snapshot may legitimately exist on disk — the
    previous snapshot is a diff baseline, and a developer's `.env` is how the app
    is configured locally. What must never happen is either being *committed*, so
    the check is against git's ignore rules rather than against the filesystem.
    """

    @staticmethod
    def _is_ignored(path: Path) -> bool | None:
        """True/False from git, or None when git cannot answer."""
        try:
            out = subprocess.run(
                ["git", "check-ignore", "-q", str(path)],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        return out.returncode == 0

    def test_no_credential_file_is_committable(self):
        for path in _walk():
            forbidden = (
                path.name in FORBIDDEN_NAMES
                or any(path.name.endswith(s) for s in FORBIDDEN_SUFFIXES)
            )
            if not forbidden:
                continue
            ignored = self._is_ignored(path)
            if ignored is None:
                # No git available: fall back to the strict reading, since
                # without git there is no ignore mechanism protecting it.
                pytest.fail(
                    f"{path.relative_to(ROOT)} must not be present, and git is "
                    f"unavailable to prove it would be ignored"
                )
            assert ignored, (
                f"{path.relative_to(ROOT)} is not gitignored and would be "
                f"committed"
            )

    def test_gitignore_covers_the_forbidden_names(self):
        # A file that exists but is ignored is fine; a file that would be
        # committed is not. The rules must be present even if the files are not.
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in ignored
        assert "*.duckdb.wal" in ignored
        assert "*.previous.duckdb" in ignored
        # The snapshot itself IS committed, on purpose: the demo must run from a
        # clean checkout without crawling. Only the displaced baseline is not.
        assert "\n*.duckdb\n" not in ignored, (
            "the catalog snapshot is committed deliberately; ignoring it would "
            "break the five-command run"
        )

    @pytest.mark.parametrize("pattern", range(len(SECRET_PATTERNS)))
    def test_no_source_file_contains_a_literal_secret(self, pattern):
        matcher = SECRET_PATTERNS[pattern]
        for path in _walk():
            if path.suffix not in SCAN_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in matcher.finditer(text):
                # An env-var read is the documented configuration path, not a
                # leak. `os.environ.get("...")` and `getenv` are how the app is
                # meant to be configured.
                context = text[max(0, match.start() - 80):match.end() + 40]
                if "environ" in context or "getenv" in context:
                    continue
                pytest.fail(
                    f"{path.relative_to(ROOT)} looks like it contains a "
                    f"credential: {match.group(0)[:40]!r}"
                )

    def test_the_documented_configuration_is_environment_only(self):
        """The README must not instruct anyone to put a key in a file."""
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "PAPERLANE_LLM_API_KEY" in readme
        # It may name the variable; it must not supply a value.
        assert not re.search(r"PAPERLANE_LLM_API_KEY\s*=\s*[A-Za-z0-9]", readme)

    def test_git_status_shows_no_secret_bearing_path(self):
        """If this is a git repository, nothing secret may be staged."""
        try:
            out = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pytest.skip("git is not available")
        if out.returncode != 0:
            pytest.skip("not a git repository")
        for line in out.stdout.splitlines():
            path = line[3:].strip()
            name = Path(path).name
            assert name not in FORBIDDEN_NAMES, f"staged: {path}"
            assert not any(name.endswith(s) for s in FORBIDDEN_SUFFIXES), (
                f"staged: {path}"
            )


# ---------------------------------------------------------------------------
# Produced records (task 6.1)
# ---------------------------------------------------------------------------


class TestProducedRecordsCarryNoCredential:
    """Scan the records the application actually writes, not just the source.

    The source scan above catches a key typed into a file. This catches the other
    direction: a key that arrives at runtime and is written out. They are
    different failures and neither implies the other, so both are checked.

    The records are produced by driving the real application, because a scan of a
    hand-written sample would prove nothing about what the application does.
    """

    #: A value no source file contains, so a hit in the log is a real leak.
    #: Assembled at runtime: a literal here would trip this repository's own
    #: credential scan, which is a false positive in the check that matters.
    SENTINEL = "sk-" + "recordscan" + "0" * 22

    @staticmethod
    def _records(tmp_path: Path) -> str:
        """Drive the app and return everything it wrote, as one string."""
        from fastapi.testclient import TestClient

        from paperlane.api import create_app
        from paperlane.records import RecordWriter

        log = tmp_path / "requests.jsonl"
        client = TestClient(create_app(record_writer=RecordWriter(log)))
        client.post("/api/ask", json={
            "request": "A4 80gsm 20 reams", "use_model": False,
        })
        client.post("/api/quote", json={
            "size": "A4", "weight_gsm": 80, "quantity": 20,
        })
        client.post("/api/quote/lines", json={"lines": [
            {"sku": "PL-CP-A4-80-NUSA", "quantity": 10},
        ]})
        client.post("/ask", data={"request": "A4 80gsm 20 reams"})
        return log.read_text() if log.exists() else ""

    def test_produced_records_contain_no_credential_shape(self, tmp_path):
        text = self._records(tmp_path)
        assert text, "no records were produced, so the scan proves nothing"
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            assert not match, (
                f"a produced record contains a credential: "
                f"{match.group(0)[:40]!r}"
            )

    def test_a_key_in_an_error_path_does_not_reach_the_record(
        self, tmp_path, monkeypatch
    ):
        """The failure that a source scan cannot catch.

        A provider client that quotes its own key in an exception message would
        put it into ``fallback_reason``. This asserts the record does not carry
        it — which is the runtime half of "no credential is ever recorded".
        """
        from fastapi.testclient import TestClient

        from paperlane.api import create_app
        from paperlane.records import RecordWriter

        monkeypatch.setenv("PAPERLANE_LLM_API_KEY", self.SENTINEL)
        sentinel = self.SENTINEL

        class LeakyClient:
            def extract_criteria(self, text: str):
                raise RuntimeError(f"upstream rejected {sentinel}")

        log = tmp_path / "requests.jsonl"
        client = TestClient(create_app(
            model_client=LeakyClient(), record_writer=RecordWriter(log)
        ))
        client.post("/api/ask", json={"request": "A4 80gsm 20 reams"})

        text = log.read_text()
        assert sentinel not in text
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text)

    def test_the_record_file_is_not_committable(self, tmp_path):
        """Operational data must be gitignored, so the scan is a backstop."""
        from paperlane import records

        try:
            out = subprocess.run(
                ["git", "check-ignore", "-q", str(records.DEFAULT_PATH)],
                cwd=ROOT, capture_output=True, text=True, timeout=20,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            pytest.skip("git is not available")
        assert out.returncode == 0, (
            f"{records.DEFAULT_PATH.name} is not gitignored"
        )


class TestDocumentationIndex:
    """Every doc that exists is listed, and every doc listed exists.

    A docs index drifts in exactly one direction: it stops mentioning a file that
    was added, so the file is invisible to anyone reading the index. That is not
    a typo, it is a doc nobody finds. Checked in both directions, because the
    other drift — an index naming a file that was deleted — is just as
    misleading.
    """

    def _listed(self) -> set[str]:
        """Doc filenames the README index mentions.

        Two forms are used in the README: an explicit ``docs/name.md`` link, and
        a bare ``name.md`` inside the "Full detail in ``docs/``:" sentence. Both
        count as listed — the index is that sentence — so both are collected.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        listed = set(re.findall(r"docs/([a-z0-9-]+\.md)", readme))

        # The bare-name sentence, found by its own wording rather than by
        # position, so it can be reworded without silently emptying this check.
        index = re.search(r"Full detail in `docs/`:(.+?)\.\n", readme, re.S)
        if index:
            listed |= set(re.findall(r"`([a-z0-9-]+\.md)`", index.group(1)))
        return listed

    def test_every_doc_is_listed(self):
        present = {path.name for path in (ROOT / "docs").glob("*.md")}
        missing = present - self._listed()
        assert not missing, f"docs exist but are not in the README index: {missing}"

    def test_every_listed_doc_exists(self):
        absent = self._listed() - {path.name for path in (ROOT / "docs").glob("*.md")}
        assert not absent, f"the README index names docs that do not exist: {absent}"

    def test_the_conversation_doc_is_indexed(self):
        """Named explicitly, so removing it from the index is a visible failure."""
        assert "conversation-memory.md" in self._listed()
