"""Agent skills structural tests (ticket #59).

The skills are markdown, so "does it work" is really two load-time
contracts: the harness discovers `.omp/skills/<name>/SKILL.md` and reads
`name` + `description` from the frontmatter, and every MCP tool the skills
teach must exist in the facade's endpoint table (src/mcp_server). A skill
that drifts from either is dead text to a fresh agent — these tests check
the skills against both sources of truth.
"""

from __future__ import annotations

import pathlib
import re

from src import mcp_server
from src.router import CONDITIONS

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / ".omp" / "skills"

WORKFLOW_SKILLS = (
    "hunting-a-product",
    "correcting-data",
    "tuning-thresholds",
    "daily-sweep",
)

REQUIRED_SECTIONS = ("## When to use", "## Tools", "## Example sequence")

TOOL_NAMES = {t["name"] for t in mcp_server._TOOLS}


def read_skill(name: str) -> tuple[dict, str]:
    """Parse the frontmatter into a dict; return (frontmatter, body)."""
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{name}: file must open with frontmatter"
    end = text.find("\n---\n", 4)
    assert end != -1, f"{name}: frontmatter is never closed"
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        assert sep, f"{name}: frontmatter line is not 'key: value' -> {line!r}"
        meta[key.strip()] = value.strip()
    return meta, text[end + 5 :]


def taught_tools(body: str) -> set:
    """Tool names from the leading cell of each row of the '## Tools' table.

    The leading cell only: backticked snake_case elsewhere in prose is a
    field name (`status`, `fair_price`), not a tool.
    """
    m = re.search(r"^## Tools\n(.*?)(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    assert m, "no '## Tools' section found"
    lead = re.compile(r"^\|\s*`([a-z][a-z0-9_]+)`\s*\|")
    found = set()
    for line in m.group(1).splitlines():
        hit = lead.match(line)
        if hit:
            found.add(hit.group(1))
    return found


def test_claude_skills_symlink_exists():
    """Claude Code reads .claude/skills; a symlink keeps one source of truth."""
    link = ROOT / ".claude" / "skills"
    assert link.is_symlink(), ".claude/skills must be a symlink to ../.omp/skills"
    assert link.resolve() == (ROOT / ".omp" / "skills").resolve()


def test_every_workflow_skill_exists():
    for name in WORKFLOW_SKILLS:
        path = SKILLS_DIR / name / "SKILL.md"
        assert path.is_file(), f"missing skill: {path}"


def test_frontmatter_names_match_directory():
    for name in WORKFLOW_SKILLS:
        meta, _ = read_skill(name)
        assert meta.get("name") == name, f"{name}: frontmatter name must equal directory"
        desc = meta.get("description", "")
        assert len(desc) >= 30, f"{name}: description too thin to route on"


def test_required_sections_present():
    for name in WORKFLOW_SKILLS:
        _, body = read_skill(name)
        for section in REQUIRED_SECTIONS:
            assert section in body, f"{name}: missing section {section!r}"


def test_tools_taught_exist():
    """Every tool the skills name is a tool the MCP facade actually exposes."""
    for name in WORKFLOW_SKILLS:
        _, body = read_skill(name)
        for tool in taught_tools(body):
            assert tool in TOOL_NAMES, f"{name}: teaches unknown tool {tool!r}"


def test_every_mcp_tool_is_taught():
    """Union of the four skills' Tools sections covers the whole facade."""
    taught: set = set()
    for name in WORKFLOW_SKILLS:
        _, body = read_skill(name)
        taught.update(taught_tools(body))
    missing = TOOL_NAMES - taught
    assert not missing, f"tools taught by no skill: {sorted(missing)}"


def test_canonical_conditions_are_stated():
    """The condition vocabulary lives in code; correcting-data must name it."""
    _, body = read_skill("correcting-data")
    for cond in CONDITIONS + ("unknown",):
        assert cond in body, f"correcting-data never mentions condition {cond!r}"


def test_search_status_flow_is_stated():
    """The hunt skill teaches the status lifecycle the server actually uses."""
    _, body = read_skill("hunting-a-product")
    for status in ("active", "running", "enriching", "complete"):
        assert status in body, f"hunting-a-product never mentions status {status!r}"
