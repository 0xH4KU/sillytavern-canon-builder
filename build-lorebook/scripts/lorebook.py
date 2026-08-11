#!/usr/bin/env python3
"""Deterministic file workflow for agent-authored Fandom lorebooks."""

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


ENTITY_TYPES = {
    "world_lore",
    "character",
    "location",
    "faction",
    "item",
    "event",
    "species",
    "other",
}
IMPORTANCE = {"core", "recommended"}
SPOILER_POLICIES = {"avoid", "balanced", "full"}
SPOILER_RISKS = {"none", "moderate", "major"}
SPOILER_TIERS = {"safe", "conditional"}
RELATIONSHIP_MODES = {"off", "targeted"}
STRATEGIES = {"keyword", "constant", "vectorized"}
TRIGGERS = {"normal", "continue", "impersonate", "swipe", "regenerate", "quiet"}
REVIEW_CHECKS = (
    "source_fidelity",
    "spoiler_safety",
    "trigger_precision",
    "continuity",
    "atomicity",
)
REVIEW_ISSUE_CATEGORIES = set(REVIEW_CHECKS) | {
    "coverage",
    "relationship_fidelity",
}
MAX_SUPPORTING_SOURCES = 3
MIN_EVIDENCE_CHARS = 32
SOURCE_MANIFEST_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
USER_AGENT = "build-lorebook-skill/1.0 (local research workflow)"

GENERIC_REVIEW_NOTES = {
    "checked",
    "ok",
    "reviewed",
    "reviewed against source text",
    "automated review",
    "automated validation pass",
    "matches exact term exactly",
    "matches keywords",
    "matches safe topic",
    "matches topic",
    "safe parent",
    "safe parent must not trigger this",
    "scope passed",
    "supported",
    "supports the claim",
    "supports this claim",
    "unrelated",
    "unrelated text",
    "valid",
}

GENERIC_TRIGGER_TEXTS = {
    "this is totally unrelated",
    "totally unrelated text",
}

EVIDENCE_STOPWORDS = {
    "and",
    "are",
    "but",
    "categories",
    "com",
    "fandom",
    "for",
    "from",
    "has",
    "https",
    "into",
    "its",
    "source",
    "that",
    "the",
    "their",
    "this",
    "was",
    "were",
    "wiki",
    "with",
}

REVEAL_BOUNDARY_MARKERS = (
    "death",
    "ending",
    "fate",
    "final form",
    "identity",
    "origin",
    "time loop",
    "timeline",
    "transformation",
    "true nature",
)

DEFAULT_SETTINGS = {
    "strategy": "keyword",
    "selective_logic": 0,
    "order": 100,
    "position": 0,
    "depth": 4,
    "role": 0,
    "probability": 100,
    "enabled": True,
    "outlet_name": "",
    "group": "",
    "group_override": False,
    "group_weight": 100,
    "scan_depth": None,
    "case_sensitive": None,
    "match_whole_words": None,
    "use_group_scoring": None,
    "automation_id": "",
    "sticky": None,
    "cooldown": None,
    "delay": None,
    "exclude_recursion": False,
    "prevent_recursion": False,
    "delay_until_recursion": 0,
    "ignore_budget": False,
    "match_persona_description": False,
    "match_character_description": False,
    "match_character_personality": False,
    "match_character_depth_prompt": False,
    "match_scenario": False,
    "match_creator_notes": False,
    "triggers": [],
}

REQUIRED_SETTINGS = {
    "strategy",
    "selective_logic",
    "order",
    "position",
    "depth",
    "role",
    "probability",
    "scan_depth",
    "case_sensitive",
    "match_whole_words",
    "triggers",
}

GENERIC_SPOILER_TERMS = {
    "avoid": (
        " dies",
        " death",
        " killed",
        " suicide",
        " murdered",
        " revealed to be",
        " true identity",
        " witch form",
        " becomes a witch",
        " final battle",
        " ending",
        " betrayal",
    ),
    "balanced": (
        " dies",
        " killed",
        " suicide",
        " murdered",
        " true identity",
        " witch form",
        " becomes a witch",
        " final battle",
        " ending",
        " final fate",
        "previously existed as",
        "rewritten universe",
        "rewritten world",
        "became the witch",
        "was the witch",
    ),
}


class WorkflowError(Exception):
    pass


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def read_jsonl(path):
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise WorkflowError(f"Missing file: {path}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"Invalid JSONL at {path}:{number}: {exc}") from exc
        if not isinstance(value, dict):
            raise WorkflowError(f"Expected an object at {path}:{number}")
        rows.append(value)
    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def canonical_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalized_text(value):
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def source_body(value):
    parts = re.split(r"\n---\s*\n", str(value), maxsplit=1)
    body = parts[1] if len(parts) == 2 else str(value)
    navigation = re.search(r"(?im)^\s*(?:navigation|v\s*[•|]\s*e)\s*$", body)
    return body[: navigation.start()] if navigation else body


def quote_contains_metadata(value):
    return any(
        re.match(
            r"^(?:#|source\s*:|categories\s*:|navigation$|v\s*[•|]\s*e$|---$)",
            line.strip(),
            re.I,
        )
        for line in str(value).splitlines()
        if line.strip()
    )


def evidence_terms(value):
    return {
        term
        for term in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", str(value).casefold())
        if term not in EVIDENCE_STOPWORDS
    }


def generic_review_note(value):
    normalized = normalized_text(value).rstrip(".")
    return len(normalized) < 8 or normalized in GENERIC_REVIEW_NOTES


def generic_trigger_text(value):
    return normalized_text(value).rstrip(".") in GENERIC_TRIGGER_TEXTS


def evidence_length(value):
    compact = re.sub(r"\s+", "", str(value))
    return len(compact) + sum(contains_cjk(character) for character in compact)


def merged_reveal_title(project, value):
    parts = [
        normalized_text(part)
        for part in re.split(r"\s(?:&|/|and)\s", str(value), flags=re.I)
    ]
    if len(parts) < 2:
        return False
    continuities = [normalized_text(value) for value in project.get("continuities", [])]
    boundary_parts = sum(
        any(marker in part for marker in REVEAL_BOUNDARY_MARKERS)
        or any(continuity and continuity in part for continuity in continuities)
        for part in parts
    )
    return boundary_parts > 1


def required_exact_spoiler_terms(project, entry):
    keywords = entry.get("keywords", [])
    secondary = entry.get("secondary_keywords", [])
    activation_values = (
        [entry.get("title", "")]
        + (keywords if isinstance(keywords, list) else [])
        + (secondary if isinstance(secondary, list) else [])
    )
    return [
        term
        for term in project.get("spoiler_blocklist", [])
        if isinstance(term, str)
        and term.strip()
        and any(
            normalized_text(term) in normalized_text(value)
            for value in activation_values
        )
    ]


def relationship_support_required(project, item):
    return (
        project.get("relationship_mode", "off") == "targeted"
        and spoiler_tier(item) == "safe"
        and item.get("importance") == "core"
        and item.get("entity_type") in {"character", "faction"}
    )


def content_sentences(value):
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？])|(?<=[.!?])\s+", str(value).strip())
        if sentence.strip()
    ]


def project_path(workspace):
    return Path(workspace).resolve() / "project.json"


def load_project(workspace):
    project = read_json(project_path(workspace))
    if not isinstance(project, dict):
        raise WorkflowError("project.json must contain an object")
    version = project.get("version", 1)
    if not _is_int(version) or version not in {1, 2, 3}:
        raise WorkflowError("project.json version must be 1, 2, or 3")
    for name in ("name", "wiki_url", "purpose", "output_language"):
        if not isinstance(project.get(name), str) or not project[name].strip():
            raise WorkflowError(f"project.json {name} must be a non-empty string")
    if project.get("spoiler_policy") not in SPOILER_POLICIES:
        raise WorkflowError("project.json has an invalid spoiler_policy")
    limits = project.get("limits")
    if not isinstance(limits, dict):
        raise WorkflowError("project.json limits must be an object")
    for name in ("max_candidates", "max_entries", "max_entry_chars"):
        value = limits.get(name)
        if not _is_int(value) or value <= 0:
            raise WorkflowError(
                f"project.json limits.{name} must be a positive integer"
            )
    coverage = project.get("coverage_minimums", {})
    if not isinstance(coverage, dict):
        raise WorkflowError("project.json coverage_minimums must be an object")
    for entity_type, minimum in coverage.items():
        if entity_type not in ENTITY_TYPES or not _is_int(minimum) or minimum < 0:
            raise WorkflowError(f"Invalid coverage minimum: {entity_type}={minimum}")
    for name in (
        "scope",
        "continuities",
        "required_titles",
        "spoiler_blocklist",
        "exclude_title_patterns",
        "exclude_category_patterns",
    ):
        value = project.get(name, [])
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise WorkflowError(f"project.json {name} must be an array of strings")
    relationship_mode = project.get("relationship_mode", "off")
    if relationship_mode not in RELATIONSHIP_MODES:
        raise WorkflowError("project.json relationship_mode must be off or targeted")
    requirements = project.get("scope_requirements", [])
    if not isinstance(requirements, list):
        raise WorkflowError("project.json scope_requirements must be an array")
    scopes = project.get("scope", [])
    if len(scopes) > 1 and version < 3:
        raise WorkflowError("multi-scope projects require project.json version 3")
    requirement_scopes = []
    continuities = set(project.get("continuities", []))
    for index, requirement in enumerate(requirements):
        label = f"project.json scope_requirements[{index}]"
        if not isinstance(requirement, dict):
            raise WorkflowError(f"{label} must be an object")
        scope = requirement.get("scope")
        if not isinstance(scope, str) or not scope.strip():
            raise WorkflowError(f"{label}.scope must be a non-empty string")
        requirement_scopes.append(scope)
        required_continuities = requirement.get("continuities")
        if not valid_string_list(required_continuities, 1, 8):
            raise WorkflowError(f"{label}.continuities must contain 1..8 strings")
        unknown_continuities = set(required_continuities) - continuities
        if unknown_continuities:
            raise WorkflowError(
                f"{label}.continuities contains unknown values: "
                + ", ".join(sorted(unknown_continuities))
            )
        required_titles = requirement.get("required_titles", [])
        if not valid_string_list(required_titles, 0, 32):
            raise WorkflowError(f"{label}.required_titles must contain 0..32 strings")
        minimums = requirement.get("coverage_minimums", {})
        if not isinstance(minimums, dict):
            raise WorkflowError(f"{label}.coverage_minimums must be an object")
        for entity_type, minimum in minimums.items():
            if entity_type not in ENTITY_TYPES or not _is_int(minimum) or minimum < 0:
                raise WorkflowError(
                    f"{label}.coverage_minimums has invalid value: "
                    f"{entity_type}={minimum}"
                )
        if not required_titles and not any(minimums.values()):
            raise WorkflowError(
                f"{label} must require at least one title or coverage minimum"
            )
        if version >= 3 and len(scopes) > 1:
            positive_types = {
                entity_type for entity_type, minimum in minimums.items() if minimum > 0
            }
            if len(required_titles) < 2:
                raise WorkflowError(
                    f"{label}.required_titles must contain at least two backbone titles"
                )
            if len(positive_types) < 2:
                raise WorkflowError(
                    f"{label}.coverage_minimums must cover at least two entity types"
                )
            if not positive_types & {"character", "faction", "species"}:
                raise WorkflowError(
                    f"{label}.coverage_minimums must include a central actor type"
                )
            if not positive_types & {
                "world_lore",
                "location",
                "item",
                "event",
                "species",
            }:
                raise WorkflowError(
                    f"{label}.coverage_minimums must include a setting or system type"
                )
    if len(requirement_scopes) != len(set(requirement_scopes)):
        raise WorkflowError("project.json scope_requirements contains duplicate scopes")
    if requirements and set(requirement_scopes) != set(scopes):
        raise WorkflowError("project.json scope_requirements must match scope")
    if version >= 3 and scopes and set(requirement_scopes) != set(scopes):
        raise WorkflowError("project.json version 3 requires every scope requirement")
    return project


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def project_version(project):
    value = project.get("version", 1)
    return value if _is_int(value) else 1


def spoiler_tier(value):
    if isinstance(value, dict):
        return value.get("spoiler_tier", "safe")
    return "safe"


def selected_source_page_ids(value):
    if not isinstance(value, dict):
        return []
    primary = value.get("page_ids", [])
    supporting = value.get("supporting_page_ids", [])
    return (primary if isinstance(primary, list) else []) + (
        supporting if isinstance(supporting, list) else []
    )


def contains_cjk(value):
    return isinstance(value, str) and bool(
        re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", value)
    )


def fandom_api_url(wiki_url):
    parsed = urlparse(wiki_url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not hostname.endswith(".fandom.com"):
        raise WorkflowError("wiki_url must be an http(s) Fandom wiki URL")
    return f"{parsed.scheme}://{parsed.netloc}/api.php"


def wiki_page_url(wiki_url, title):
    parsed = urlparse(wiki_url)
    encoded = quote(title.replace(" ", "_"), safe="():,_-'")
    return f"{parsed.scheme}://{parsed.netloc}/wiki/{encoded}"


def api_request(api_url, params, timeout=30):
    url = f"{api_url}?{urlencode(params)}"
    request = Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(attempt + 1)
    raise WorkflowError(f"Fandom API request failed: {last_error}")


def chunks(values, size):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def clean_wikitext_preview(value, limit=1200):
    value = re.sub(r"<!--.*?-->", " ", value or "", flags=re.DOTALL)
    value = re.sub(r"<ref\b[^>]*>.*?</ref>|<ref\b[^>]*/>", " ", value, flags=re.DOTALL)
    value = re.sub(
        r"\[\[(?:File|Image|Category):[^\]]+\]\]", " ", value, flags=re.IGNORECASE
    )
    for _ in range(4):
        cleaned = re.sub(r"\{\{[^{}]*\}\}", " ", value, flags=re.DOTALL)
        if cleaned == value:
            break
        value = cleaned
    value = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", value)
    value = re.sub(r"\[(?:https?://\S+)(?:\s+([^\]]+))?\]", r"\1", value)
    value = re.sub(r"<[^>]+>|'{2,}|={2,}", " ", value)
    return re.sub(r"\s+", " ", value).strip()[:limit]


def rule_decision(
    title, categories, extra_title_patterns=(), extra_category_patterns=()
):
    lowered = title.casefold()
    category_text = " ".join(categories).casefold()
    if re.search(
        r"(^|/)(image gallery|gallery|quotes?|relationships?|history|appearances?|abilities|trivia|synopsis)(/|$)",
        lowered,
    ):
        return "exclude", "Supplemental subpage."
    if re.search(
        r"\b(disambiguation|transcript|walkthrough|strategy guide|episode guide)\b|^(list|index) of ",
        lowered,
    ):
        return "exclude", "Utility, list, transcript, or guide page."
    if re.search(r"\b(episode|chapter)\s*(?:no\.?\s*)?\d+\b", lowered):
        return "exclude", "Episode or chapter page."
    if re.search(
        r"\b(maintenance|disambiguation|transcripts?|walkthroughs?|strategy guides?|"
        r"non[- ]?canon(?:ical)?|fan ?content|episodes?|episode summaries|chapters?|galleries|"
        r"songs?|soundtracks?)\b",
        category_text,
    ):
        return "exclude", "Utility, episode, chapter, or explicitly non-canon category."
    for pattern in extra_title_patterns:
        if pattern.search(title):
            return "exclude", f"Project title exclusion: {pattern.pattern}"
    for pattern in extra_category_patterns:
        if pattern.search(" ".join(categories)):
            return "exclude", f"Project category exclusion: {pattern.pattern}"
    return "keep", None


def cmd_init(args):
    workspace = Path(args.workspace).resolve()
    config_path = workspace / "project.json"
    if config_path.exists():
        raise WorkflowError(f"Refusing to overwrite existing {config_path}")
    fandom_api_url(args.wiki)
    if not args.name.strip() or not args.language.strip():
        raise WorkflowError("name and language must be non-empty")
    if min(args.max_candidates, args.max_entries, args.max_entry_chars) <= 0:
        raise WorkflowError("all limits must be positive integers")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "sources").mkdir(exist_ok=True)
    (workspace / "entries").mkdir(exist_ok=True)
    project = {
        "version": 3,
        "name": args.name,
        "wiki_url": args.wiki.rstrip("/"),
        "purpose": args.purpose or f"Build a roleplay lorebook for {args.name}.",
        "output_language": args.language,
        "spoiler_policy": args.spoiler,
        "scope": [],
        "scope_requirements": [],
        "continuities": [],
        "required_titles": [],
        "coverage_minimums": {},
        "spoiler_blocklist": [],
        "exclude_title_patterns": [],
        "exclude_category_patterns": [],
        "relationship_mode": "targeted",
        "limits": {
            "max_candidates": args.max_candidates,
            "max_entries": args.max_entries,
            "max_entry_chars": args.max_entry_chars,
        },
    }
    write_json(config_path, project)
    print(f"Initialized {workspace}")


def list_fandom_pages(api_url):
    pages = []
    continuation = None
    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": 0,
            "apfilterredir": "nonredirects",
            "aplimit": "max",
            "format": "json",
            "formatversion": 2,
        }
        if continuation:
            params["apcontinue"] = continuation
        payload = api_request(api_url, params)
        pages.extend(payload.get("query", {}).get("allpages", []))
        continuation = payload.get("continue", {}).get("apcontinue")
        if not continuation:
            return pages


def fetch_candidate_metadata(api_url, pages):
    metadata = {}
    for batch in chunks(pages, 50):
        payload = api_request(
            api_url,
            {
                "action": "query",
                "pageids": "|".join(str(page["pageid"]) for page in batch),
                "prop": "categories|info|revisions",
                "cllimit": "max",
                "rvprop": "content",
                "rvslots": "main",
                "rvsection": 0,
                "format": "json",
                "formatversion": 2,
            },
        )
        for page in payload.get("query", {}).get("pages", []):
            revisions = page.get("revisions") or []
            slot = revisions[0].get("slots", {}).get("main", {}) if revisions else {}
            content = slot.get("content") or slot.get("*") or ""
            metadata[page["pageid"]] = {
                "page_length": page.get("length"),
                "categories": sorted(
                    item["title"].removeprefix("Category:")
                    for item in page.get("categories", [])
                    if isinstance(item.get("title"), str)
                ),
                "intro": clean_wikitext_preview(content),
            }
    return metadata


def cmd_discover(args):
    workspace = Path(args.workspace).resolve()
    project = load_project(workspace)
    api_url = fandom_api_url(project["wiki_url"])
    pages = list_fandom_pages(api_url)
    try:
        extra_title_patterns = [
            re.compile(value, re.IGNORECASE)
            for value in project.get("exclude_title_patterns", [])
        ]
        extra_category_patterns = [
            re.compile(value, re.IGNORECASE)
            for value in project.get("exclude_category_patterns", [])
        ]
    except (re.error, TypeError) as exc:
        raise WorkflowError(f"Invalid exclude_title_patterns regex: {exc}") from exc
    required = {value.casefold() for value in project.get("required_titles", [])}
    metadata = fetch_candidate_metadata(api_url, pages)
    candidates = []
    for page in pages:
        title = page["title"]
        details = metadata.get(page["pageid"], {})
        categories = details.get("categories", [])
        action, reason = rule_decision(
            title, categories, extra_title_patterns, extra_category_patterns
        )
        if title.casefold() in required and action == "exclude":
            action, reason = "keep", f"Required title override; original rule: {reason}"
        candidates.append(
            {
                "page_id": page["pageid"],
                "title": title,
                "url": wiki_page_url(project["wiki_url"], title),
                "categories": categories,
                "page_length": details.get("page_length"),
                "intro": details.get("intro", ""),
                "rule_action": action,
                "rule_reason": reason,
            }
        )
    candidates.sort(key=lambda row: row["title"].casefold())
    write_jsonl(workspace / "candidates.jsonl", candidates)
    counts = Counter(row["rule_action"] for row in candidates)
    print(
        f"Discovered {len(candidates)} canonical pages: "
        f"{counts['keep']} kept, {counts['exclude']} rule-excluded."
    )
    maximum = project["limits"]["max_candidates"]
    if counts["keep"] > maximum:
        raise WorkflowError(
            f"Kept candidate pool {counts['keep']} is above max_candidates={maximum}. "
            "Inspect the written catalog, add project exclusion patterns, or explicitly raise the limit."
        )


def cmd_catalog(args):
    candidates = read_jsonl(Path(args.workspace).resolve() / "candidates.jsonl")
    actions = Counter(row.get("rule_action") for row in candidates)
    categories = Counter(
        category
        for row in candidates
        if row.get("rule_action") == "keep"
        for category in row.get("categories", [])
    )
    reasons = Counter(
        row.get("rule_reason")
        for row in candidates
        if row.get("rule_action") == "exclude"
    )
    print(f"Candidates: {len(candidates)}")
    print(f"Kept: {actions['keep']}; rule-excluded: {actions['exclude']}")
    print("Top kept categories:")
    for name, count in categories.most_common(args.top):
        print(f"  {count:4}  {name}")
    if reasons:
        print("Exclusion reasons:")
        for name, count in reasons.most_common():
            print(f"  {count:4}  {name}")


def validate_selection(project, candidates, selection):
    errors = []
    warnings = []
    if not isinstance(selection, dict):
        return ["selection.json must contain an object"], warnings, []
    selected = selection.get("selected")
    if not isinstance(selected, list):
        return ["selection.json selected must be an array"], warnings, []
    by_id = {row.get("page_id"): row for row in candidates}
    by_title = {str(row.get("title", "")).casefold(): row for row in candidates}
    seen_ids = set()
    selected_by_id = {}
    page_owners = {}
    coverage = Counter()
    kept_count = sum(row.get("rule_action") == "keep" for row in candidates)
    if kept_count > project["limits"]["max_candidates"]:
        errors.append(
            f"Kept candidate pool {kept_count} is above max_candidates="
            f"{project['limits']['max_candidates']}"
        )
    for index, item in enumerate(selected):
        label = f"selected[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        entry_id = item.get("id")
        if not isinstance(entry_id, str) or not ID_PATTERN.fullmatch(entry_id):
            errors.append(f"{label}.id must be unique ASCII kebab-case")
        elif entry_id in seen_ids:
            errors.append(f"Duplicate selected id: {entry_id}")
        else:
            seen_ids.add(entry_id)
            selected_by_id[entry_id] = item
        tier = item.get("spoiler_tier")
        if tier is None and project_version(project) == 1:
            tier = "safe"
            warnings.append(f"{label} uses legacy implicit spoiler_tier=safe")
        elif not isinstance(tier, str) or tier not in SPOILER_TIERS:
            errors.append(f"{label}.spoiler_tier must be safe or conditional")
            tier = "safe"
        parent_id = item.get("spoiler_parent_id")
        if tier == "conditional":
            if not isinstance(parent_id, str) or not ID_PATTERN.fullmatch(parent_id):
                errors.append(
                    f"{label}.spoiler_parent_id must reference a safe selected id"
                )
        elif parent_id is not None:
            errors.append(
                f"{label}.spoiler_parent_id is only valid for conditional entries"
            )
        for field in ("title", "continuity", "reason", "spoiler_reason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        if tier == "conditional" and merged_reveal_title(
            project, item.get("title", "")
        ):
            errors.append(f"{label}.title appears to merge multiple reveal boundaries")
        entity_type = item.get("entity_type")
        importance = item.get("importance")
        if not isinstance(entity_type, str) or entity_type not in ENTITY_TYPES:
            errors.append(f"{label}.entity_type is invalid")
        elif tier == "safe":
            coverage[entity_type] += 1
        if not isinstance(importance, str) or importance not in IMPORTANCE:
            errors.append(f"{label}.importance must be core or recommended")
        confidence = item.get("confidence")
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            errors.append(f"{label}.confidence must be between 0 and 1")
        elif confidence < 0.7 and not item.get("manual_override", False):
            errors.append(f"{label} has confidence below 0.7 without manual_override")
        risk = item.get("spoiler_risk")
        if not isinstance(risk, str) or risk not in SPOILER_RISKS:
            errors.append(f"{label}.spoiler_risk is invalid")
        policy = project["spoiler_policy"]
        blocked_risk = isinstance(risk, str) and (
            (policy == "avoid" and risk in {"moderate", "major"})
            or (
                policy == "balanced"
                and tier == "safe"
                and risk in {"moderate", "major"}
            )
        )
        if blocked_risk and not item.get("spoiler_override", False):
            errors.append(f"{label} has {risk} spoiler risk under {policy} policy")
        if tier == "conditional" and risk == "none":
            errors.append(f"{label} is conditional but has no spoiler risk")
        page_ids = item.get("page_ids")
        if not isinstance(page_ids, list) or not page_ids:
            errors.append(f"{label}.page_ids must be a non-empty array")
            continue
        if any(not _is_int(page_id) for page_id in page_ids):
            errors.append(f"{label}.page_ids must contain integers")
            continue
        if len(page_ids) != len(set(page_ids)):
            errors.append(f"{label}.page_ids contains duplicates")
        for page_id in page_ids:
            if not _is_int(page_id) or page_id not in by_id:
                errors.append(f"{label} references unknown page_id {page_id!r}")
                continue
            page_owners.setdefault(page_id, []).append(item)
            if by_id[page_id].get("rule_action") == "exclude" and not item.get(
                "allow_rule_excluded", False
            ):
                errors.append(
                    f"{label} uses rule-excluded page_id {page_id} without override"
                )
        supporting_ids = item.get("supporting_page_ids", [])
        if (
            not isinstance(supporting_ids, list)
            or len(supporting_ids) > MAX_SUPPORTING_SOURCES
            or any(not _is_int(page_id) for page_id in supporting_ids)
        ):
            errors.append(
                f"{label}.supporting_page_ids must contain 0..{MAX_SUPPORTING_SOURCES} integers"
            )
            continue
        if len(supporting_ids) != len(set(supporting_ids)):
            errors.append(f"{label}.supporting_page_ids contains duplicates")
        if set(page_ids) & set(supporting_ids):
            errors.append(f"{label} repeats a primary page as a supporting source")
        for page_id in supporting_ids:
            candidate = by_id.get(page_id)
            if not candidate:
                errors.append(
                    f"{label} references unknown supporting page_id {page_id!r}"
                )
                continue
            is_relationship_subpage = bool(
                re.search(r"/relationships?$", str(candidate.get("title", "")), re.I)
            )
            if (
                candidate.get("rule_action") == "exclude"
                and not is_relationship_subpage
                and not item.get("allow_rule_excluded", False)
            ):
                errors.append(
                    f"{label} uses rule-excluded supporting page_id {page_id} without override"
                )

    for index, item in enumerate(selected):
        if not isinstance(item, dict) or spoiler_tier(item) != "conditional":
            continue
        parent_id = item.get("spoiler_parent_id")
        parent = selected_by_id.get(parent_id)
        if not parent or spoiler_tier(parent) != "safe":
            errors.append(
                f"selected[{index}].spoiler_parent_id must reference a safe selected entry"
            )
    for page_id, owners in page_owners.items():
        if len(owners) < 2:
            continue
        safe_owner_ids = {
            owner.get("id") for owner in owners if spoiler_tier(owner) == "safe"
        }
        if len(safe_owner_ids) != 1:
            errors.append(
                f"page_id {page_id} is reused without exactly one safe source owner"
            )
            continue
        safe_owner_id = next(iter(safe_owner_ids))
        for owner in owners:
            if (
                spoiler_tier(owner) == "conditional"
                and owner.get("spoiler_parent_id") != safe_owner_id
            ):
                errors.append(
                    f"page_id {page_id} conditional reuse must point to {safe_owner_id}"
                )

    maximum = project["limits"]["max_entries"]
    if len(selected) > maximum:
        errors.append(f"Selected {len(selected)} entries, above max_entries={maximum}")
    if selected and not any(
        item.get("importance") == "core" and spoiler_tier(item) == "safe"
        for item in selected
        if isinstance(item, dict)
    ):
        errors.append("Selection has no core entries")
    for entity_type, minimum in project.get("coverage_minimums", {}).items():
        if coverage[entity_type] < minimum:
            errors.append(
                f"Coverage for {entity_type} is {coverage[entity_type]}, below required {minimum}"
            )
    for title in project.get("required_titles", []):
        candidate = by_title.get(title.casefold())
        if not candidate:
            errors.append(f"Required title was not discovered: {title}")
            continue
        owner = next(
            (
                item
                for item in selected
                if isinstance(item, dict)
                and spoiler_tier(item) == "safe"
                and candidate["page_id"] in item.get("page_ids", [])
            ),
            None,
        )
        if not owner:
            errors.append(f"Required title is not selected: {title}")
        elif owner.get("importance") != "core":
            errors.append(f"Required title is not core: {title}")
    for requirement in project.get("scope_requirements", []):
        scope = requirement["scope"]
        label = f"Scope {scope!r}"
        allowed_continuities = set(requirement["continuities"])
        eligible = [
            item
            for item in selected
            if isinstance(item, dict)
            and spoiler_tier(item) == "safe"
            and item.get("continuity") in allowed_continuities
        ]
        eligible_coverage = Counter(item.get("entity_type") for item in eligible)
        for entity_type, minimum in requirement.get("coverage_minimums", {}).items():
            if eligible_coverage[entity_type] < minimum:
                errors.append(
                    f"{label} coverage for {entity_type} is "
                    f"{eligible_coverage[entity_type]}, below required {minimum}"
                )
        for title in requirement.get("required_titles", []):
            candidate = by_title.get(title.casefold())
            if not candidate:
                errors.append(f"{label} required title was not discovered: {title}")
                continue
            if not any(
                candidate["page_id"] in item.get("page_ids", []) for item in eligible
            ):
                errors.append(
                    f"{label} required title is not selected as safe: {title}"
                )
    if project.get("relationship_mode", "off") == "targeted":
        for item in selected:
            if (
                isinstance(item, dict)
                and relationship_support_required(project, item)
                and not item.get("supporting_page_ids")
            ):
                warnings.append(
                    f"Core {item.get('entity_type')} {item.get('id')} has no "
                    "relationship supporting source"
                )
    manual_review = selection.get("manual_review", [])
    if not isinstance(manual_review, list):
        errors.append("selection.json manual_review must be an array")
    else:
        for index, item in enumerate(manual_review):
            if not isinstance(item, dict) or item.get("page_id") not in by_id:
                errors.append(f"manual_review[{index}] references an unknown page")
            elif not isinstance(item.get("reason"), str) or not item["reason"].strip():
                errors.append(f"manual_review[{index}].reason must be non-empty")
    safe_count = sum(
        spoiler_tier(item) == "safe" for item in selected if isinstance(item, dict)
    )
    if safe_count >= 10 and coverage["character"] / safe_count > 0.65:
        warnings.append(
            "More than 65% of selected concepts are characters; verify world coverage"
        )
    return errors, warnings, selected


class ArticleTextParser(HTMLParser):
    BLOCKS = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "li",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self):
        lines = []
        for line in unescape("".join(self.parts)).splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
        return "\n\n".join(lines)


def render_source(api_url, candidate, revision_id=None):
    target = (
        {"oldid": revision_id}
        if revision_id is not None
        else {"pageid": candidate["page_id"]}
    )
    payload = api_request(
        api_url,
        {
            "action": "parse",
            **target,
            "prop": "text|revid",
            "disableeditsection": 1,
            "disablelimitreport": 1,
            "format": "json",
            "formatversion": 2,
        },
        timeout=45,
    )
    parsed = payload.get("parse", {})
    if parsed.get("pageid") != candidate["page_id"]:
        raise WorkflowError(
            f"Revision does not belong to source page {candidate['title']}"
        )
    html = parsed.get("text")
    if isinstance(html, dict):
        html = html.get("*")
    if not isinstance(html, str) or not html:
        raise WorkflowError(f"No article text returned for {candidate['title']}")
    fetched_revision = parsed.get("revid")
    if not _is_int(fetched_revision) or fetched_revision <= 0:
        raise WorkflowError(f"No revision ID returned for {candidate['title']}")
    if revision_id is not None and fetched_revision != revision_id:
        raise WorkflowError(
            f"Expected revision {revision_id}, received {fetched_revision} "
            f"for {candidate['title']}"
        )
    parser = ArticleTextParser()
    parser.feed(html)
    content = parser.text()
    if not content:
        raise WorkflowError(
            f"No readable article text returned for {candidate['title']}"
        )
    header = (
        f"# {candidate['title']}\n\n"
        f"Source: {candidate['url']}\n"
        f"Categories: {', '.join(candidate.get('categories', []))}\n\n"
        "---\n\n"
    )
    return header + content + "\n", fetched_revision


def fetch_source(api_url, candidate, destination):
    text, revision_id = render_source(api_url, candidate)
    temporary = destination.with_suffix(".txt.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)
    return {
        "url": candidate["url"],
        "revision_id": revision_id,
        "sha256": file_sha256(destination),
    }


def empty_source_manifest(project):
    return {
        "version": SOURCE_MANIFEST_VERSION,
        "wiki_url": project["wiki_url"].rstrip("/"),
        "sources": {},
    }


def load_source_manifest(workspace, project, required=True):
    path = Path(workspace) / "source_manifest.json"
    if not path.exists():
        if required:
            raise WorkflowError("Missing source_manifest.json; run fetch")
        return empty_source_manifest(project)
    manifest = read_json(path)
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != SOURCE_MANIFEST_VERSION
        or manifest.get("wiki_url") != project["wiki_url"].rstrip("/")
        or not isinstance(manifest.get("sources"), dict)
    ):
        raise WorkflowError("source_manifest.json is invalid; run fetch --refresh")
    return manifest


def source_record_matches(path, candidate, record):
    return (
        path.exists()
        and isinstance(record, dict)
        and record.get("url") == candidate.get("url")
        and _is_int(record.get("revision_id"))
        and record["revision_id"] > 0
        and isinstance(record.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        and file_sha256(path) == record["sha256"]
    )


def validate_source_integrity(workspace, project, candidates, selected):
    errors = []
    try:
        manifest = load_source_manifest(workspace, project)
    except WorkflowError as exc:
        errors.append(str(exc))
        manifest = empty_source_manifest(project)
    by_id = {row.get("page_id"): row for row in candidates}
    page_ids = sorted(
        {page_id for item in selected for page_id in selected_source_page_ids(item)}
    )
    for page_id in page_ids:
        candidate = by_id.get(page_id, {})
        path = Path(workspace) / "sources" / f"{page_id}.txt"
        record = manifest["sources"].get(str(page_id))
        if not path.exists():
            errors.append(f"Missing cached source: sources/{page_id}.txt")
        elif not source_record_matches(path, candidate, record):
            errors.append(
                f"Cached source integrity failed: sources/{page_id}.txt; "
                "run fetch --refresh"
            )
    return errors


def verify_sources_remote(workspace, project, candidates, selected, workers=6):
    manifest = load_source_manifest(workspace, project)
    by_id = {row["page_id"]: row for row in candidates}
    page_ids = sorted(
        {page_id for item in selected for page_id in selected_source_page_ids(item)}
    )
    api_url = fandom_api_url(project["wiki_url"])
    failures = []

    def verify(page_id):
        record = manifest["sources"][str(page_id)]
        text, _ = render_source(api_url, by_id[page_id], record["revision_id"])
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != record["sha256"]:
            raise WorkflowError(
                f"revision {record['revision_id']} no longer renders to the cached text"
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(verify, page_id): page_id for page_id in page_ids}
        for future in as_completed(futures):
            page_id = futures[future]
            try:
                future.result()
            except Exception as exc:
                failures.append(f"{by_id[page_id]['title']}: {exc}")
    return sorted(failures)


def load_selection_files(workspace):
    project = load_project(workspace)
    candidates = read_jsonl(Path(workspace) / "candidates.jsonl")
    selection = read_json(Path(workspace) / "selection.json")
    errors, warnings, selected = validate_selection(project, candidates, selection)
    return project, candidates, selection, errors, warnings, selected


def cmd_fetch(args):
    workspace = Path(args.workspace).resolve()
    if args.workers < 1:
        raise WorkflowError("workers must be a positive integer")
    project, candidates, _, errors, warnings, selected = load_selection_files(workspace)
    if errors:
        print_issues(errors, warnings)
        raise WorkflowError("Selection validation failed; no sources were fetched")
    by_id = {row["page_id"]: row for row in candidates}
    page_ids = sorted(
        {page_id for item in selected for page_id in selected_source_page_ids(item)}
    )
    sources = workspace / "sources"
    sources.mkdir(exist_ok=True)
    try:
        manifest = load_source_manifest(workspace, project, required=False)
    except WorkflowError:
        if not args.refresh:
            raise
        manifest = empty_source_manifest(project)
    pending = [
        page_id
        for page_id in page_ids
        if args.refresh
        or not source_record_matches(
            sources / f"{page_id}.txt",
            by_id[page_id],
            manifest["sources"].get(str(page_id)),
        )
    ]
    if not pending:
        print(f"All {len(page_ids)} selected source pages are cached.")
        return
    api_url = fandom_api_url(project["wiki_url"])
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_source, api_url, by_id[page_id], sources / f"{page_id}.txt"
            ): page_id
            for page_id in pending
        }
        for future in as_completed(futures):
            page_id = futures[future]
            try:
                manifest["sources"][str(page_id)] = future.result()
            except Exception as exc:  # Keep successful cache files on partial failure.
                failures.append(f"{by_id[page_id]['title']}: {exc}")
    write_json(workspace / "source_manifest.json", manifest)
    print(
        f"Cached {len(pending) - len(failures)} of {len(pending)} pending source pages."
    )
    if failures:
        raise WorkflowError("Source failures:\n  " + "\n  ".join(failures))


def valid_string_list(value, minimum=0, maximum=8):
    return (
        isinstance(value, list)
        and minimum <= len(value) <= maximum
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def validate_source_evidence(workspace, entry, prefix):
    evidence = entry.get("source_evidence")
    if evidence is None:
        return []
    if not isinstance(evidence, list) or not evidence:
        return [f"{prefix}.source_evidence must be a non-empty array"]

    errors = []
    sentences = content_sentences(entry.get("content", ""))
    source_ids = set(entry.get("source_page_ids", []))
    covered = set()
    cited_source_ids = set()
    seen = set()
    source_cache = {}
    expected_fields = {"page_id", "source_quote", "supports"}
    for index, item in enumerate(evidence):
        label = f"{prefix}.source_evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(item) != expected_fields:
            errors.append(
                f"{label} fields must be: {', '.join(sorted(expected_fields))}"
            )
        page_id = item.get("page_id")
        if page_id not in source_ids:
            errors.append(f"{label}.page_id must reference an entry source")
            continue
        cited_source_ids.add(page_id)
        supports = item.get("supports")
        if (
            not isinstance(supports, list)
            or not supports
            or any(not _is_int(value) for value in supports)
            or len(supports) != len(set(supports))
        ):
            errors.append(f"{label}.supports must contain unique sentence indexes")
            supports = []
        valid_supports = []
        for sentence_index in supports:
            if sentence_index not in range(len(sentences)):
                errors.append(f"{label}.supports contains an unknown sentence index")
            else:
                valid_supports.append(sentence_index)
                covered.add(sentence_index)
        quote_value = item.get("source_quote")
        if (
            not isinstance(quote_value, str)
            or evidence_length(quote_value) < MIN_EVIDENCE_CHARS
        ):
            errors.append(
                f"{label}.source_quote must contain at least "
                f"{MIN_EVIDENCE_CHARS} characters"
            )
            continue
        if quote_contains_metadata(quote_value):
            errors.append(f"{label}.source_quote must come from article body text")
            continue
        record_key = (page_id, normalized_text(quote_value))
        if record_key in seen:
            errors.append(
                f"{label} duplicates an evidence quote; merge its supports instead"
            )
        seen.add(record_key)
        if page_id not in source_cache:
            source_path = Path(workspace) / "sources" / f"{page_id}.txt"
            try:
                source_cache[page_id] = normalized_text(
                    source_body(source_path.read_text(encoding="utf-8"))
                )
            except FileNotFoundError:
                source_cache[page_id] = ""
        if normalized_text(quote_value) not in source_cache[page_id]:
            errors.append(f"{label}.source_quote was not found in the cached source")
        supported_text = " ".join(sentences[value] for value in valid_supports)
        claim_terms = evidence_terms(supported_text)
        quote_terms = evidence_terms(quote_value)
        if claim_terms and quote_terms and not claim_terms & quote_terms:
            errors.append(
                f"{label}.source_quote has no meaningful term overlap with its claims"
            )

    for index, sentence in enumerate(sentences):
        if index not in covered:
            errors.append(
                f"{prefix}.source_evidence does not cover sentence {index}: {sentence}"
            )
    unused_sources = source_ids - cited_source_ids
    if unused_sources:
        errors.append(
            f"{prefix}.source_evidence does not use source page IDs: "
            + ", ".join(str(value) for value in sorted(unused_sources))
        )
    return errors


def validate_entry(project, selection_item, entry):
    entry_id = selection_item.get("id", "unknown")
    prefix = f"entry {entry_id}"
    errors = []
    warnings = []
    if not isinstance(entry, dict):
        return [f"{prefix} must contain an object"], warnings
    expected_tier = spoiler_tier(selection_item)
    entry_tier = entry.get("spoiler_tier")
    if entry_tier is None and project_version(project) == 1:
        entry_tier = "safe"
        warnings.append(f"{prefix} uses legacy implicit spoiler_tier=safe")
    elif not isinstance(entry_tier, str) or entry_tier not in SPOILER_TIERS:
        errors.append(f"{prefix}.spoiler_tier must be safe or conditional")
        entry_tier = "safe"
    if entry_tier != expected_tier:
        errors.append(f"{prefix}.spoiler_tier does not match its selection")
    expected_parent = selection_item.get("spoiler_parent_id")
    parent_id = entry.get("spoiler_parent_id")
    if entry_tier == "conditional":
        if parent_id != expected_parent:
            errors.append(f"{prefix}.spoiler_parent_id does not match its selection")
    elif parent_id is not None:
        errors.append(
            f"{prefix}.spoiler_parent_id is only valid for conditional entries"
        )
    for field in ("id", "title", "memo", "content", "continuity", "settings_rationale"):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            errors.append(f"{prefix}.{field} must be a non-empty string")
    if entry.get("id") != entry_id:
        errors.append(f"{prefix}.id does not match its selection")
    for field in ("entity_type", "importance", "continuity"):
        if entry.get(field) != selection_item.get(field):
            errors.append(f"{prefix}.{field} does not match its selection")
    source_page_ids = entry.get("source_page_ids")
    expected_source_ids = selected_source_page_ids(selection_item)
    if (
        not isinstance(source_page_ids, list)
        or any(not _is_int(value) for value in source_page_ids)
        or len(source_page_ids) != len(set(source_page_ids))
        or set(source_page_ids) != set(expected_source_ids)
    ):
        errors.append(
            f"{prefix}.source_page_ids must match selection primary and supporting page IDs"
        )
    maximum = project["limits"]["max_entry_chars"]
    content = entry.get("content", "")
    if isinstance(content, str) and not 80 <= len(content) <= maximum:
        errors.append(f"{prefix}.content length must be 80..{maximum} characters")
    keywords = entry.get("keywords")
    secondary = entry.get("secondary_keywords")
    settings = entry.get("settings")
    if not isinstance(settings, dict):
        errors.append(f"{prefix}.settings must be an object")
        settings = {}
    missing_settings = sorted(REQUIRED_SETTINGS - set(settings))
    if missing_settings:
        errors.append(f"{prefix}.settings is missing: {', '.join(missing_settings)}")
    unknown_settings = sorted(set(settings) - set(DEFAULT_SETTINGS))
    if unknown_settings:
        errors.append(
            f"{prefix}.settings has unknown fields: {', '.join(unknown_settings)}"
        )
    strategy = settings.get("strategy")
    if not isinstance(strategy, str) or strategy not in STRATEGIES:
        errors.append(f"{prefix}.settings.strategy is invalid")
    keyword_minimum = 1 if strategy == "keyword" else 0
    if not valid_string_list(keywords, keyword_minimum, 8):
        errors.append(
            f"{prefix}.keywords must contain {keyword_minimum}..8 non-empty strings"
        )
        keywords = []
    if not valid_string_list(secondary, 0, 8):
        errors.append(
            f"{prefix}.secondary_keywords must contain 0..8 non-empty strings"
        )
        secondary = []
    normalized_keys = [value.casefold() for value in keywords + secondary]
    if len(normalized_keys) != len(set(normalized_keys)):
        errors.append(f"{prefix} contains duplicate primary/secondary keywords")
    selective_logic = settings.get("selective_logic")
    if not _is_int(selective_logic) or selective_logic not in {0, 1, 2, 3}:
        errors.append(f"{prefix}.settings.selective_logic must be 0..3")
    for field in ("order", "depth"):
        if not _is_int(settings.get(field)) or settings[field] < 0:
            errors.append(f"{prefix}.settings.{field} must be a non-negative integer")
    if not _is_int(settings.get("position")) or settings.get("position") not in range(
        8
    ):
        errors.append(f"{prefix}.settings.position must be 0..7")
    if not _is_int(settings.get("role")) or settings.get("role") not in {0, 1, 2}:
        errors.append(f"{prefix}.settings.role must be 0..2")
    if (
        not _is_int(settings.get("probability"))
        or not 0 <= settings.get("probability", -1) <= 100
    ):
        errors.append(f"{prefix}.settings.probability must be 0..100")
    for field in ("scan_depth", "sticky", "cooldown", "delay"):
        value = settings.get(field)
        if value is not None and (not _is_int(value) or value < 0):
            errors.append(
                f"{prefix}.settings.{field} must be null or a non-negative integer"
            )
    for field in ("case_sensitive", "match_whole_words", "use_group_scoring"):
        value = settings.get(field)
        if value is not None and not isinstance(value, bool):
            errors.append(f"{prefix}.settings.{field} must be null or boolean")
    for field in (
        "enabled",
        "group_override",
        "exclude_recursion",
        "prevent_recursion",
        "ignore_budget",
        "match_persona_description",
        "match_character_description",
        "match_character_personality",
        "match_character_depth_prompt",
        "match_scenario",
        "match_creator_notes",
    ):
        if field in settings and not isinstance(settings[field], bool):
            errors.append(f"{prefix}.settings.{field} must be boolean")
    for field in ("group_weight", "delay_until_recursion"):
        if field in settings and (not _is_int(settings[field]) or settings[field] < 0):
            errors.append(f"{prefix}.settings.{field} must be a non-negative integer")
    for field in ("outlet_name", "group", "automation_id"):
        if field in settings and not isinstance(settings[field], str):
            errors.append(f"{prefix}.settings.{field} must be a string")
    triggers = settings.get("triggers")
    if not isinstance(triggers, list) or any(
        not isinstance(value, str) or value not in TRIGGERS for value in triggers
    ):
        errors.append(f"{prefix}.settings.triggers contains an invalid trigger")
    elif len(triggers) != len(set(triggers)):
        errors.append(f"{prefix}.settings.triggers contains duplicates")
    elif set(triggers) == TRIGGERS:
        errors.append(
            f"{prefix}.settings.triggers lists every trigger; use an empty array"
        )
    if (
        settings.get("position") == 7
        and not str(settings.get("outlet_name", "")).strip()
    ):
        errors.append(f"{prefix} uses outlet position without outlet_name")
    if settings.get("probability") != 100:
        warnings.append(
            f"{prefix} uses probability {settings.get('probability')}; verify randomness is intentional"
        )
    if (
        any(contains_cjk(value) for value in keywords + secondary)
        and settings.get("match_whole_words") is not False
    ):
        message = (
            f"{prefix} has CJK activation keys and must set match_whole_words=false"
        )
        if project_version(project) >= 2:
            errors.append(message)
        else:
            warnings.append(message)
    if entry_tier == "conditional":
        if merged_reveal_title(project, entry.get("title", "")):
            errors.append(f"{prefix}.title appears to merge multiple reveal boundaries")
        if not str(entry.get("memo", "")).startswith("[Spoiler]"):
            errors.append(f"{prefix}.memo must start with [Spoiler]")
        if strategy != "keyword":
            errors.append(f"{prefix} conditional spoilers must use keyword strategy")
        if settings.get("enabled", True) is not True:
            errors.append(f"{prefix} conditional spoilers must be enabled")
        if settings.get("probability") != 100:
            errors.append(f"{prefix} conditional spoilers must use probability 100")
        if settings.get("exclude_recursion") is not True:
            errors.append(
                f"{prefix} conditional spoilers must set exclude_recursion=true"
            )
        if settings.get("prevent_recursion") is not True:
            errors.append(
                f"{prefix} conditional spoilers must set prevent_recursion=true"
            )
        if settings.get("delay_until_recursion") not in {None, 0}:
            errors.append(f"{prefix} conditional spoilers cannot wait for recursion")
        if settings.get("ignore_budget") is True:
            errors.append(
                f"{prefix} conditional spoilers cannot ignore the lorebook budget"
            )
        if secondary and selective_logic not in {0, 1}:
            errors.append(
                f"{prefix} conditional secondary keywords must use AND ANY or AND ALL"
            )
        matching_sources = (
            "match_persona_description",
            "match_character_description",
            "match_character_personality",
            "match_character_depth_prompt",
            "match_scenario",
            "match_creator_notes",
        )
        if any(settings.get(field) is True for field in matching_sources):
            errors.append(
                f"{prefix} conditional spoilers cannot use additional matching sources"
            )
        for term in required_exact_spoiler_terms(project, entry):
            if not entry_activates(entry, term):
                errors.append(
                    f"{prefix} exact spoiler term must activate by itself: {term}"
                )
    review = entry.get("spoiler_review")
    if not isinstance(review, dict):
        errors.append(f"{prefix}.spoiler_review must be an object")
    else:
        if review.get("policy") != project["spoiler_policy"]:
            errors.append(f"{prefix}.spoiler_review.policy does not match project")
        if review.get("checked") is not True:
            errors.append(f"{prefix}.spoiler_review.checked must be true")
        if not isinstance(review.get("notes"), str) or not review["notes"].strip():
            errors.append(f"{prefix}.spoiler_review.notes must be non-empty")
    if (
        project["spoiler_policy"] != "full"
        and entry_tier == "safe"
        and isinstance(content, str)
    ):
        lowered = f" {content.casefold()}"
        for blocked in project.get("spoiler_blocklist", []):
            if isinstance(blocked, str) and blocked.casefold() in lowered:
                errors.append(
                    f"{prefix} contains project spoiler blocklist phrase: {blocked}"
                )
        for term in GENERIC_SPOILER_TERMS.get(project["spoiler_policy"], ()):
            if term in lowered:
                message = (
                    f"{prefix} may contain a restricted spoiler marker: {term.strip()}"
                )
                if project_version(project) >= 2:
                    errors.append(message)
                else:
                    warnings.append(message)
    return errors, warnings


def selection_artifact_hash(project, candidates, selection):
    page_ids = {
        page_id
        for item in selection.get("selected", [])
        if isinstance(item, dict)
        for page_id in selected_source_page_ids(item)
        if _is_int(page_id)
    }
    selected_candidates = sorted(
        (row for row in candidates if row.get("page_id") in page_ids),
        key=lambda row: row.get("page_id", 0),
    )
    return canonical_hash(
        {
            "project": project,
            "selection": selection,
            "selected_candidates": selected_candidates,
        }
    )


def entry_artifact_hash(workspace, project, entry):
    sources = []
    for page_id in entry.get("source_page_ids", []):
        path = Path(workspace) / "sources" / f"{page_id}.txt"
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            content = None
        sources.append({"page_id": page_id, "content": content})
    return canonical_hash(
        {
            "entry": entry,
            "sources": sources,
            "review_policy": {
                "relationship_mode": project.get("relationship_mode", "off"),
                "spoiler_blocklist": project.get("spoiler_blocklist", []),
                "spoiler_policy": project.get("spoiler_policy"),
            },
        }
    )


def keyword_matches(text, keyword, case_sensitive=False, whole_words=False):
    # ponytail: model static keyword gates; use SillyTavern's matcher only if parity tests diverge.
    flags = 0 if case_sensitive else re.IGNORECASE
    if whole_words:
        return bool(re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text, flags))
    if case_sensitive:
        return keyword in text
    return keyword.casefold() in text.casefold()


def entry_activates(entry, text):
    settings = entry.get("settings", {})
    if settings.get("strategy") != "keyword":
        return settings.get("strategy") == "constant"
    case_sensitive = settings.get("case_sensitive") is True
    whole_words = settings.get("match_whole_words") is True
    primary = [
        keyword_matches(text, key, case_sensitive, whole_words)
        for key in entry.get("keywords", [])
    ]
    if not any(primary):
        return False
    secondary = [
        keyword_matches(text, key, case_sensitive, whole_words)
        for key in entry.get("secondary_keywords", [])
    ]
    if not secondary:
        return True
    logic = settings.get("selective_logic", 0)
    if logic == 0:
        return any(secondary)
    if logic == 1:
        return all(secondary)
    if logic == 2:
        return not any(secondary)
    return not all(secondary)


def pending_entry_review(workspace, project, entry):
    return {
        "id": entry["id"],
        "artifact_hash": entry_artifact_hash(workspace, project, entry),
        "status": "pending",
        "checks": {name: "pending" for name in REVIEW_CHECKS},
        "claims": [
            {
                "claim": sentence,
                "verdict": "pending",
                "page_id": None,
                "source_quote": "",
                "notes": "",
            }
            for sentence in content_sentences(entry["content"])
        ],
        "exact_spoiler_terms": required_exact_spoiler_terms(project, entry),
        "trigger_tests": [],
        "notes": "",
    }


def pending_selection_review(project, candidates, selection):
    return {
        "artifact_hash": selection_artifact_hash(project, candidates, selection),
        "status": "pending",
        "scope_reviews": [
            {
                "scope": scope,
                "status": "pending",
                "covered_entry_ids": [],
                "missing": [],
                "notes": "",
            }
            for scope in project.get("scope", [])
        ],
        "notes": "",
    }


def pending_entry_review_v2(workspace, project, entry):
    return {
        "id": entry["id"],
        "artifact_hash": entry_artifact_hash(workspace, project, entry),
        "status": "pending",
        "issues": [],
        "risk_tests": [],
    }


def pending_selection_review_v2(project, candidates, selection):
    return {
        "artifact_hash": selection_artifact_hash(project, candidates, selection),
        "status": "pending",
        "issues": [],
    }


def validate_review_issues(value, status, prefix):
    errors = []
    if not isinstance(value, list):
        return [f"{prefix}.issues must be an array"]
    if status == "pass" and value:
        errors.append(f"{prefix}.issues must be empty when status is pass")
    if status == "fail" and not value:
        errors.append(f"{prefix}.issues must explain a failed review")
    for index, issue in enumerate(value):
        label = f"{prefix}.issues[{index}]"
        if not isinstance(issue, dict):
            errors.append(f"{label} must be an object")
            continue
        expected = {"category", "message", "targets"}
        if set(issue) != expected:
            errors.append(f"{label} fields must be: {', '.join(sorted(expected))}")
        if issue.get("category") not in REVIEW_ISSUE_CATEGORIES:
            errors.append(f"{label}.category is invalid")
        if not isinstance(issue.get("message"), str) or generic_review_note(
            issue.get("message", "")
        ):
            errors.append(f"{label}.message must describe a specific defect")
        if not valid_string_list(issue.get("targets"), 1, 8):
            errors.append(f"{label}.targets must contain 1..8 artifact locations")
    return errors


def validate_generated_trigger_rules(project, entry, parent_entry, prefix):
    if entry.get("settings", {}).get("strategy") != "keyword":
        return []
    errors = []
    primary = entry.get("keywords", [])
    secondary = entry.get("secondary_keywords", [])
    logic = entry.get("settings", {}).get("selective_logic", 0)

    def check(text, expected, label):
        actual = entry_activates(entry, text)
        if actual != expected:
            errors.append(
                f"{prefix} generated trigger check {label} expected "
                f"activation={str(expected).lower()} but got {str(actual).lower()}"
            )

    for key in primary:
        if not secondary:
            check(key, True, repr(key))
        elif logic == 0:
            check(key, False, f"primary-only {key!r}")
            for secondary_key in secondary:
                check(
                    f"{key} {secondary_key}",
                    True,
                    f"AND ANY {key!r} + {secondary_key!r}",
                )
        elif logic == 1:
            check(key, False, f"primary-only {key!r}")
            if len(secondary) > 1:
                for secondary_key in secondary:
                    check(
                        f"{key} {secondary_key}",
                        False,
                        f"partial AND ALL {key!r} + {secondary_key!r}",
                    )
            check(
                " ".join([key, *secondary]),
                True,
                f"AND ALL for {key!r}",
            )
        elif logic == 2:
            check(key, True, f"primary-only {key!r}")
            for secondary_key in secondary:
                check(
                    f"{key} {secondary_key}",
                    False,
                    f"NOT ANY {key!r} + {secondary_key!r}",
                )
        elif logic == 3:
            check(key, True, f"primary-only {key!r}")
            if len(secondary) > 1:
                for secondary_key in secondary:
                    check(
                        f"{key} {secondary_key}",
                        True,
                        f"partial NOT ALL {key!r} + {secondary_key!r}",
                    )
            check(
                " ".join([key, *secondary]),
                False,
                f"NOT ALL for {key!r}",
            )
    for secondary_key in secondary:
        check(secondary_key, False, f"secondary-only {secondary_key!r}")
    for term in required_exact_spoiler_terms(project, entry):
        check(term, True, f"exact spoiler term {term!r}")

    if entry.get("spoiler_tier") == "conditional" and parent_entry:
        normalized_primary = {normalized_text(value) for value in primary}
        parent_keys = {
            normalized_text(value) for value in parent_entry.get("keywords", [])
        }
        if normalized_primary & parent_keys:
            if not normalized_primary <= parent_keys:
                errors.append(
                    f"{prefix} mixes safe-parent and distinct spoiler primary keys"
                )
            if not secondary:
                errors.append(
                    f"{prefix} parent-intent activation requires secondary keywords"
                )
        elif secondary:
            errors.append(
                f"{prefix} exact-name activation cannot use secondary keywords"
            )
    return errors


def validate_risk_tests(entry, tests, prefix):
    if entry.get("settings", {}).get("strategy") != "keyword":
        if tests not in (None, []):
            return [f"{prefix}.risk_tests must be empty for non-keyword entries"]
        return []
    if not isinstance(tests, list):
        return [f"{prefix}.risk_tests must be an array"]
    errors = []
    seen = set()
    for index, test in enumerate(tests):
        label = f"{prefix}.risk_tests[{index}]"
        if not isinstance(test, dict):
            errors.append(f"{label} must be an object")
            continue
        if set(test) != {"text", "expected", "reason"}:
            errors.append(f"{label} fields must be: expected, reason, text")
        text = test.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{label}.text must be non-empty")
            continue
        normalized = normalized_text(text)
        if normalized in seen:
            errors.append(f"{prefix}.risk_tests contains duplicate text")
        seen.add(normalized)
        if generic_trigger_text(text):
            errors.append(f"{label}.text must be a realistic entry-specific example")
        expected = test.get("expected")
        if not isinstance(expected, bool):
            errors.append(f"{label}.expected must be boolean")
            continue
        if not isinstance(test.get("reason"), str) or generic_review_note(
            test.get("reason", "")
        ):
            errors.append(f"{label}.reason must explain the ambiguity being tested")
        actual = entry_activates(entry, text)
        if actual != expected:
            errors.append(
                f"{label} expected activation={str(expected).lower()} but got "
                f"{str(actual).lower()}"
            )
    return errors


def validate_trigger_tests(project, entry, review, parent_entry, prefix):
    errors = []
    tests = review.get("trigger_tests")
    if entry.get("settings", {}).get("strategy") != "keyword":
        if tests not in (None, []):
            errors.append(
                f"{prefix}.trigger_tests must be empty for non-keyword entries"
            )
        return errors
    if not isinstance(tests, list):
        return [f"{prefix}.trigger_tests must be an array"]
    minimum = 2 if entry.get("spoiler_tier") == "conditional" else 1
    positive = 0
    negative = 0
    seen_text = set()
    for index, test in enumerate(tests):
        label = f"{prefix}.trigger_tests[{index}]"
        if not isinstance(test, dict):
            errors.append(f"{label} must be an object")
            continue
        text = test.get("text")
        expected = test.get("expected")
        reason = test.get("reason")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{label}.text must be non-empty")
            continue
        normalized = normalized_text(text)
        if normalized in seen_text:
            errors.append(f"{prefix} contains duplicate trigger test text")
        seen_text.add(normalized)
        if generic_trigger_text(text):
            errors.append(f"{label}.text must be a realistic entry-specific example")
        if not isinstance(expected, bool):
            errors.append(f"{label}.expected must be boolean")
            continue
        if not isinstance(reason, str) or generic_review_note(reason):
            errors.append(f"{label}.reason must explain this specific test")
        actual = entry_activates(entry, text)
        if actual != expected:
            errors.append(
                f"{label} expected activation={str(expected).lower()} but got "
                f"{str(actual).lower()}"
            )
        if expected:
            positive += 1
        else:
            negative += 1
    if positive < minimum or negative < minimum:
        errors.append(
            f"{prefix} requires at least {minimum} positive and {minimum} negative trigger tests"
        )

    exact_terms = review.get("exact_spoiler_terms")
    if not valid_string_list(exact_terms, 0, 8):
        errors.append(f"{prefix}.exact_spoiler_terms must contain 0..8 strings")
        exact_terms = []
    if entry.get("spoiler_tier") != "conditional" and exact_terms:
        errors.append(
            f"{prefix}.exact_spoiler_terms is only valid for conditional entries"
        )
    required_terms = required_exact_spoiler_terms(project, entry)
    required_normalized = {normalized_text(term): term for term in required_terms}
    actual_normalized = {normalized_text(term): term for term in exact_terms}
    if len(actual_normalized) != len(exact_terms):
        errors.append(f"{prefix}.exact_spoiler_terms contains duplicates")
    missing_terms = required_normalized.keys() - actual_normalized.keys()
    unexpected_terms = actual_normalized.keys() - required_normalized.keys()
    for normalized in sorted(missing_terms):
        errors.append(
            f"{prefix} omits required exact spoiler term: "
            f"{required_normalized[normalized]}"
        )
    for normalized in sorted(unexpected_terms):
        errors.append(
            f"{prefix} contains unexpected exact spoiler term: "
            f"{actual_normalized[normalized]}"
        )
    for term in exact_terms:
        if not any(
            isinstance(test, dict)
            and test.get("expected") is True
            and normalized_text(test.get("text", "")) == normalized_text(term)
            for test in tests
        ):
            errors.append(
                f"{prefix} exact spoiler term lacks a standalone positive test: {term}"
            )

    if entry.get("spoiler_tier") == "conditional" and parent_entry:
        primary = {normalized_text(value) for value in entry.get("keywords", [])}
        parent_keys = {
            normalized_text(value) for value in parent_entry.get("keywords", [])
        }
        secondary = entry.get("secondary_keywords", [])
        if primary & parent_keys:
            if not primary <= parent_keys:
                errors.append(
                    f"{prefix} mixes safe-parent and distinct spoiler primary keys"
                )
            if not secondary:
                errors.append(
                    f"{prefix} parent-intent activation requires secondary keywords"
                )
            if not any(
                isinstance(test, dict)
                and test.get("expected") is False
                and any(
                    keyword_matches(
                        test.get("text", ""),
                        key,
                        entry.get("settings", {}).get("case_sensitive") is True,
                        entry.get("settings", {}).get("match_whole_words") is True,
                    )
                    for key in parent_entry.get("keywords", [])
                )
                for test in tests
            ):
                errors.append(
                    f"{prefix} needs a negative test containing a safe-parent key"
                )
        elif secondary:
            errors.append(
                f"{prefix} exact-name activation cannot use secondary keywords"
            )
    return errors


def validate_review_v1(
    workspace, project, candidates, selection, selected, entries_by_id
):
    errors = []
    warnings = []
    stats = {"reviewed": 0}
    selected_by_id = {
        item.get("id"): item for item in selected if isinstance(item, dict)
    }
    path = Path(workspace) / "review.json"
    if not path.exists():
        return (
            ["Missing review.json; run review-init and complete independent review"],
            warnings,
            stats,
        )
    try:
        review = read_json(path)
    except WorkflowError as exc:
        return [str(exc)], warnings, stats
    if not isinstance(review, dict) or review.get("version") != 1:
        return ["review.json must be a version 1 object"], warnings, stats

    selection_review = review.get("selection")
    if not isinstance(selection_review, dict):
        errors.append("review.selection must be an object")
    else:
        expected_hash = selection_artifact_hash(project, candidates, selection)
        if selection_review.get("artifact_hash") != expected_hash:
            errors.append("review.selection is stale; rerun review-init")
        if selection_review.get("status") != "pass":
            errors.append("review.selection.status must be pass")
        if not isinstance(selection_review.get("notes"), str) or generic_review_note(
            selection_review["notes"]
        ):
            errors.append(
                "review.selection.notes must contain a specific review result"
            )
        scope_reviews = selection_review.get("scope_reviews")
        if not isinstance(scope_reviews, list):
            errors.append("review.selection.scope_reviews must be an array")
            scope_reviews = []
        expected_scopes = project.get("scope", [])
        actual_scopes = [
            item.get("scope") for item in scope_reviews if isinstance(item, dict)
        ]
        if len(actual_scopes) != len(set(actual_scopes)):
            errors.append("review.selection.scope_reviews contains duplicate scopes")
        if set(actual_scopes) != set(expected_scopes):
            errors.append("review.selection.scope_reviews must match project scope")
        safe_ids = {
            item.get("id")
            for item in selected
            if isinstance(item, dict) and spoiler_tier(item) == "safe"
        }
        requirements_by_scope = {
            item["scope"]: item for item in project.get("scope_requirements", [])
        }
        candidates_by_title = {
            str(row.get("title", "")).casefold(): row for row in candidates
        }
        covered_sets = {}
        for index, scope_review in enumerate(scope_reviews):
            label = f"review.selection.scope_reviews[{index}]"
            if not isinstance(scope_review, dict):
                errors.append(f"{label} must be an object")
                continue
            if scope_review.get("status") != "pass":
                errors.append(f"{label}.status must be pass")
            covered = scope_review.get("covered_entry_ids")
            if not isinstance(covered, list) or not covered:
                errors.append(f"{label}.covered_entry_ids must be non-empty")
                covered = []
            elif any(not isinstance(value, str) for value in covered) or len(
                covered
            ) != len(set(covered)):
                errors.append(
                    f"{label}.covered_entry_ids must contain unique entry IDs"
                )
            requirement = requirements_by_scope.get(scope_review.get("scope"))
            allowed_ids = safe_ids
            if requirement:
                allowed_continuities = set(requirement["continuities"])
                allowed_ids = {
                    entry_id
                    for entry_id, selected_item in selected_by_id.items()
                    if spoiler_tier(selected_item) == "safe"
                    and selected_item.get("continuity") in allowed_continuities
                }
            if any(value not in allowed_ids for value in covered):
                errors.append(
                    f"{label}.covered_entry_ids must reference safe entries in scope"
                )
            if covered:
                coverage_key = frozenset(covered)
                previous_scope = covered_sets.get(coverage_key)
                if previous_scope is not None:
                    errors.append(
                        f"{label}.covered_entry_ids duplicates coverage for "
                        f"scope {previous_scope!r}"
                    )
                else:
                    covered_sets[coverage_key] = scope_review.get("scope")
            if requirement:
                covered_items = [
                    selected_by_id[value]
                    for value in covered
                    if value in selected_by_id and value in allowed_ids
                ]
                covered_types = Counter(
                    item.get("entity_type") for item in covered_items
                )
                for entity_type, minimum in requirement.get(
                    "coverage_minimums", {}
                ).items():
                    if covered_types[entity_type] < minimum:
                        errors.append(
                            f"{label} covers {covered_types[entity_type]} "
                            f"{entity_type} entries, below required {minimum}"
                        )
                for title in requirement.get("required_titles", []):
                    candidate = candidates_by_title.get(title.casefold())
                    if not candidate or not any(
                        candidate.get("page_id") in item.get("page_ids", [])
                        for item in covered_items
                    ):
                        errors.append(f"{label} does not cover required title: {title}")
            missing = scope_review.get("missing")
            if not isinstance(missing, list) or any(
                not isinstance(value, str) for value in missing
            ):
                errors.append(f"{label}.missing must be an array of strings")
            elif missing:
                errors.append(f"{label}.missing must be empty before approval")
            if not isinstance(scope_review.get("notes"), str) or generic_review_note(
                scope_review["notes"]
            ):
                errors.append(f"{label}.notes must contain a specific review result")

    entry_reviews = review.get("entries")
    if not isinstance(entry_reviews, list):
        errors.append("review.entries must be an array")
        entry_reviews = []
    review_by_id = {}
    for index, item in enumerate(entry_reviews):
        if not isinstance(item, dict):
            errors.append(f"review.entries[{index}] must be an object")
            continue
        entry_id = item.get("id")
        if entry_id in review_by_id:
            errors.append(f"Duplicate review entry id: {entry_id}")
        review_by_id[entry_id] = item
    expected_ids = {item.get("id") for item in selected if isinstance(item, dict)}
    if set(review_by_id) != expected_ids:
        errors.append("review.entries IDs must exactly match selected entry IDs")

    for entry_id in sorted(expected_ids):
        entry = entries_by_id.get(entry_id)
        item = review_by_id.get(entry_id)
        if not entry or not item:
            continue
        prefix = f"review entry {entry_id}"
        if item.get("artifact_hash") != entry_artifact_hash(workspace, project, entry):
            errors.append(f"{prefix} is stale; rerun review-init")
        if item.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        checks = item.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"{prefix}.checks must be an object")
        else:
            for name in REVIEW_CHECKS:
                if checks.get(name) != "pass":
                    errors.append(f"{prefix}.checks.{name} must be pass")
        if not isinstance(item.get("notes"), str) or generic_review_note(item["notes"]):
            errors.append(f"{prefix}.notes must contain a specific review result")

        sentences = {
            normalized_text(sentence): sentence
            for sentence in content_sentences(entry.get("content", ""))
        }
        claims = item.get("claims")
        covered_claims = set()
        if not isinstance(claims, list) or not claims:
            errors.append(f"{prefix}.claims must be a non-empty array")
            claims = []
        source_ids = set(entry.get("source_page_ids", []))
        source_cache = {}
        cited_source_ids = set()
        quote_claims = {}
        for index, claim in enumerate(claims):
            label = f"{prefix}.claims[{index}]"
            if not isinstance(claim, dict):
                errors.append(f"{label} must be an object")
                continue
            claim_text = claim.get("claim")
            normalized_claim = normalized_text(claim_text)
            if not isinstance(claim_text, str) or normalized_claim not in sentences:
                errors.append(f"{label}.claim must exactly match a content sentence")
            else:
                covered_claims.add(normalized_claim)
            if claim.get("verdict") != "supported":
                errors.append(f"{label}.verdict must be supported")
            if not isinstance(claim.get("notes"), str) or generic_review_note(
                claim["notes"]
            ):
                errors.append(f"{label}.notes must explain the evidence")
            page_id = claim.get("page_id")
            if page_id not in source_ids:
                errors.append(f"{label}.page_id must reference an entry source")
                continue
            cited_source_ids.add(page_id)
            quote = claim.get("source_quote")
            if (
                not isinstance(quote, str)
                or evidence_length(quote) < MIN_EVIDENCE_CHARS
            ):
                errors.append(
                    f"{label}.source_quote must contain at least "
                    f"{MIN_EVIDENCE_CHARS} characters"
                )
                continue
            if quote_contains_metadata(quote):
                errors.append(f"{label}.source_quote must come from article body text")
                continue
            normalized_quote = normalized_text(quote)
            previous_claim = quote_claims.get(normalized_quote)
            if previous_claim is not None and previous_claim != normalized_claim:
                errors.append(f"{label}.source_quote is reused for a different claim")
            else:
                quote_claims[normalized_quote] = normalized_claim
            claim_terms = evidence_terms(claim_text)
            quote_terms = evidence_terms(quote)
            if claim_terms and quote_terms and not claim_terms & quote_terms:
                errors.append(
                    f"{label}.source_quote has no meaningful term overlap with claim"
                )
            if page_id not in source_cache:
                source_path = Path(workspace) / "sources" / f"{page_id}.txt"
                try:
                    source_cache[page_id] = normalized_text(
                        source_body(source_path.read_text(encoding="utf-8"))
                    )
                except FileNotFoundError:
                    source_cache[page_id] = ""
            if normalized_quote not in source_cache[page_id]:
                errors.append(
                    f"{label}.source_quote was not found in the cached source"
                )
        for normalized, sentence in sentences.items():
            if normalized not in covered_claims:
                errors.append(f"{prefix} has an unreviewed sentence: {sentence}")

        selection_item = selected_by_id.get(entry_id, {})
        supporting_ids = set(selection_item.get("supporting_page_ids", []))
        unused_supporting = supporting_ids - cited_source_ids
        if unused_supporting:
            errors.append(
                f"{prefix} does not cite supporting source IDs: "
                + ", ".join(str(value) for value in sorted(unused_supporting))
            )
        if (
            relationship_support_required(project, selection_item)
            and not supporting_ids
        ):
            errors.append(
                f"{prefix} requires a relationship supporting source in targeted mode"
            )

        parent_entry = entries_by_id.get(entry.get("spoiler_parent_id"))
        errors.extend(
            validate_trigger_tests(project, entry, item, parent_entry, prefix)
        )
        if not any(value.startswith(prefix) for value in errors):
            stats["reviewed"] += 1
    return errors, warnings, stats


def validate_review_v2(
    workspace, project, candidates, selection, selected, entries_by_id
):
    errors = []
    warnings = []
    stats = {"reviewed": 0}
    review = read_json(Path(workspace) / "review.json")

    selection_review = review.get("selection")
    if not isinstance(selection_review, dict):
        errors.append("review.selection must be an object")
    else:
        expected_hash = selection_artifact_hash(project, candidates, selection)
        if selection_review.get("artifact_hash") != expected_hash:
            errors.append("review.selection is stale; rerun review-init")
        status = selection_review.get("status")
        if status != "pass":
            errors.append("review.selection.status must be pass")
        errors.extend(
            validate_review_issues(
                selection_review.get("issues"), status, "review.selection"
            )
        )

    entry_reviews = review.get("entries")
    if not isinstance(entry_reviews, list):
        errors.append("review.entries must be an array")
        entry_reviews = []
    review_by_id = {}
    for index, item in enumerate(entry_reviews):
        if not isinstance(item, dict):
            errors.append(f"review.entries[{index}] must be an object")
            continue
        entry_id = item.get("id")
        if entry_id in review_by_id:
            errors.append(f"Duplicate review entry id: {entry_id}")
        review_by_id[entry_id] = item
    expected_ids = {item.get("id") for item in selected if isinstance(item, dict)}
    if set(review_by_id) != expected_ids:
        errors.append("review.entries IDs must exactly match selected entry IDs")

    for entry_id in sorted(expected_ids):
        entry = entries_by_id.get(entry_id)
        item = review_by_id.get(entry_id)
        if not entry or not item:
            continue
        prefix = f"review entry {entry_id}"
        before = len(errors)
        if "source_evidence" not in entry:
            errors.append(f"{prefix} requires draft source_evidence for review v2")
        if item.get("artifact_hash") != entry_artifact_hash(workspace, project, entry):
            errors.append(f"{prefix} is stale; rerun review-init")
        status = item.get("status")
        if status != "pass":
            errors.append(f"{prefix}.status must be pass")
        errors.extend(validate_review_issues(item.get("issues"), status, prefix))
        parent_entry = entries_by_id.get(entry.get("spoiler_parent_id"))
        errors.extend(
            validate_generated_trigger_rules(project, entry, parent_entry, prefix)
        )
        errors.extend(validate_risk_tests(entry, item.get("risk_tests"), prefix))
        if len(errors) == before:
            stats["reviewed"] += 1
    return errors, warnings, stats


def validate_review(workspace, project, candidates, selection, selected, entries_by_id):
    path = Path(workspace) / "review.json"
    if not path.exists():
        return (
            ["Missing review.json; run review-init and complete independent review"],
            [],
            {"reviewed": 0},
        )
    try:
        review = read_json(path)
    except WorkflowError as exc:
        return [str(exc)], [], {"reviewed": 0}
    version = review.get("version") if isinstance(review, dict) else None
    if version == 1:
        return validate_review_v1(
            workspace, project, candidates, selection, selected, entries_by_id
        )
    if version == 2:
        return validate_review_v2(
            workspace, project, candidates, selection, selected, entries_by_id
        )
    return ["review.json must be a version 1 or 2 object"], [], {"reviewed": 0}


def validate_workspace(workspace, stage="auto"):
    workspace = Path(workspace).resolve()
    project, candidates, selection, errors, warnings, selected = load_selection_files(
        workspace
    )
    entries_dir = workspace / "entries"
    entry_paths = sorted(entries_dir.glob("*.json")) if entries_dir.exists() else []
    if stage == "auto":
        stage = "entries" if entry_paths else "selection"
    stats = {
        "stage": stage,
        "candidates": len(candidates),
        "selected": len(selected),
        "core": sum(
            item.get("importance") == "core"
            for item in selected
            if isinstance(item, dict)
        ),
        "conditional": sum(
            spoiler_tier(item) == "conditional"
            for item in selected
            if isinstance(item, dict)
        ),
        "manual_review": len(selection.get("manual_review", []))
        if isinstance(selection, dict)
        else 0,
        "entries": len(entry_paths),
    }
    if stage == "selection":
        return errors, warnings, stats
    errors.extend(validate_source_integrity(workspace, project, candidates, selected))
    selected_by_id = {
        item.get("id"): item for item in selected if isinstance(item, dict)
    }
    entries = []
    entries_by_id = {}
    for entry_id, item in selected_by_id.items():
        path = entries_dir / f"{entry_id}.json"
        if not path.exists():
            errors.append(f"Missing selected entry file: entries/{entry_id}.json")
            continue
        try:
            entry = read_json(path)
        except WorkflowError as exc:
            errors.append(str(exc))
            continue
        entry_errors, entry_warnings = validate_entry(project, item, entry)
        errors.extend(entry_errors)
        warnings.extend(entry_warnings)
        errors.extend(validate_source_evidence(workspace, entry, f"entry {entry_id}"))
        entries.append(entry)
        entries_by_id[entry_id] = entry
    evidence_count = sum("source_evidence" in entry for entry in entries)
    if evidence_count not in {0, len(entries)}:
        errors.append(
            "Entries must either all use source_evidence for review v2 or all use the legacy review"
        )
    for path in entry_paths:
        if path.stem not in selected_by_id:
            warnings.append(
                f"Unselected entry file will not be packed: entries/{path.name}"
            )
    for field in ("title", "memo"):
        duplicates = [
            value
            for value, count in Counter(
                str(entry.get(field, "")).strip().casefold()
                for entry in entries
                if entry.get(field)
            ).items()
            if count > 1
        ]
        if duplicates:
            errors.append(f"Duplicate entry {field} values: {', '.join(duplicates)}")
    contents = Counter(
        str(entry.get("content", "")).strip()
        for entry in entries
        if entry.get("content")
    )
    if any(count > 1 for count in contents.values()):
        errors.append("Two or more entries have identical content")
    safe_keys = {
        value.casefold()
        for entry in entries
        if entry.get("spoiler_tier", "safe") == "safe"
        for value in entry.get("keywords", [])
        if isinstance(value, str)
    }
    for entry in entries:
        if entry.get("spoiler_tier", "safe") != "conditional":
            continue
        primary = {
            value.casefold()
            for value in entry.get("keywords", [])
            if isinstance(value, str)
        }
        if primary & safe_keys and not entry.get("secondary_keywords"):
            errors.append(
                f"entry {entry.get('id', 'unknown')} reuses safe keys without "
                "conditional secondary keywords"
            )
    if entries and evidence_count == len(entries):
        for entry in entries:
            parent_entry = entries_by_id.get(entry.get("spoiler_parent_id"))
            errors.extend(
                validate_generated_trigger_rules(
                    project,
                    entry,
                    parent_entry,
                    f"entry {entry.get('id', 'unknown')}",
                )
            )
    if len(entries) >= 5:
        fingerprints = Counter(
            tuple(
                json.dumps(entry.get("settings", {}).get(key), sort_keys=True)
                for key in sorted(REQUIRED_SETTINGS)
            )
            for entry in entries
        )
        if len(fingerprints) == 1:
            warnings.append(
                "All entries use identical reviewed settings; verify this is intentional"
            )
    if stage == "review":
        review_errors, review_warnings, review_stats = validate_review(
            workspace,
            project,
            candidates,
            selection,
            selected,
            entries_by_id,
        )
        errors.extend(review_errors)
        warnings.extend(review_warnings)
        stats.update(review_stats)
    return errors, warnings, stats


def print_issues(errors, warnings, stats=None):
    if stats:
        print(
            "Validation: "
            + ", ".join(f"{name}={value}" for name, value in stats.items())
        )
    for value in errors:
        print(f"ERROR: {value}")
    for value in warnings:
        print(f"WARN: {value}")
    if not errors:
        print(f"OK: no validation errors ({len(warnings)} warnings)")


def cmd_validate(args):
    errors, warnings, stats = validate_workspace(args.workspace, args.stage)
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError(f"Validation failed with {len(errors)} error(s)")


def cmd_review_init(args):
    workspace = Path(args.workspace).resolve()
    errors, warnings, stats = validate_workspace(workspace, "entries")
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError("Entry validation failed; review template was not created")
    project, candidates, selection, _, _, selected = load_selection_files(workspace)
    entries = {
        item["id"]: read_json(workspace / "entries" / f"{item['id']}.json")
        for item in selected
    }
    review_version = (
        2 if all("source_evidence" in entry for entry in entries.values()) else 1
    )
    review_path = workspace / "review.json"
    previous = {}
    if review_path.exists() and not args.reset:
        previous = read_json(review_path)
        if not isinstance(previous, dict) or previous.get("version") != review_version:
            previous = {}

    selection_review = (
        pending_selection_review_v2(project, candidates, selection)
        if review_version == 2
        else pending_selection_review(project, candidates, selection)
    )
    old_selection = previous.get("selection")
    if (
        isinstance(old_selection, dict)
        and old_selection.get("artifact_hash") == selection_review["artifact_hash"]
    ):
        selection_review = old_selection

    old_entries = {
        item.get("id"): item
        for item in previous.get("entries", [])
        if isinstance(item, dict)
    }
    reviews = []
    preserved = 0
    for item in selected:
        pending = (
            pending_entry_review_v2(workspace, project, entries[item["id"]])
            if review_version == 2
            else pending_entry_review(workspace, project, entries[item["id"]])
        )
        old = old_entries.get(item["id"])
        if (
            isinstance(old, dict)
            and old.get("artifact_hash") == pending["artifact_hash"]
        ):
            reviews.append(old)
            preserved += 1
        else:
            reviews.append(pending)
    write_json(
        review_path,
        {
            "version": review_version,
            "selection": selection_review,
            "entries": reviews,
        },
    )
    print(
        f"Initialized review v{review_version} at {review_path}: "
        f"{preserved} preserved, "
        f"{len(reviews) - preserved} pending."
    )


def packed_entry(entry, candidates_by_id, uid):
    settings = dict(DEFAULT_SETTINGS)
    settings.update(entry["settings"])
    sources = [candidates_by_id[page_id]["url"] for page_id in entry["source_page_ids"]]
    secondary = entry["secondary_keywords"]
    return {
        "uid": uid,
        "displayIndex": uid,
        "key": entry["keywords"],
        "keysecondary": secondary,
        "comment": entry["memo"],
        "content": entry["content"],
        "constant": settings["strategy"] == "constant",
        "vectorized": settings["strategy"] == "vectorized",
        "selective": bool(secondary),
        "selectiveLogic": settings["selective_logic"],
        "addMemo": True,
        "order": settings["order"],
        "position": settings["position"],
        "disable": not settings["enabled"],
        "ignoreBudget": settings["ignore_budget"],
        "excludeRecursion": settings["exclude_recursion"],
        "preventRecursion": settings["prevent_recursion"],
        "delayUntilRecursion": settings["delay_until_recursion"],
        "probability": settings["probability"],
        "useProbability": True,
        "depth": settings["depth"],
        "outletName": settings["outlet_name"],
        "group": settings["group"],
        "groupOverride": settings["group_override"],
        "groupWeight": settings["group_weight"],
        "scanDepth": settings["scan_depth"],
        "caseSensitive": settings["case_sensitive"],
        "matchWholeWords": settings["match_whole_words"],
        "useGroupScoring": settings["use_group_scoring"],
        "automationId": settings["automation_id"],
        "role": settings["role"],
        "sticky": settings["sticky"],
        "cooldown": settings["cooldown"],
        "delay": settings["delay"],
        "matchPersonaDescription": settings["match_persona_description"],
        "matchCharacterDescription": settings["match_character_description"],
        "matchCharacterPersonality": settings["match_character_personality"],
        "matchCharacterDepthPrompt": settings["match_character_depth_prompt"],
        "matchScenario": settings["match_scenario"],
        "matchCreatorNotes": settings["match_creator_notes"],
        "triggers": settings["triggers"],
        "extensions": {
            "lorecard": {
                "id": entry["id"],
                "title": entry["title"],
                "entity_type": entry["entity_type"],
                "importance": entry["importance"],
                "continuity": entry["continuity"],
                "spoiler_tier": entry.get("spoiler_tier", "safe"),
                "spoiler_parent_id": entry.get("spoiler_parent_id"),
                "source_url": sources[0],
                "source_urls": sources,
                "source_page_ids": entry["source_page_ids"],
                "settings_rationale": entry["settings_rationale"],
            }
        },
    }


def cmd_pack(args):
    workspace = Path(args.workspace).resolve()
    errors, warnings, stats = validate_workspace(workspace, "review")
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError("Refusing to pack an invalid or incomplete lorebook")
    project, candidates, _, _, _, selected = load_selection_files(workspace)
    if not getattr(args, "_skip_source_recheck", False):
        failures = verify_sources_remote(workspace, project, candidates, selected)
        if failures:
            raise WorkflowError(
                "Remote source verification failed:\n  " + "\n  ".join(failures)
            )
        verified_page_ids = {
            page_id for item in selected for page_id in selected_source_page_ids(item)
        }
        print(f"Verified {len(verified_page_ids)} source revisions.")
    candidates_by_id = {row["page_id"]: row for row in candidates}
    importance_order = {"core": 0, "recommended": 1}
    spoiler_order = {"safe": 0, "conditional": 1}
    selected = sorted(
        selected,
        key=lambda item: (
            spoiler_order[spoiler_tier(item)],
            importance_order[item["importance"]],
            item["entity_type"],
            item["title"].casefold(),
        ),
    )
    entries = {}
    for uid, item in enumerate(selected):
        entry = read_json(workspace / "entries" / f"{item['id']}.json")
        entries[str(uid)] = packed_entry(entry, candidates_by_id, uid)
    output = workspace / (args.output or "lorebook.json")
    write_json(output, {"entries": entries})
    print(f"Packed {len(entries)} entries to {output}")


def cmd_audit(args):
    lorebook = read_json(args.lorebook)
    raw_entries = lorebook.get("entries") if isinstance(lorebook, dict) else None
    if isinstance(raw_entries, dict):
        entries = list(raw_entries.values())
    elif isinstance(raw_entries, list):
        entries = raw_entries
    else:
        raise WorkflowError("Lorebook must contain an entries object or array")
    errors = []
    warnings = []
    comments = Counter()
    sources = Counter()
    fingerprints = Counter()
    enriched = 0
    blocklist = []
    spoiler_policy = "full"
    audit_project = {}
    generic_spoiler_entries = 0
    conditional_entries = 0
    safe_activation_keys = set()
    conditional_activation = []
    if args.project:
        audit_project = read_json(args.project)
        blocklist = [
            value.casefold()
            for value in audit_project.get("spoiler_blocklist", [])
            if isinstance(value, str)
        ]
        spoiler_policy = audit_project.get("spoiler_policy", "full")
    fingerprint_fields = (
        "constant",
        "vectorized",
        "selectiveLogic",
        "order",
        "position",
        "probability",
        "depth",
        "role",
        "scanDepth",
        "caseSensitive",
        "matchWholeWords",
        "excludeRecursion",
        "preventRecursion",
        "triggers",
    )
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"Entry {index} is not an object")
            continue
        comment = str(entry.get("comment", "")).strip()
        content = str(entry.get("content", "")).strip()
        keys = entry.get("key")
        if not comment:
            errors.append(f"Entry {index} has no memo/comment")
        else:
            comments[comment.casefold()] += 1
        if not content:
            errors.append(f"Entry {index} has no content")
        if not isinstance(keys, list) or (
            not keys and not entry.get("constant") and not entry.get("vectorized")
        ):
            errors.append(f"Entry {index} has no usable activation key")
        triggers = entry.get("triggers", [])
        if (
            isinstance(triggers, list)
            and all(isinstance(value, str) for value in triggers)
            and set(triggers) == TRIGGERS
        ):
            errors.append(f"Entry {index} lists every trigger; empty already means all")
        extension = entry.get("extensions", {}).get("lorecard", {})
        tier = "safe"
        if isinstance(extension, dict):
            source = extension.get("source_url")
            if source:
                sources[source] += 1
            if extension.get("entity_type") and extension.get("continuity"):
                enriched += 1
            tier = extension.get("spoiler_tier", "safe")
        normalized_keys = (
            {value.casefold() for value in keys if isinstance(value, str)}
            if isinstance(keys, list)
            else set()
        )
        secondary_keys = entry.get("keysecondary", [])
        if tier == "conditional":
            conditional_entries += 1
            conditional_activation.append((index, normalized_keys, secondary_keys))
            if not comment.startswith("[Spoiler]"):
                errors.append(
                    f"Entry {index} conditional memo must start with [Spoiler]"
                )
            if entry.get("constant") or entry.get("vectorized"):
                errors.append(f"Entry {index} conditional spoiler is not keyword-only")
            if entry.get("disable") is True:
                errors.append(f"Entry {index} conditional spoiler is disabled")
            if entry.get("probability") != 100:
                errors.append(
                    f"Entry {index} conditional spoiler must use probability 100"
                )
            if entry.get("excludeRecursion") is not True:
                errors.append(
                    f"Entry {index} conditional spoiler allows recursive activation"
                )
            if entry.get("preventRecursion") is not True:
                errors.append(
                    f"Entry {index} conditional spoiler allows downstream recursion"
                )
            if entry.get("ignoreBudget") is True:
                errors.append(
                    f"Entry {index} conditional spoiler ignores the lorebook budget"
                )
            if not extension.get("spoiler_parent_id"):
                errors.append(
                    f"Entry {index} conditional spoiler has no parent metadata"
                )
            if secondary_keys and entry.get("selectiveLogic") not in {0, 1}:
                errors.append(
                    f"Entry {index} conditional spoiler uses unsafe optional-filter logic"
                )
        else:
            safe_activation_keys.update(normalized_keys)
        if (
            normalized_keys
            and any(contains_cjk(value) for value in keys)
            and entry.get("matchWholeWords") is not False
        ):
            message = f"Entry {index} has CJK keys without matchWholeWords=false"
            if project_version(audit_project) >= 2:
                errors.append(message)
            else:
                warnings.append(message)
        if blocklist and tier == "safe":
            lowered = f" {content.casefold()}"
            for phrase in blocklist:
                if phrase in lowered:
                    errors.append(
                        f"Entry {index} contains spoiler blocklist phrase: {phrase}"
                    )
        lowered = f" {content.casefold()}"
        if tier == "safe" and any(
            term in lowered for term in GENERIC_SPOILER_TERMS.get(spoiler_policy, ())
        ):
            generic_spoiler_entries += 1
        fingerprints[
            tuple(
                json.dumps(entry.get(field), sort_keys=True)
                for field in fingerprint_fields
            )
        ] += 1
    for index, keys, secondary in conditional_activation:
        if keys & safe_activation_keys and not secondary:
            errors.append(
                f"Entry {index} reuses safe keys without conditional secondary keywords"
            )
    duplicate_comments = [name for name, count in comments.items() if count > 1]
    if duplicate_comments:
        errors.append(f"Duplicate memos/comments: {', '.join(duplicate_comments)}")
    duplicate_sources = sum(count - 1 for count in sources.values() if count > 1)
    if duplicate_sources:
        warnings.append(f"{duplicate_sources} repeated source URL assignments")
    if entries and enriched == 0:
        warnings.append("No entries preserve entity type and continuity metadata")
    if generic_spoiler_entries:
        warnings.append(
            f"{generic_spoiler_entries}/{len(entries)} entries contain generic {spoiler_policy} spoiler markers"
        )
    if fingerprints:
        largest = fingerprints.most_common(1)[0][1]
        if largest == len(entries) and len(entries) >= 5:
            warnings.append("Every entry has the same settings fingerprint")
        elif largest / len(entries) > 0.8 and len(entries) >= 10:
            warnings.append(
                f"{largest}/{len(entries)} entries share one settings fingerprint"
            )
    stats = {
        "entries": len(entries),
        "unique_memos": len(comments),
        "unique_sources": len(sources),
        "enriched_entries": enriched,
        "conditional_entries": conditional_entries,
        "settings_profiles": len(fingerprints),
    }
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError(f"Audit found {len(errors)} error(s)")


def cmd_self_test(_args):
    assert (
        evidence_length("這段來源正文直接而且完整地支持這個角色設定。")
        >= MIN_EVIDENCE_CHARS
    )
    assert not generic_review_note("來源直接支持這個設定。")
    assert generic_review_note("Supports the claim.")
    assert generic_trigger_text("This is totally unrelated.")
    assert rule_decision("Episode 12", ["Episodes"])[0] == "exclude"
    assert rule_decision("Theme", ["Songs", "Soundtrack"])[0] == "exclude"
    assert rule_decision("Hero/Image Gallery", ["Stubs"])[0] == "exclude"
    assert (
        rule_decision(
            "Side Character", ["Spin-off"], (), (re.compile("spin", re.IGNORECASE),)
        )[0]
        == "exclude"
    )
    assert rule_decision("Soul Gem", ["Items"])[0] == "keep"
    project = {
        "version": 3,
        "name": "Test",
        "wiki_url": "https://test.fandom.com/wiki",
        "purpose": "Test the workflow.",
        "output_language": "Traditional Chinese",
        "spoiler_policy": "balanced",
        "scope": ["Main"],
        "scope_requirements": [
            {
                "scope": "Main",
                "continuities": ["Main"],
                "required_titles": ["Soul Gem"],
                "coverage_minimums": {"item": 1},
            }
        ],
        "continuities": ["Main"],
        "required_titles": ["Soul Gem"],
        "coverage_minimums": {"item": 1},
        "spoiler_blocklist": ["secret ending"],
        "relationship_mode": "targeted",
        "limits": {"max_candidates": 10, "max_entries": 4, "max_entry_chars": 1000},
    }
    candidates = [
        {
            "page_id": 1,
            "title": "Soul Gem",
            "url": "https://test.fandom.com/wiki/Soul_Gem",
            "categories": ["Items"],
            "rule_action": "keep",
        },
        {
            "page_id": 2,
            "title": "Hero/Relationships",
            "url": "https://test.fandom.com/wiki/Hero/Relationships",
            "categories": ["Supplemental"],
            "rule_action": "exclude",
            "rule_reason": "Supplemental subpage.",
        },
        {
            "page_id": 3,
            "title": "Hero/Image Gallery",
            "url": "https://test.fandom.com/wiki/Hero/Image_Gallery",
            "categories": ["Image Galleries"],
            "rule_action": "exclude",
            "rule_reason": "Supplemental subpage.",
        },
    ]
    safe_selection_item = {
        "id": "soul-gem",
        "title": "Soul Gem",
        "page_ids": [1],
        "supporting_page_ids": [2],
        "entity_type": "item",
        "importance": "core",
        "continuity": "Main",
        "confidence": 0.95,
        "reason": "Defining item.",
        "spoiler_risk": "none",
        "spoiler_reason": "Premise-safe function only.",
        "spoiler_override": False,
        "spoiler_tier": "safe",
    }
    assert not relationship_support_required(project, safe_selection_item)
    assert relationship_support_required(
        project, dict(safe_selection_item, entity_type="character")
    )
    conditional_selection_item = {
        "id": "soul-gem-truth",
        "title": "Soul Gem: Hidden mechanics",
        "page_ids": [1],
        "entity_type": "item",
        "importance": "recommended",
        "continuity": "Main",
        "confidence": 0.95,
        "reason": "Reveal-only mechanics useful after the topic is raised.",
        "spoiler_risk": "major",
        "spoiler_reason": "Explains a central transformation reveal.",
        "spoiler_override": False,
        "spoiler_tier": "conditional",
        "spoiler_parent_id": "soul-gem",
    }
    selection = {
        "selected": [safe_selection_item, conditional_selection_item],
        "manual_review": [],
    }
    errors, _, _ = validate_selection(project, candidates, selection)
    assert not errors, errors
    missing_scope_backbone = json.loads(json.dumps(project))
    missing_scope_backbone["scope_requirements"][0]["required_titles"] = [
        "Hero/Relationships"
    ]
    errors, _, _ = validate_selection(missing_scope_backbone, candidates, selection)
    assert errors and "required title is not selected as safe" in " ".join(errors)
    invalid_support = {
        "selected": [dict(safe_selection_item, supporting_page_ids=[3])],
        "manual_review": [],
    }
    errors, _, _ = validate_selection(project, candidates, invalid_support)
    assert errors and "rule-excluded supporting" in " ".join(errors)
    invalid_selection = {
        "selected": [dict(safe_selection_item, spoiler_risk=[])],
        "manual_review": [],
    }
    errors, _, _ = validate_selection(project, candidates, invalid_selection)
    assert errors and "spoiler_risk" in " ".join(errors)
    exposed_selection = {
        "selected": [dict(safe_selection_item, spoiler_risk="major")],
        "manual_review": [],
    }
    errors, _, _ = validate_selection(project, candidates, exposed_selection)
    assert errors and "spoiler risk under balanced" in " ".join(errors)
    invalid_parent = {
        "selected": [
            safe_selection_item,
            dict(conditional_selection_item, spoiler_parent_id="missing"),
        ],
        "manual_review": [],
    }
    errors, _, _ = validate_selection(project, candidates, invalid_parent)
    assert errors and "spoiler_parent_id" in " ".join(errors)
    errors, _, _ = validate_selection(
        dict(project, spoiler_policy="avoid"), candidates, selection
    )
    assert errors and "spoiler risk under avoid" in " ".join(errors)
    safe_entry = {
        "id": "soul-gem",
        "title": "Soul Gem",
        "memo": "[Main] Soul Gem",
        "content": "A Soul Gem is the magical focus carried by a contracted magical girl. It stores power, supports transformation, and becomes clouded as magic is spent.",
        "keywords": ["Soul Gem", "靈魂寶石"],
        "secondary_keywords": [],
        "entity_type": "item",
        "importance": "core",
        "continuity": "Main",
        "source_page_ids": [1, 2],
        "spoiler_tier": "safe",
        "spoiler_review": {
            "policy": "balanced",
            "checked": True,
            "notes": "Premise facts only.",
        },
        "settings": {key: DEFAULT_SETTINGS[key] for key in REQUIRED_SETTINGS},
        "settings_rationale": "Core factual item with ordinary keyword activation.",
    }
    safe_entry["settings"]["match_whole_words"] = False
    errors, _ = validate_entry(project, safe_selection_item, safe_entry)
    assert not errors, errors
    exposed_marker = json.loads(json.dumps(safe_entry))
    exposed_marker["content"] += " It previously existed as a hidden final form."
    errors, _ = validate_entry(project, safe_selection_item, exposed_marker)
    assert errors and "restricted spoiler marker" in " ".join(errors)
    unsafe_cjk = json.loads(json.dumps(safe_entry))
    unsafe_cjk["settings"]["match_whole_words"] = None
    errors, _ = validate_entry(project, safe_selection_item, unsafe_cjk)
    assert errors and "match_whole_words=false" in " ".join(errors)
    invalid_entry = json.loads(json.dumps(safe_entry))
    invalid_entry["settings"]["triggers"] = [{}]
    errors, _ = validate_entry(project, safe_selection_item, invalid_entry)
    assert errors and "triggers" in " ".join(errors)
    conditional_entry = {
        "id": "soul-gem-truth",
        "title": "Soul Gem: Hidden mechanics",
        "memo": "[Spoiler][Main] Soul Gem truth",
        "content": "A Soul Gem contains the contracted girl's separated soul. If corruption reaches its limit, the gem transforms and the magical girl becomes a Witch.",
        "keywords": ["Soul Gem", "靈魂寶石"],
        "secondary_keywords": ["真相", "魔女化"],
        "entity_type": "item",
        "importance": "recommended",
        "continuity": "Main",
        "source_page_ids": [1],
        "spoiler_tier": "conditional",
        "spoiler_parent_id": "soul-gem",
        "spoiler_review": {
            "policy": "balanced",
            "checked": True,
            "notes": "Hidden behind an explicit reveal-intent filter.",
        },
        "settings": {key: DEFAULT_SETTINGS[key] for key in REQUIRED_SETTINGS},
        "settings_rationale": "Major reveal; require the item plus reveal intent and block recursion.",
    }
    conditional_entry["settings"].update(
        {
            "match_whole_words": False,
            "exclude_recursion": True,
            "prevent_recursion": True,
        }
    )
    errors, _ = validate_entry(project, conditional_selection_item, conditional_entry)
    assert not errors, errors
    merged_reveal = json.loads(json.dumps(conditional_entry))
    merged_reveal["title"] = "Soul Gem: Origin & final form"
    errors, _ = validate_entry(project, conditional_selection_item, merged_reveal)
    assert errors and "multiple reveal boundaries" in " ".join(errors)
    bad_exact_term = json.loads(json.dumps(conditional_entry))
    bad_exact_term["title"] = "Soul Gem: Secret ending"
    errors, _ = validate_entry(project, conditional_selection_item, bad_exact_term)
    assert errors and "exact spoiler term must activate" in " ".join(errors)
    gated_blocklist = json.loads(json.dumps(conditional_entry))
    gated_blocklist["content"] += (
        " This includes the secret ending only after activation."
    )
    errors, _ = validate_entry(project, conditional_selection_item, gated_blocklist)
    assert not errors, errors
    unsafe_conditional = json.loads(json.dumps(conditional_entry))
    unsafe_conditional["settings"]["exclude_recursion"] = False
    errors, _ = validate_entry(project, conditional_selection_item, unsafe_conditional)
    assert errors and "exclude_recursion" in " ".join(errors)
    packed = packed_entry(conditional_entry, {1: candidates[0]}, 0)
    assert packed["comment"] == "[Spoiler][Main] Soul Gem truth"
    assert packed["excludeRecursion"] is True
    assert packed["preventRecursion"] is True
    assert packed["extensions"]["lorecard"]["spoiler_tier"] == "conditional"
    with TemporaryDirectory() as directory:
        workspace = Path(directory)
        legacy_multiscope = json.loads(json.dumps(project))
        legacy_multiscope.update(
            {
                "version": 2,
                "scope": ["Main", "Side"],
                "continuities": ["Main", "Side"],
            }
        )
        write_json(workspace / "project.json", legacy_multiscope)
        try:
            load_project(workspace)
        except WorkflowError as exc:
            assert "version 3" in str(exc)
        else:
            raise AssertionError("legacy multi-scope project was accepted")
        write_json(workspace / "project.json", project)
        write_jsonl(workspace / "candidates.jsonl", candidates)
        write_json(workspace / "selection.json", selection)
        (workspace / "entries").mkdir()
        missing_errors, _, _ = validate_workspace(workspace, "entries")
        assert any("Missing selected entry file" in value for value in missing_errors)
        write_json(workspace / "entries" / "soul-gem.json", safe_entry)
        write_json(workspace / "entries" / "soul-gem-truth.json", conditional_entry)
        (workspace / "sources").mkdir()
        (workspace / "sources" / "1.txt").write_text(
            "# Soul Gem\n\n"
            "Source: https://test.fandom.com/wiki/Soul_Gem\n"
            "Categories: Items\n\n---\n\n"
            + safe_entry["content"]
            + "\n\n"
            + conditional_entry["content"]
            + "\n",
            encoding="utf-8",
        )
        missing_support_errors, _, _ = validate_workspace(workspace, "entries")
        assert any(
            "Missing cached source: sources/2.txt" in value
            for value in missing_support_errors
        )
        (workspace / "sources" / "2.txt").write_text(
            "# Hero Relationships\n\n"
            "Source: https://test.fandom.com/wiki/Hero/Relationships\n"
            "Categories: Supplemental\n\n---\n\n"
            "The hero trusts the gem bearer. "
            "It stores power, supports transformation, and becomes clouded as "
            "magic is spent.\n",
            encoding="utf-8",
        )
        manifest = empty_source_manifest(project)
        for page_id in (1, 2):
            manifest["sources"][str(page_id)] = {
                "url": next(
                    row["url"] for row in candidates if row["page_id"] == page_id
                ),
                "revision_id": 100 + page_id,
                "sha256": file_sha256(workspace / "sources" / f"{page_id}.txt"),
            }
        write_json(workspace / "source_manifest.json", manifest)
        workspace_errors, _, stats = validate_workspace(workspace, "entries")
        assert not workspace_errors, workspace_errors
        assert stats["conditional"] == 1
        source_one = workspace / "sources" / "1.txt"
        pristine_source = source_one.read_text(encoding="utf-8")
        source_one.write_text(
            pristine_source + "Injected evidence.\n", encoding="utf-8"
        )
        integrity_errors, _, _ = validate_workspace(workspace, "entries")
        assert any("source integrity failed" in value for value in integrity_errors)
        source_one.write_text(pristine_source, encoding="utf-8")
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("Missing review.json" in value for value in review_errors)
        with redirect_stdout(StringIO()):
            cmd_review_init(argparse.Namespace(workspace=str(workspace), reset=False))
        review = read_json(workspace / "review.json")
        review["selection"].update(
            {
                "status": "pass",
                "notes": "Requested scope and coverage were checked independently.",
            }
        )
        review["selection"]["scope_reviews"][0].update(
            {
                "status": "pass",
                "covered_entry_ids": ["soul-gem"],
                "notes": "The defining item represents this minimal test scope.",
            }
        )
        for item in review["entries"]:
            entry = safe_entry if item["id"] == "soul-gem" else conditional_entry
            item["status"] = "pass"
            item["checks"] = {name: "pass" for name in REVIEW_CHECKS}
            item["notes"] = "Checked independently against the cached source."
            for claim_index, claim in enumerate(item["claims"]):
                claim.update(
                    {
                        "verdict": "supported",
                        "page_id": (
                            2
                            if entry["spoiler_tier"] == "safe" and claim_index == 1
                            else 1
                        ),
                        "source_quote": claim["claim"],
                        "notes": "The cached sentence directly supports this claim.",
                    }
                )
            if entry["spoiler_tier"] == "conditional":
                item["trigger_tests"] = [
                    {
                        "text": "Soul Gem 真相",
                        "expected": True,
                        "reason": "Parent plus explicit reveal intent.",
                    },
                    {
                        "text": "靈魂寶石 魔女化",
                        "expected": True,
                        "reason": "Localized parent plus transformation intent.",
                    },
                    {
                        "text": "Soul Gem cleaning",
                        "expected": False,
                        "reason": "Parent alone with a routine topic must stay safe.",
                    },
                    {
                        "text": "An ordinary gemstone",
                        "expected": False,
                        "reason": "Confusable generic object must not activate.",
                    },
                ]
            else:
                item["trigger_tests"] = [
                    {
                        "text": "Soul Gem",
                        "expected": True,
                        "reason": "Canonical item name.",
                    },
                    {
                        "text": "An ordinary gemstone",
                        "expected": False,
                        "reason": "Generic nearby wording must not activate.",
                    },
                ]
        write_json(workspace / "review.json", review)
        review_errors, _, review_stats = validate_workspace(workspace, "review")
        assert not review_errors, review_errors
        assert review_stats["reviewed"] == 2
        metadata_evidence = json.loads(json.dumps(review))
        metadata_evidence["entries"][0]["claims"][0]["source_quote"] = (
            "# Soul Gem\n\nSource: https://test.fandom.com/wiki/Soul_Gem"
        )
        write_json(workspace / "review.json", metadata_evidence)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("article body text" in value for value in review_errors)
        duplicate_evidence = json.loads(json.dumps(review))
        safe_review = next(
            item for item in duplicate_evidence["entries"] if item["id"] == "soul-gem"
        )
        safe_review["claims"][1]["page_id"] = 1
        safe_review["claims"][1]["source_quote"] = safe_review["claims"][0][
            "source_quote"
        ]
        write_json(workspace / "review.json", duplicate_evidence)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("reused for a different claim" in value for value in review_errors)
        generic_note = json.loads(json.dumps(review))
        generic_note["entries"][0]["claims"][0]["notes"] = "Supports the claim."
        write_json(workspace / "review.json", generic_note)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("must explain the evidence" in value for value in review_errors)
        synthetic_term = json.loads(json.dumps(review))
        conditional_review = next(
            item for item in synthetic_term["entries"] if item["id"] == "soul-gem-truth"
        )
        conditional_review["exact_spoiler_terms"].append(
            "AutomatedTriggerPasssoulgemtruth"
        )
        write_json(workspace / "review.json", synthetic_term)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("unexpected exact spoiler term" in value for value in review_errors)
        generic_trigger = json.loads(json.dumps(review))
        generic_trigger["entries"][0]["trigger_tests"][1].update(
            {
                "text": "This is totally unrelated.",
                "reason": "Unrelated text.",
            }
        )
        write_json(workspace / "review.json", generic_trigger)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("entry-specific example" in value for value in review_errors)
        unused_support = json.loads(json.dumps(review))
        safe_review = next(
            item for item in unused_support["entries"] if item["id"] == "soul-gem"
        )
        safe_review["claims"][1]["page_id"] = 1
        write_json(workspace / "review.json", unused_support)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any(
            "does not cite supporting source IDs" in value for value in review_errors
        )
        unsupported = json.loads(json.dumps(review))
        unsupported["entries"][0]["claims"][0]["source_quote"] = (
            "This quotation is absent from every cached source."
        )
        write_json(workspace / "review.json", unsupported)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("was not found" in value for value in review_errors)
        bad_trigger = json.loads(json.dumps(review))
        bad_trigger["entries"][1]["trigger_tests"][0]["expected"] = False
        write_json(workspace / "review.json", bad_trigger)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("expected activation=false" in value for value in review_errors)
        write_json(workspace / "review.json", review)

        def fake_render_source(_api_url, candidate, revision_id=None):
            return (
                (workspace / "sources" / f"{candidate['page_id']}.txt").read_text(
                    encoding="utf-8"
                ),
                revision_id,
            )

        def changed_render_source(api_url, candidate, revision_id=None):
            text, fetched_revision = fake_render_source(api_url, candidate, revision_id)
            return text + "Changed upstream rendering.\n", fetched_revision

        with patch.object(
            sys.modules[__name__],
            "render_source",
            side_effect=changed_render_source,
        ):
            failures = verify_sources_remote(
                workspace, project, candidates, selection["selected"], workers=1
            )
        assert failures and "no longer renders" in failures[0]

        with patch.object(
            sys.modules[__name__], "render_source", side_effect=fake_render_source
        ):
            with redirect_stdout(StringIO()):
                cmd_pack(
                    argparse.Namespace(
                        workspace=str(workspace), output="packed-lorebook.json"
                    )
                )
        packed_lorebook = read_json(workspace / "packed-lorebook.json")
        assert len(packed_lorebook["entries"]) == 2
        assert packed_lorebook["entries"]["0"]["extensions"]["lorecard"][
            "source_page_ids"
        ] == [1, 2]
        assert packed_lorebook["entries"]["1"]["excludeRecursion"] is True
        with redirect_stdout(StringIO()):
            cmd_audit(
                argparse.Namespace(
                    lorebook=str(workspace / "packed-lorebook.json"),
                    project=str(workspace / "project.json"),
                )
            )

        safe_v2 = json.loads(json.dumps(safe_entry))
        safe_v2["source_evidence"] = [
            {
                "page_id": 1,
                "source_quote": safe_entry["content"],
                "supports": [0, 1],
            },
            {
                "page_id": 2,
                "source_quote": content_sentences(safe_entry["content"])[1],
                "supports": [1],
            },
        ]
        conditional_v2 = json.loads(json.dumps(conditional_entry))
        conditional_v2["source_evidence"] = [
            {
                "page_id": 1,
                "source_quote": conditional_entry["content"],
                "supports": [0, 1],
            }
        ]
        write_json(workspace / "entries" / "soul-gem.json", safe_v2)
        write_json(workspace / "entries" / "soul-gem-truth.json", conditional_v2)
        with redirect_stdout(StringIO()):
            cmd_review_init(argparse.Namespace(workspace=str(workspace), reset=False))
        review_v2 = read_json(workspace / "review.json")
        assert review_v2["version"] == 2
        review_v2["selection"].update({"status": "pass", "issues": []})
        for item in review_v2["entries"]:
            item.update({"status": "pass", "issues": []})
        conditional_review_v2 = next(
            item for item in review_v2["entries"] if item["id"] == "soul-gem-truth"
        )
        conditional_review_v2["risk_tests"] = [
            {
                "text": "Soul Gem cleaning",
                "expected": False,
                "reason": "The safe parent name without reveal intent must remain inactive.",
            }
        ]
        write_json(workspace / "review.json", review_v2)
        review_errors, _, review_stats = validate_workspace(workspace, "review")
        assert not review_errors, review_errors
        assert review_stats["reviewed"] == 2
        with patch.object(
            sys.modules[__name__], "render_source", side_effect=fake_render_source
        ):
            with redirect_stdout(StringIO()):
                cmd_pack(
                    argparse.Namespace(
                        workspace=str(workspace), output="packed-lorebook-v2.json"
                    )
                )
        assert "source_evidence" not in (
            workspace / "packed-lorebook-v2.json"
        ).read_text(encoding="utf-8")
        with redirect_stdout(StringIO()):
            cmd_review_init(argparse.Namespace(workspace=str(workspace), reset=False))
        assert read_json(workspace / "review.json") == review_v2

        missing_coverage = json.loads(json.dumps(safe_v2))
        for evidence in missing_coverage["source_evidence"]:
            evidence["supports"] = [0]
        write_json(workspace / "entries" / "soul-gem.json", missing_coverage)
        evidence_errors, _, _ = validate_workspace(workspace, "entries")
        assert any("does not cover sentence 1" in value for value in evidence_errors)
        write_json(workspace / "entries" / "soul-gem.json", safe_v2)

        unresolved = json.loads(json.dumps(review_v2))
        unresolved["entries"][0]["issues"] = [
            {
                "category": "source_fidelity",
                "message": "The first sentence overstates what the cited passage establishes.",
                "targets": ["content:0"],
            }
        ]
        write_json(workspace / "review.json", unresolved)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("issues must be empty" in value for value in review_errors)

        bad_risk = json.loads(json.dumps(review_v2))
        next(item for item in bad_risk["entries"] if item["id"] == "soul-gem-truth")[
            "risk_tests"
        ][0]["expected"] = True
        write_json(workspace / "review.json", bad_risk)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("expected activation=true" in value for value in review_errors)
        write_json(workspace / "review.json", review_v2)

        overlapping = json.loads(json.dumps(conditional_v2))
        overlapping["secondary_keywords"] = []
        write_json(workspace / "entries" / "soul-gem-truth.json", overlapping)
        workspace_errors, _, _ = validate_workspace(workspace, "entries")
        assert any("reuses safe keys" in value for value in workspace_errors)
        stale_errors, _, _ = validate_workspace(workspace, "review")
        assert any("is stale" in value for value in stale_errors)
        path = workspace / "round-trip.json"
        write_json(path, {"entries": {"0": packed}})
        assert read_json(path)["entries"]["0"]["uid"] == 0
    print("Self-test passed.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a file-based lorebook workspace")
    init.add_argument("workspace")
    init.add_argument("--wiki", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--purpose")
    init.add_argument("--language", default="English")
    init.add_argument("--spoiler", choices=sorted(SPOILER_POLICIES), default="balanced")
    init.add_argument("--max-candidates", type=int, default=1000)
    init.add_argument("--max-entries", type=int, default=150)
    init.add_argument("--max-entry-chars", type=int, default=4000)
    init.set_defaults(func=cmd_init)

    discover = subparsers.add_parser("discover", help="Discover canonical Fandom pages")
    discover.add_argument("workspace")
    discover.set_defaults(func=cmd_discover)

    catalog = subparsers.add_parser("catalog", help="Summarize discovered candidates")
    catalog.add_argument("workspace")
    catalog.add_argument("--top", type=int, default=20)
    catalog.set_defaults(func=cmd_catalog)

    fetch = subparsers.add_parser("fetch", help="Cache selected canonical source pages")
    fetch.add_argument("workspace")
    fetch.add_argument("--workers", type=int, default=6)
    fetch.add_argument("--refresh", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    validate = subparsers.add_parser(
        "validate", help="Validate selection or completed entries"
    )
    validate.add_argument("workspace")
    validate.add_argument(
        "--stage", choices=("auto", "selection", "entries", "review"), default="auto"
    )
    validate.set_defaults(func=cmd_validate)

    review_init = subparsers.add_parser(
        "review-init", help="Create or refresh the independent review template"
    )
    review_init.add_argument("workspace")
    review_init.add_argument(
        "--reset", action="store_true", help="Discard all preserved review decisions"
    )
    review_init.set_defaults(func=cmd_review_init)

    pack = subparsers.add_parser("pack", help="Validate and pack SillyTavern JSON")
    pack.add_argument("workspace")
    pack.add_argument("--output")
    pack.set_defaults(func=cmd_pack)

    audit = subparsers.add_parser(
        "audit", help="Audit an existing SillyTavern lorebook"
    )
    audit.add_argument("lorebook")
    audit.add_argument("--project")
    audit.set_defaults(func=cmd_audit)

    self_test = subparsers.add_parser(
        "self-test", help="Run deterministic smoke checks"
    )
    self_test.set_defaults(func=cmd_self_test)
    return parser


def main():
    try:
        args = build_parser().parse_args()
        args.func(args)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
