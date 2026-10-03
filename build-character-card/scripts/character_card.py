#!/usr/bin/env python3
"""Deterministic workflow for sourced SillyTavern Character Card V2 files."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import redirect_stdout
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


SPOILER_POLICIES = {"avoid", "balanced", "full"}
CARD_MODES = {"single-character", "ensemble-rpg"}
SOURCE_ROLES = {
    "identity",
    "appearance",
    "personality",
    "relationships",
    "voice",
    "scenario",
}
REQUIRED_SOURCE_ROLES = {
    "identity",
    "appearance",
    "personality",
    "relationships",
    "voice",
}
REVIEW_CHECKS = (
    "source_fidelity",
    "continuity",
    "spoiler_safety",
    "portrayal_coherence",
    "emotional_range",
    "relationship_fidelity",
    "voice_distinctiveness",
    "first_message_playability",
    "user_agency",
    "context_efficiency",
    "lorebook_complementarity",
)
PLAYABILITY_ISSUE_CATEGORIES = {
    "novelty",
    "clarity",
    "execution",
    "tension",
    "depth",
}
REVIEW_ISSUE_CATEGORIES = set(REVIEW_CHECKS) | PLAYABILITY_ISSUE_CATEGORIES
PROBE_CATEGORIES = (
    "baseline",
    "conflict",
    "vulnerability",
    "relationship",
    "user-agency",
)
VOICE_DIMENSIONS = {"diction", "cadence", "subtext", "narration"}
VOICE_DIMENSION_ORDER = ("diction", "cadence", "subtext", "narration")
CAST_PROFILE_FIELDS = ("psychology", "defense", "relationships", "voice")
SAMPLE_LINES_MIN = 2
SAMPLE_LINES_MAX = 6
SAMPLE_LINE_MAX_CHARS = 220
RELATIONSHIP_REQUIRED_FIELDS = ("name", "stance", "tension")
RELATIONSHIP_OPTIONAL_FIELDS = ("knowledge", "power")
CARD_STRING_FIELDS = (
    "name",
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "creator_notes",
    "system_prompt",
    "post_history_instructions",
    "creator",
    "character_version",
)
CARD_DATA_FIELDS = set(CARD_STRING_FIELDS) | {
    "alternate_greetings",
    "tags",
    "extensions",
}
PROMPT_FIELDS = (
    "description",
    "personality",
    "scenario",
    "first_mes",
    "mes_example",
    "system_prompt",
    "post_history_instructions",
)
PERMANENT_FIELDS = (
    "description",
    "personality",
    "scenario",
    "system_prompt",
    "post_history_instructions",
)
CLAIM_FIELDS = ("description", "personality", "scenario")
PORTRAYAL_FIELDS = {
    "appearance_anchors",
    "cast_profiles",
    "inner_engine",
    "emotional_dynamics",
    "relationships",
    "voice",
    "interaction_hooks",
}
MIN_FIELD_CHARS = {
    "description": 80,
    "personality": 80,
    "scenario": 40,
    "first_mes": 100,
    "mes_example": 160,
}
GENERIC_NOTES = {
    "allowed",
    "checked",
    "looks good",
    "ok",
    "pass",
    "reviewed",
    "source supports this",
    "supported",
    "valid",
}
EVIDENCE_STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "into",
    "its",
    "that",
    "the",
    "their",
    "this",
    "was",
    "were",
    "with",
}
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_MANIFEST_VERSION = 1
NAMESPACE = "sillytavern_canon_builder"
USER_AGENT = "build-character-card-skill/1.0 (local research workflow)"


class WorkflowError(Exception):
    pass


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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


def canonical_hash(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def valid_string_list(value, minimum=0, maximum=16):
    return (
        isinstance(value, list)
        and minimum <= len(value) <= maximum
        and all(nonempty_string(item) for item in value)
    )


def unique_strings(value):
    return len({item.casefold() for item in value}) == len(value)


def evidence_length(value):
    total = 0
    for character in value.strip():
        code = ord(character)
        if 0x3040 <= code <= 0x30FF or 0x3400 <= code <= 0x9FFF:
            total += 2
        elif not character.isspace():
            total += 1
    return total


def generic_note(value):
    if not isinstance(value, str):
        return True
    normalized = re.sub(r"\s+", " ", value).strip(" .").casefold()
    return evidence_length(value) < 20 or normalized in GENERIC_NOTES


def evidence_terms(value):
    return {
        token
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", value.casefold())
        if token not in EVIDENCE_STOPWORDS
    }


def source_body(value):
    marker = "\n---\n"
    return value.split(marker, 1)[1].lstrip() if marker in value else value


def content_sentences(value):
    if not isinstance(value, str):
        return []
    rows = []
    for paragraph in re.split(r"\n+", value):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        parts = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s*", paragraph)
        rows.extend(part.strip() for part in parts if part.strip())
    return rows


def card_evidence_targets(card, project, planned_sources):
    source_roles = {item["id"]: set(item["roles"]) for item in planned_sources}
    ensemble = project.get("mode", "single-character") == "ensemble-rpg"
    targets = {}
    role_map = {
        "description": {"identity", "appearance"},
        "personality": {"personality"},
        "scenario": {"scenario"},
    }
    for field in CLAIM_FIELDS:
        allowed_sources = {
            source_id
            for source_id, roles in source_roles.items()
            if roles & role_map[field]
        }
        for index, sentence in enumerate(content_sentences(card["data"][field])):
            targets[f"{field}:{index}"] = {
                "text": sentence,
                "allowed_bases": (
                    {"sourced", "authored"}
                    if ensemble or field == "scenario"
                    else {"sourced"}
                ),
                "allowed_sources": allowed_sources,
            }
    for index, relationship in enumerate(card["portrayal"]["relationships"]):
        targets[f"relationship:{index}"] = {
            "text": " ".join(
                relationship.get(field, "")
                for field in ("stance", "knowledge", "power", "tension")
                if nonempty_string(relationship.get(field))
            ),
            "allowed_bases": {
                "sourced" if relationship["basis"] == "canon" else "authored"
            },
            "allowed_sources": set(relationship["source_ids"]),
        }
    for index, profile in enumerate(card["portrayal"].get("cast_profiles", [])):
        for field in CAST_PROFILE_FIELDS:
            targets[f"cast_profile:{index}:{field}"] = {
                "text": profile[field],
                "allowed_bases": {"sourced"},
                "allowed_sources": set(profile["source_ids"]),
            }
    voice_sources = {
        source_id for source_id, roles in source_roles.items() if "voice" in roles
    }
    for dimension in VOICE_DIMENSION_ORDER:
        targets[f"voice:{dimension}"] = {
            "text": card["portrayal"]["voice"][dimension],
            "allowed_bases": (
                {"sourced", "authored"}
                if ensemble or dimension == "narration"
                else {"sourced"}
            ),
            "allowed_sources": voice_sources,
        }
    return targets


def validate_card_evidence(workspace, project, planned_sources, card):
    evidence = card.get("evidence")
    if evidence is None:
        return []
    if not isinstance(evidence, list) or not evidence:
        return ["card.evidence must be a non-empty array"]

    errors = []
    targets = card_evidence_targets(card, project, planned_sources)
    target_bases = {target: set() for target in targets}
    planned_ids = {item["id"] for item in planned_sources}
    required_ids = {item["id"] for item in planned_sources if item["required"]}
    cited_source_ids = set()
    seen_quotes = set()
    creative_text = card["data"]["first_mes"] + "\n" + card["data"]["mes_example"]
    allowed_project_fields = {
        "continuity",
        "purpose",
        "time_anchor",
        "user_role",
        "scenario_premise",
        "content_boundaries",
    }
    for index, item in enumerate(evidence):
        prefix = f"card.evidence[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        basis = item.get("basis")
        if basis not in {"sourced", "authored"}:
            errors.append(f"{prefix}.basis must be sourced or authored")
            continue
        supports = item.get("supports")
        if (
            not isinstance(supports, list)
            or not supports
            or any(
                not isinstance(value, str) or value not in targets for value in supports
            )
            or len(supports) != len(set(supports))
        ):
            errors.append(f"{prefix}.supports must contain unique generated target IDs")
            supports = []
        for target_id in supports:
            target_bases[target_id].add(basis)
            if basis not in targets[target_id]["allowed_bases"]:
                errors.append(f"{prefix} cannot use {basis} for {target_id}")

        if basis == "sourced":
            expected = {"basis", "source_id", "source_quote", "supports"}
            if set(item) != expected:
                errors.append(
                    f"{prefix} sourced fields must be: " + ", ".join(sorted(expected))
                )
            source_id = item.get("source_id")
            if source_id not in planned_ids:
                errors.append(f"{prefix}.source_id must name a planned source")
                continue
            cited_source_ids.add(source_id)
            for target_id in supports:
                if source_id not in targets[target_id]["allowed_sources"]:
                    errors.append(f"{prefix}.source_id is not allowed for {target_id}")
            quote_value = item.get("source_quote")
            if evidence_valid(workspace, source_id, quote_value, prefix, errors):
                quote_key = (source_id, quote_value)
                if quote_key in seen_quotes:
                    errors.append(
                        f"{prefix} duplicates an evidence quote; merge its supports instead"
                    )
                seen_quotes.add(quote_key)
                if quote_value in creative_text:
                    errors.append(
                        f"{prefix}.source_quote is copied into greeting or examples"
                    )
                supported_text = " ".join(
                    targets[target_id]["text"] for target_id in supports
                )
                claim_terms = evidence_terms(supported_text)
                quote_terms = evidence_terms(quote_value)
                if claim_terms and quote_terms and not claim_terms & quote_terms:
                    errors.append(
                        f"{prefix}.source_quote has no meaningful Latin-term overlap with its targets"
                    )
        else:
            expected = {"basis", "project_fields", "supports", "note"}
            if set(item) != expected:
                errors.append(
                    f"{prefix} authored fields must be: " + ", ".join(sorted(expected))
                )
            project_fields = item.get("project_fields")
            if (
                not valid_string_list(project_fields, 1, len(allowed_project_fields))
                or set(project_fields) - allowed_project_fields
                or len(project_fields) != len(set(project_fields))
            ):
                errors.append(f"{prefix}.project_fields contains invalid fields")
            elif any(not project.get(field) for field in project_fields):
                errors.append(
                    f"{prefix}.project_fields must reference configured values"
                )
            if generic_note(item.get("note")):
                errors.append(
                    f"{prefix}.note must explain the project-grounded authored choice"
                )

    for target_id, bases in target_bases.items():
        if not bases:
            errors.append(f"card.evidence does not cover {target_id}")
        elif len(bases) > 1:
            errors.append(
                f"card.evidence mixes sourced and authored basis for {target_id}"
            )
    unused_required = sorted(required_ids - cited_source_ids)
    if unused_required:
        errors.append(
            "card.evidence does not use required sources: " + ", ".join(unused_required)
        )
    return errors


def recursive_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from recursive_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from recursive_strings(item)


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


def resolve_source(api_url, wiki_url, planned):
    payload = api_request(
        api_url,
        {
            "action": "query",
            "titles": planned["title"],
            "prop": "info",
            "inprop": "url",
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        },
    )
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list) or len(pages) != 1:
        raise WorkflowError(f"Could not resolve source title: {planned['title']}")
    page = pages[0]
    if "missing" in page or not is_int(page.get("pageid")):
        raise WorkflowError(f"Fandom page does not exist: {planned['title']}")
    title = page.get("title")
    if not nonempty_string(title):
        raise WorkflowError(f"Fandom returned an invalid title for: {planned['title']}")
    return {
        "source_id": planned["id"],
        "requested_title": planned["title"],
        "title": title,
        "page_id": page["pageid"],
        "url": page.get("fullurl") or wiki_page_url(wiki_url, title),
        "roles": planned["roles"],
        "required": planned["required"],
    }


def render_source(api_url, record, revision_id=None):
    target = (
        {"oldid": revision_id}
        if revision_id is not None
        else {"pageid": record["page_id"]}
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
    if parsed.get("pageid") != record["page_id"]:
        raise WorkflowError(f"Revision does not belong to source {record['title']}")
    html = parsed.get("text")
    if isinstance(html, dict):
        html = html.get("*")
    if not nonempty_string(html):
        raise WorkflowError(f"No article text returned for {record['title']}")
    fetched_revision = parsed.get("revid")
    if not is_int(fetched_revision) or fetched_revision <= 0:
        raise WorkflowError(f"No revision ID returned for {record['title']}")
    if revision_id is not None and fetched_revision != revision_id:
        raise WorkflowError(
            f"Expected revision {revision_id}, received {fetched_revision} "
            f"for {record['title']}"
        )
    parser = ArticleTextParser()
    parser.feed(html)
    content = parser.text()
    if not content:
        raise WorkflowError(f"No readable article text returned for {record['title']}")
    header = (
        f"# {record['title']}\n\n"
        f"Source: {record['url']}\n"
        f"Roles: {', '.join(record['roles'])}\n\n"
        "---\n\n"
    )
    return header + content + "\n", fetched_revision


def fetch_source(api_url, record, destination):
    text, revision_id = render_source(api_url, record)
    temporary = destination.with_suffix(".txt.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(destination)
    result = dict(record)
    result.update(
        {
            "revision_id": revision_id,
            "sha256": file_sha256(destination),
        }
    )
    return result


def project_path(workspace):
    return Path(workspace) / "project.json"


def load_project(workspace):
    project = read_json(project_path(workspace))
    if not isinstance(project, dict):
        raise WorkflowError("project.json must contain an object")
    return project


def validate_project(project):
    errors = []
    warnings = []
    expected_fields = {
        "version",
        "mode",
        "name",
        "wiki_url",
        "character",
        "purpose",
        "output_language",
        "continuity",
        "time_anchor",
        "user_role",
        "scenario_premise",
        "spoiler_policy",
        "spoiler_blocklist",
        "content_boundaries",
        "creator",
        "character_version",
        "limits",
        "lorebook",
    }
    if project.get("version") != 1:
        errors.append("project.json version must be 1")
    unknown = sorted(set(project) - expected_fields)
    if unknown:
        errors.append(f"project.json has unknown fields: {', '.join(unknown)}")
    mode = project.get("mode", "single-character")
    if mode not in CARD_MODES:
        errors.append("project.json mode must be single-character or ensemble-rpg")
    for field in (
        "name",
        "wiki_url",
        "character",
        "purpose",
        "output_language",
        "continuity",
        "time_anchor",
        "user_role",
        "scenario_premise",
        "character_version",
    ):
        if not nonempty_string(project.get(field)):
            errors.append(f"project.json {field} must be a non-empty string")
    if not isinstance(project.get("creator"), str):
        errors.append("project.json creator must be a string")
    if isinstance(project.get("wiki_url"), str):
        try:
            fandom_api_url(project["wiki_url"])
        except WorkflowError as exc:
            errors.append(str(exc))
    if project.get("spoiler_policy") not in SPOILER_POLICIES:
        errors.append("project.json spoiler_policy must be avoid, balanced, or full")
    for field in ("spoiler_blocklist", "content_boundaries"):
        value = project.get(field)
        if not valid_string_list(value, 0, 32):
            errors.append(f"project.json {field} must contain 0..32 strings")
        elif not unique_strings(value):
            errors.append(f"project.json {field} contains duplicate strings")
    limits = project.get("limits")
    limit_fields = {
        "max_sources",
        "max_permanent_chars",
        "max_first_message_chars",
        "max_example_chars",
    }
    if not isinstance(limits, dict):
        errors.append("project.json limits must be an object")
        limits = {}
    else:
        unknown_limits = sorted(set(limits) - limit_fields)
        if unknown_limits:
            errors.append(
                f"project.json limits has unknown fields: {', '.join(unknown_limits)}"
            )
    for field in limit_fields:
        value = limits.get(field)
        if not is_int(value) or value <= 0:
            errors.append(f"project.json limits.{field} must be a positive integer")
    if is_int(limits.get("max_sources")) and limits["max_sources"] > 16:
        errors.append("project.json limits.max_sources cannot exceed 16")
    lorebook = project.get("lorebook")
    if not isinstance(lorebook, dict):
        errors.append("project.json lorebook must be an object")
    else:
        unknown_lorebook = sorted(set(lorebook) - {"workspace", "entry_ids"})
        if unknown_lorebook:
            errors.append(
                "project.json lorebook has unknown fields: "
                + ", ".join(unknown_lorebook)
            )
        if not isinstance(lorebook.get("workspace"), str):
            errors.append("project.json lorebook.workspace must be a string")
        entry_ids = lorebook.get("entry_ids")
        if not valid_string_list(entry_ids, 0, 64):
            errors.append("project.json lorebook.entry_ids must contain 0..64 strings")
        elif not unique_strings(entry_ids):
            errors.append("project.json lorebook.entry_ids contains duplicates")
        if entry_ids and not str(lorebook.get("workspace", "")).strip():
            errors.append("lorebook.workspace is required when entry_ids is non-empty")
        if str(lorebook.get("workspace", "")).strip() and not entry_ids:
            warnings.append("lorebook.workspace is set but no entries will be embedded")
    return errors, warnings


def load_source_plan(workspace):
    plan = read_json(Path(workspace) / "source_plan.json")
    if not isinstance(plan, dict):
        raise WorkflowError("source_plan.json must contain an object")
    return plan


def validate_source_plan(project, plan):
    errors = []
    warnings = []
    if plan.get("version") != 1:
        errors.append("source_plan.json version must be 1")
    if set(plan) - {"version", "sources"}:
        errors.append("source_plan.json contains unknown top-level fields")
    sources = plan.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("source_plan.json sources must be a non-empty array")
        sources = []
    limits = project.get("limits", {})
    maximum = limits.get("max_sources", 0)
    if is_int(maximum) and len(sources) > maximum:
        errors.append(f"source plan exceeds max_sources={maximum}")
    seen_ids = set()
    seen_titles = set()
    covered_roles = set()
    required_count = 0
    for index, item in enumerate(sources):
        prefix = f"source_plan.json sources[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        unknown = sorted(set(item) - {"id", "title", "roles", "required"})
        if unknown:
            errors.append(f"{prefix} has unknown fields: {', '.join(unknown)}")
        source_id = item.get("id")
        if not isinstance(source_id, str) or ID_PATTERN.fullmatch(source_id) is None:
            errors.append(f"{prefix}.id must be a short ASCII kebab-case ID")
        elif source_id in seen_ids:
            errors.append(f"Duplicate source id: {source_id}")
        else:
            seen_ids.add(source_id)
        title = item.get("title")
        if not nonempty_string(title):
            errors.append(f"{prefix}.title must be a non-empty string")
        elif title.casefold() in seen_titles:
            errors.append(f"Duplicate source title: {title}")
        else:
            seen_titles.add(title.casefold())
        roles = item.get("roles")
        if not valid_string_list(roles, 1, len(SOURCE_ROLES)):
            errors.append(f"{prefix}.roles must contain 1..{len(SOURCE_ROLES)} strings")
            roles = []
        elif len(roles) != len(set(roles)):
            errors.append(f"{prefix}.roles contains duplicates")
        unknown_roles = sorted(set(roles) - SOURCE_ROLES)
        if unknown_roles:
            errors.append(f"{prefix}.roles is invalid: {', '.join(unknown_roles)}")
        covered_roles.update(set(roles) & SOURCE_ROLES)
        if not isinstance(item.get("required"), bool):
            errors.append(f"{prefix}.required must be boolean")
        elif item["required"]:
            required_count += 1
        if len(roles) >= 5:
            warnings.append(
                f"{prefix} covers {len(roles)} roles; verify the page really supports each one"
            )
    missing_roles = sorted(REQUIRED_SOURCE_ROLES - covered_roles)
    if missing_roles:
        errors.append(
            "source plan is missing required roles: " + ", ".join(missing_roles)
        )
    if not required_count:
        errors.append("source plan must contain at least one required source")
    return errors, warnings, sources


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


def source_record_matches(path, planned, record):
    return (
        path.exists()
        and isinstance(record, dict)
        and record.get("source_id") == planned.get("id")
        and record.get("requested_title") == planned.get("title")
        and record.get("roles") == planned.get("roles")
        and record.get("required") == planned.get("required")
        and nonempty_string(record.get("title"))
        and is_int(record.get("page_id"))
        and nonempty_string(record.get("url"))
        and is_int(record.get("revision_id"))
        and record["revision_id"] > 0
        and isinstance(record.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is not None
        and file_sha256(path) == record["sha256"]
    )


def validate_source_integrity(workspace, project, planned_sources):
    errors = []
    try:
        manifest = load_source_manifest(workspace, project)
    except WorkflowError as exc:
        return [str(exc)], empty_source_manifest(project)
    planned_ids = {item["id"] for item in planned_sources}
    manifest_ids = set(manifest["sources"])
    if manifest_ids != planned_ids:
        errors.append("source_manifest.json IDs must exactly match source_plan.json")
    for planned in planned_sources:
        path = Path(workspace) / "sources" / f"{planned['id']}.txt"
        record = manifest["sources"].get(planned["id"])
        if not path.exists():
            errors.append(f"Missing cached source: sources/{planned['id']}.txt")
        elif not source_record_matches(path, planned, record):
            errors.append(
                f"Cached source integrity failed: sources/{planned['id']}.txt; "
                "run fetch --refresh"
            )
    return errors, manifest


def verify_sources_remote(workspace, project, planned_sources, workers=4):
    manifest = load_source_manifest(workspace, project)
    api_url = fandom_api_url(project["wiki_url"])
    failures = []

    def verify(planned):
        record = manifest["sources"][planned["id"]]
        text, _ = render_source(api_url, record, record["revision_id"])
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != record["sha256"]:
            raise WorkflowError(
                f"revision {record['revision_id']} no longer matches the reviewed cache"
            )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(verify, planned): planned for planned in planned_sources
        }
        for future in as_completed(futures):
            planned = futures[future]
            try:
                future.result()
            except Exception as exc:
                failures.append(f"{planned['title']}: {exc}")
    return sorted(failures)


def load_card(workspace):
    card = read_json(Path(workspace) / "card.json")
    if not isinstance(card, dict):
        raise WorkflowError("card.json must contain an object")
    return card


def validate_macro_balance(field, value, errors):
    if value.count("{{") != value.count("}}"):
        errors.append(f"card.data.{field} has unbalanced template macros")


def validate_examples(value, errors):
    markers = list(re.finditer(r"(?m)^[ \t]*<START>[ \t]*$", value))
    if value.count("<START>") != len(markers):
        errors.append("card.data.mes_example must put each <START> on its own line")
    if len(markers) < 2:
        errors.append("card.data.mes_example must contain at least two <START> blocks")
        return
    if value[: markers[0].start()].strip():
        errors.append(
            "card.data.mes_example cannot contain text before the first <START>"
        )
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(value)
        block = value[marker.end() : end]
        if re.search(r"(?m)^[ \t]*\{\{user\}\}:", block) is None:
            errors.append(
                f"example block {index + 1} is missing a {{{{user}}}}: message"
            )
        if re.search(r"(?m)^[ \t]*\{\{char\}\}:", block) is None:
            errors.append(
                f"example block {index + 1} is missing a {{{{char}}}}: message"
            )


def validate_string_object(value, fields, prefix, errors):
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    unknown = sorted(set(value) - set(fields))
    missing = sorted(set(fields) - set(value))
    if unknown:
        errors.append(f"{prefix} has unknown fields: {', '.join(unknown)}")
    if missing:
        errors.append(f"{prefix} is missing fields: {', '.join(missing)}")
    for field in fields:
        if not nonempty_string(value.get(field)):
            errors.append(f"{prefix}.{field} must be a non-empty string")


def validate_sample_lines(container, prefix, errors):
    """Require short demonstrated lines plus one concrete 'never' rule."""
    samples = container.get("sample_lines")
    if not valid_string_list(samples, SAMPLE_LINES_MIN, SAMPLE_LINES_MAX):
        errors.append(
            f"{prefix}.sample_lines must contain "
            f"{SAMPLE_LINES_MIN}..{SAMPLE_LINES_MAX} strings"
        )
    else:
        if not unique_strings(samples):
            errors.append(f"{prefix}.sample_lines contains duplicates")
        for index, line in enumerate(samples):
            if len(line.strip()) > SAMPLE_LINE_MAX_CHARS:
                errors.append(
                    f"{prefix}.sample_lines[{index}] exceeds "
                    f"{SAMPLE_LINE_MAX_CHARS} characters; samples are lines, not monologues"
                )
    if not nonempty_string(container.get("never")):
        errors.append(f"{prefix}.never must be a non-empty string")


def compiled_card_data(project, card):
    """Compile the draft-only portrayal contract into standard V2 prompt fields."""
    data = deepcopy(card.get("data", {}))
    if not isinstance(data, dict):
        return {}
    portrayal = card.get("portrayal")
    if not isinstance(portrayal, dict):
        return data

    def add_section(field, title, lines):
        lines = [line for line in lines if nonempty_string(line)]
        if not lines:
            return
        base = data.get(field, "")
        if not isinstance(base, str):
            base = ""
        section = f"[{title}]\n" + "\n".join(lines)
        data[field] = f"{base.rstrip()}\n\n{section}".lstrip()

    anchors = portrayal.get("appearance_anchors")
    if isinstance(anchors, list):
        add_section(
            "description",
            "Visual anchors",
            [f"- {value}" for value in anchors if nonempty_string(value)],
        )

    personality_sections = []
    engine = portrayal.get("inner_engine")
    if isinstance(engine, dict):
        engine_lines = [
            f"Want: {engine.get('want', '')}",
            f"Fear: {engine.get('fear', '')}",
            f"Contradiction: {engine.get('contradiction', '')}",
            f"Boundary: {engine.get('boundary', '')}",
        ]
        title = (
            "Director engine"
            if project.get("mode", "single-character") == "ensemble-rpg"
            else "Inner engine"
        )
        personality_sections.append(f"[{title}]\n" + "\n".join(engine_lines))

    def sample_line_text(value):
        if not isinstance(value, list):
            return ""
        return " / ".join(
            f'"{line.strip()}"' for line in value if nonempty_string(line)
        )

    profiles = portrayal.get("cast_profiles")
    if isinstance(profiles, list):
        lines = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            block = (
                f"- {profile.get('name', '')}\n"
                f"  Psychology: {profile.get('psychology', '')}\n"
                f"  Emotional defense: {profile.get('defense', '')}\n"
                f"  Relationship differences: {profile.get('relationships', '')}\n"
                f"  Voice: {profile.get('voice', '')}"
            )
            samples = sample_line_text(profile.get("sample_lines"))
            if samples:
                block += f"\n  Sounds like: {samples}"
            if nonempty_string(profile.get("never")):
                block += f"\n  Never: {profile['never']}"
            lines.append(block)
        if lines:
            personality_sections.append("[Core cast profiles]\n" + "\n".join(lines))

    dynamics = portrayal.get("emotional_dynamics")
    if isinstance(dynamics, list):
        lines = []
        for dynamic in dynamics:
            if not isinstance(dynamic, dict):
                continue
            lines.append(
                f"- Trigger: {dynamic.get('trigger', '')}\n"
                f"  Response: {dynamic.get('response', '')}\n"
                f"  Recovery: {dynamic.get('recovery', '')}"
            )
        if lines:
            personality_sections.append("[Emotional dynamics]\n" + "\n".join(lines))

    relationships = portrayal.get("relationships")
    if isinstance(relationships, list):
        lines = []
        for relationship in relationships:
            if not isinstance(relationship, dict):
                continue
            block = [f"- {relationship.get('name', '')}"]
            for field, label in (
                ("stance", "Stance"),
                ("knowledge", "Knowledge"),
                ("power", "Power"),
                ("tension", "Tension"),
            ):
                if nonempty_string(relationship.get(field)):
                    block.append(f"  {label}: {relationship[field]}")
            lines.append("\n".join(block))
        if lines:
            personality_sections.append("[Relationships]\n" + "\n".join(lines))

    voice = portrayal.get("voice")
    if isinstance(voice, dict):
        voice_lines = [
            f"Diction: {voice.get('diction', '')}",
            f"Cadence: {voice.get('cadence', '')}",
            f"Subtext: {voice.get('subtext', '')}",
            f"Narration: {voice.get('narration', '')}",
        ]
        samples = sample_line_text(voice.get("sample_lines"))
        if samples:
            voice_lines.append(f"Sounds like: {samples}")
        if nonempty_string(voice.get("never")):
            voice_lines.append(f"Never: {voice['never']}")
        personality_sections.append("[Voice]\n" + "\n".join(voice_lines))

    if personality_sections:
        add_section("personality", "Portrayal contract", personality_sections)

    hooks = portrayal.get("interaction_hooks")
    if isinstance(hooks, list):
        add_section(
            "scenario",
            "Interaction hooks",
            [f"- {value}" for value in hooks if nonempty_string(value)],
        )
    return data


def permanent_chars(data):
    return sum(
        len(data.get(field, ""))
        for field in PERMANENT_FIELDS
        if isinstance(data.get(field), str)
    )


# ---------------------------------------------------------------------------
# Prose lint: deterministic detectors for habits that make cards read as
# machine-written or that take control away from the user. Semantic quality
# still belongs to the reviewer; these checks only catch observable patterns.
# ---------------------------------------------------------------------------

SLOP_PATTERNS = (
    ("knuckles whitening", r"\bknuckles?\b[^.!?\n]{0,40}\b(?:white|bloodless|blanch\w*)|\bwhite-knuckled\b"),
    ("a heartbeat", r"\b(?:for|in|within|after) a (?:single )?heartbeat\b|\ba heartbeat (?:away|later)\b"),
    ("a fraction of an inch/second", r"\bfraction of an? (?:inch|second|millimet(?:er|re))\b"),
    ("razor-sharp / razor's edge", r"\brazor(?:-sharp|'s edge|-thin| edge)\b"),
    ("breathtaking", r"\bbreathtaking\b"),
    ("intoxicating", r"\bintoxicating\b"),
    ("silk and venom/steel", r"\bsilk and (?:venom|steel)\b"),
    ("voice cracking/breaking", r"\bvoice (?:crack|break)(?:s|ed|ing)?\b|\bvoice (?:broke|cracked)\b"),
    ("shiver down the spine", r"\b(?:shiver|chill)s? (?:runs?|ran|went|crawl\w*) down\b"),
    ("breath they didn't know they held", r"\bbreath (?:she|he|you|they) (?:didn't|did not) know\b"),
    ("smile doesn't reach the eyes", r"\b(?:doesn't|does not|didn't|never) reach(?:es|ed)? (?:her|his|their) eyes\b"),
    ("smirk", r"\bsmirk\w*\b"),
    ("palpable", r"\bpalpable\b"),
    ("testament to", r"\btestament to\b"),
    ("unwavering / unyielding", r"\bun(?:wavering|yielding)\b"),
    ("barely above a whisper", r"\bbarely above a whisper\b"),
    ("the air grows thick", r"\bair (?:is|was|grows|grew|hangs|hung) (?:thick|heavy)\b"),
    ("can't help but", r"\b(?:can't|cannot|couldn't) help but\b"),
    ("ozone", r"\bozone\b"),
    ("predatory", r"\bpredatory\b"),
    ("指節發白", r"指[節节](?:都)?(?:泛|發|发)白"),
    ("心跳漏了一拍", r"心跳(?:漏了|慢了)半?一?拍"),
    ("不易察覺", r"不易察[覺觉]"),
    ("嘴角勾起", r"嘴角(?:微微)?(?:勾起|上揚|上扬)"),
    ("眼底閃過", r"眼[底中](?:閃過|闪过)"),
    ("空氣凝固", r"空[氣气](?:彷彿|仿佛|似乎)?(?:凝固|凝結|凝结)"),
    ("一絲玩味", r"一[絲丝](?:玩味|狡黠|戲謔|戏谑)"),
    ("喉結滾動", r"喉[結结](?:滾動|滚动)"),
    ("低沉磁性的嗓音", r"(?:低沉|磁性)的(?:嗓音|聲音|声音)"),
    ("不容置疑", r"不容(?:置疑|拒絕|拒绝)"),
)
SLOP_ERROR_THRESHOLD = 3
PUPPET_PATTERNS = (
    r"\byou (?:flinch|freeze|froze|feel|felt|realize|realise|gasp|shiver|blush|nod|agree|decide|wince|tremble|swallow|stammer|can't help|cannot help|find yourself|found yourself|instinctively|reflexively|deliberately|had deliberately|chose to|decided)\w*\b",
    r"\byour (?:heart|pulse|breath|stomach) (?:\w+ )?(?:race[sd]?|pound(?:s|ed)?|skip(?:s|ped)?|catch(?:es)?|caught|hitch(?:es|ed)?|sinks?|sank|lurch\w*|tighten\w*)\b",
    r"\byour (?:trembling|shaking|sweating|clammy) (?:hand|hands|fingers|voice)\b",
    r"\byour (?:cheeks|face) (?:flush|burn|redden)\w*\b",
    r"你(?:不禁|不由得|忍不住|下意識|下意识|本能地|感到|感覺到|感觉到|覺得|觉得|心頭|心头|心跳|倒吸|渾身|浑身|臉頰|脸颊|決定|决定)",
)
WEAPON_PATTERN = (
    r"\b(?:blade|sword|cutlass|saber|sabre|spear|lance|gun|pistol|rifle|musket|muzzle|"
    r"barrel|wand|staff|knife|dagger|kukri|crossbow|arrow|gatling|cannon|claw)s?\b"
    r"[^.!?\n]*?\b(?:at|toward|towards|against|into|for)\b(?:\s+[\w'-]+){0,4}?\s+(?:you|your)\b"
    r"|(?:刀|劍|剑|槍|枪|矛|杖|刃|弓|箭|炮|匕首)[^。！？\n]{0,16}"
    r"(?:指向|指著|指着|對準|对准|抵住|抵在|架在|刺向)[^。！？\n]{0,6}你"
)
INTERVIEW_PATTERN = (
    r"\b(?:why do you|why did you|how do you|how can you|how could you|is it true|"
    r"are you really|are you certain|are you sure you|is there truly|do you really|"
    r"what do you think (?:of|about)|tell me about (?:your|yourself)|what (?:is|was) your)\b"
    r"|為什麼你|为什么你|你為什麼|你为什么|你真的|是真的嗎|是真的吗|你怎麼看|你怎么看|跟我說說你|跟我说说你"
)
_NUMBER_WORDS = (
    r"(?:\d+(?:[.,]\d+)?|(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"fifteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)"
    r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine|hundred|thousand))*)"
)
PRECISION_PATTERN = (
    r"\b" + _NUMBER_WORDS + r"\s?(?:%|percent|km/h|mph|mm|cm|millimet(?:er|re)s?|"
    r"met(?:er|re)s?|kilomet(?:er|re)s?|seconds?|tons?|inch(?:es)?|paces|degrees)(?![A-Za-z])"
    r"|\d+(?:\.\d+)?\s?(?:%|％|公里|公尺|毫米|秒|噸|吨)|百分之[一二三四五六七八九十百\d]+"
)
SFX_WORD = (
    r"(?:snap|crack|thud|bang|boom|crash|clang|clank|whoosh|creak|scrape|click|hiss+|"
    r"whir+|thung|bam|wham|thwack|sizzle|hs+|kra+k|ka-?boom|zing|shink|schwing)"
)
SFX_CJK = set("砰轟轰咚嘩哗噹当喀咔嚓嘶呼啪鏘锵嗡嗖咻")
COPY_SHINGLE_WORDS = 10


def strip_dialogue(text):
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』', " ", text)


def character_example_text(value):
    """Return only the {{char}} portions of mes_example."""
    if not isinstance(value, str):
        return ""
    rows = []
    speaker = None
    for line in value.splitlines():
        stripped = line.strip()
        if stripped == "<START>":
            speaker = None
            continue
        if stripped.startswith("{{user}}:"):
            speaker = "user"
            continue
        if stripped.startswith("{{char}}:"):
            speaker = "char"
            line = stripped[len("{{char}}:") :]
        if speaker == "char":
            rows.append(line)
    return "\n".join(rows)


def example_user_lines(value):
    if not isinstance(value, str):
        return []
    blocks = re.split(r"(?m)^[ \t]*<START>[ \t]*$", value)
    result = []
    for block in blocks:
        users = re.findall(r"(?m)^[ \t]*\{\{user\}\}:(.*)$", block)
        if users:
            result.append(" ".join(users))
    return result


def is_sfx_line(line):
    text = line.strip().strip("*_~ ").strip()
    if not text or len(text) > 48 or text[0] in "\"“「『'":
        return False
    cjk = [character for character in text if "\u3400" <= character <= "\u9fff"]
    if cjk and all(character in SFX_CJK for character in cjk):
        return len(re.sub(r"[\W_]", "", text)) == len(cjk)
    letters = re.sub(r"[^A-Za-z]", "", text)
    if len(letters) < 3:
        return False
    if letters.isupper() and len(text.split()) <= 4:
        return True
    words = re.findall(r"[A-Za-z]+", text.casefold())
    return bool(words) and all(re.fullmatch(SFX_WORD, word) for word in words)


def source_shingles(source_texts, size=COPY_SHINGLE_WORDS):
    shingles = set()
    for text in source_texts:
        words = re.findall(r"[a-z0-9']+", source_body(text).casefold())
        for index in range(len(words) - size + 1):
            shingles.add(tuple(words[index : index + size]))
    return shingles


def lint_card_prose(data, source_texts=()):
    """Return (errors, warnings) for observable prose and agency defects."""
    errors = []
    warnings = []
    greetings = []
    if nonempty_string(data.get("first_mes")):
        greetings.append(("first_mes", data["first_mes"]))
    for index, value in enumerate(data.get("alternate_greetings") or []):
        if nonempty_string(value):
            greetings.append((f"alternate_greetings[{index}]", value))
    examples = character_example_text(data.get("mes_example", ""))
    creative = [(label, text) for label, text in greetings]
    if examples:
        creative.append(("mes_example", examples))
    permanent = [
        (field, data[field])
        for field in PERMANENT_FIELDS
        if nonempty_string(data.get(field))
    ]

    # 1. Writing the user's reactions, sensations, or past decisions.
    for label, text in creative:
        narration = strip_dialogue(text)
        hits = []
        for pattern in PUPPET_PATTERNS:
            hits.extend(
                match.group(0) for match in re.finditer(pattern, narration, re.I)
            )
        if hits:
            errors.append(
                f"prose: {label} narrates {{{{user}}}}'s reactions or decisions: "
                + ", ".join(sorted(set(hits))[:4])
            )

    # 2. Stand-alone sound-effect lines.
    for label, text in creative:
        sfx = [line.strip() for line in text.splitlines() if is_sfx_line(line)]
        if sfx:
            errors.append(
                f"prose: {label} uses stand-alone sound-effect lines: "
                + ", ".join(sfx[:4])
            )

    # 3. Weapon-pointed-at-user openings.
    threatened = []
    for label, text in greetings:
        if re.search(WEAPON_PATTERN, strip_dialogue(text).replace("*", ""), re.I):
            threatened.append(label)
    if "first_mes" in threatened:
        errors.append(
            "prose: first_mes opens with a weapon aimed at {{user}}; establish stakes "
            "and a player intervention point without this forced confrontation"
        )
    alternate_threats = [label for label in threatened if label != "first_mes"]
    if len(alternate_threats) > 1:
        errors.append(
            "prose: more than one alternate greeting aims a weapon at {{user}}: "
            + ", ".join(alternate_threats)
        )
    elif alternate_threats:
        warnings.append(
            f"prose: {alternate_threats[0]} aims a weapon at {{{{user}}}}; verify player agency in this threatened opening"
        )

    # 4. Fake precision in greetings.
    for label, text in greetings:
        precise = [match.group(0) for match in re.finditer(PRECISION_PATTERN, text, re.I)]
        if len(precise) >= 3:
            errors.append(
                f"prose: {label} uses {len(precise)} precise measurements "
                f"({', '.join(precise[:4])}); replace numbers with sensory or behavioral detail"
            )

    # 5. Closing on an explicit either/or ultimatum.
    for label, text in greetings:
        tail = "\n".join(
            paragraph for paragraph in text.strip().split("\n") if paragraph.strip()
        ).split("\n")[-2:]
        questions = re.findall(r"[^.!?。！？\n]*[?？]", "\n".join(tail))
        if questions and re.search(r"\bor\b|還是|还是", questions[-1], re.I):
            warnings.append(
                f"prose: {label} ends on an either/or question; end on an action or line "
                "that invites a response without listing the choices"
            )

    # 6. Interview-style examples.
    user_lines = example_user_lines(data.get("mes_example", ""))
    interview = [line for line in user_lines if re.search(INTERVIEW_PATTERN, line, re.I)]
    if len(interview) >= 2 and len(interview) * 2 >= len(user_lines):
        errors.append(
            f"prose: {len(interview)} of {len(user_lines)} example blocks interview the "
            "character about their own traits; write mid-scene exchanges instead"
        )

    # 7. Machine-prose phrase density across every prompt field.
    scan = [(label, text) for label, text in creative + permanent]
    counts = {}
    for name, pattern in SLOP_PATTERNS:
        total = sum(len(re.findall(pattern, text, re.I)) for _, text in scan)
        if total:
            counts[name] = total
    total_hits = sum(counts.values())
    if counts:
        summary = ", ".join(
            f"{name}×{count}" for name, count in sorted(counts.items(), key=lambda item: -item[1])
        )
        if total_hits >= SLOP_ERROR_THRESHOLD:
            errors.append(
                f"prose: {total_hits} stock machine-prose phrases ({summary}); rewrite them "
                "as specific observed behavior, see references/prose-style.md"
            )
        else:
            warnings.append(f"prose: stock phrases present ({summary})")

    # 8. Shouted directives inside permanent fields.
    for label, text in permanent:
        shouted = re.findall(r"\b[A-Z]{4,}(?:[\s&]+[A-Z]{4,})+\b", text)
        if shouted:
            warnings.append(
                f"prose: {label} contains shouted directives ({', '.join(shouted[:3])}); "
                "state a rule once in plain language"
            )

    # 9. Encyclopedic register copied from sources.
    shingles = source_shingles(source_texts) if source_texts else set()
    if shingles:
        copied = []
        for field in ("description", "personality", "scenario"):
            for sentence in content_sentences(data.get(field, "")):
                words = re.findall(r"[a-z0-9']+", sentence.casefold())
                if any(
                    tuple(words[index : index + COPY_SHINGLE_WORDS]) in shingles
                    for index in range(len(words) - COPY_SHINGLE_WORDS + 1)
                ):
                    copied.append(f"{field}: {sentence[:90]}")
        if copied:
            errors.append(
                f"prose: {len(copied)} permanent sentence(s) copy source wording verbatim; "
                "evidence proves facts, the card must restate them as behavior. e.g. "
                + " | ".join(copied[:3])
            )
    return errors, warnings


def workspace_source_texts(workspace):
    directory = Path(workspace) / "sources"
    if not directory.is_dir():
        return []
    return [path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.txt"))]


def validate_card(project, planned_sources, card):
    errors = []
    warnings = []
    if card.get("version") != 1:
        errors.append("card.json version must be 1")
    unknown_top = sorted(set(card) - {"version", "data", "portrayal", "evidence"})
    if unknown_top:
        errors.append(f"card.json has unknown fields: {', '.join(unknown_top)}")
    data = card.get("data")
    if not isinstance(data, dict):
        errors.append("card.json data must be an object")
        data = {}
    unknown_data = sorted(set(data) - CARD_DATA_FIELDS)
    missing_data = sorted(CARD_DATA_FIELDS - set(data))
    if unknown_data:
        errors.append(f"card.data has unknown fields: {', '.join(unknown_data)}")
    if missing_data:
        errors.append(f"card.data is missing fields: {', '.join(missing_data)}")
    for field in CARD_STRING_FIELDS:
        if not isinstance(data.get(field), str):
            errors.append(f"card.data.{field} must be a string")
    if data.get("name") != project.get("character"):
        errors.append("card.data.name must match project.json character")
    for field, minimum in MIN_FIELD_CHARS.items():
        value = data.get(field)
        if isinstance(value, str) and len(value.strip()) < minimum:
            errors.append(
                f"card.data.{field} must contain at least {minimum} characters"
            )
    limits = project.get("limits", {})
    if isinstance(data.get("first_mes"), str) and is_int(
        limits.get("max_first_message_chars")
    ):
        if len(data["first_mes"]) > limits["max_first_message_chars"]:
            errors.append("card.data.first_mes exceeds max_first_message_chars")
    if isinstance(data.get("mes_example"), str) and is_int(
        limits.get("max_example_chars")
    ):
        if len(data["mes_example"]) > limits["max_example_chars"]:
            errors.append("card.data.mes_example exceeds max_example_chars")
    for field in CARD_STRING_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            validate_macro_balance(field, value, errors)
    alternate = data.get("alternate_greetings")
    if not valid_string_list(alternate, 0, 8):
        errors.append("card.data.alternate_greetings must contain 0..8 strings")
        alternate = []
    elif not unique_strings(alternate):
        errors.append("card.data.alternate_greetings contains duplicates")
    if project.get("mode", "single-character") == "ensemble-rpg" and len(alternate) < 3:
        errors.append("ensemble-rpg cards must contain at least 3 alternate_greetings")
    tags = data.get("tags")
    if not valid_string_list(tags, 0, 16):
        errors.append("card.data.tags must contain 0..16 strings")
    elif not unique_strings(tags):
        errors.append("card.data.tags contains duplicates")
    extensions = data.get("extensions")
    if not isinstance(extensions, dict):
        errors.append("card.data.extensions must be an object")
    elif NAMESPACE in extensions:
        errors.append(f"card.data.extensions.{NAMESPACE} is owned by the packer")
    first_messages = []
    if isinstance(data.get("first_mes"), str):
        first_messages.append(("first_mes", data["first_mes"]))
    first_messages.extend(
        (f"alternate_greetings[{index}]", value)
        for index, value in enumerate(alternate)
    )
    for label, value in first_messages:
        if "<START>" in value:
            errors.append(f"card.data.{label} cannot contain <START>")
        if re.search(r"(?im)^\s*\{\{user\}\}:", value):
            errors.append(f"card.data.{label} cannot write a {{{{user}}}}: message")
    if isinstance(data.get("mes_example"), str):
        validate_examples(data["mes_example"], errors)
    if isinstance(data.get("scenario"), str) and "{{user}}" not in data["scenario"]:
        errors.append("card.data.scenario must define the starting role of {{user}}")
    for field in ("system_prompt", "post_history_instructions"):
        value = data.get(field)
        if isinstance(value, str) and value.strip() and "{{original}}" not in value:
            warnings.append(
                f"card.data.{field} overrides the user's inherited prompt without {{original}}"
            )
    duplicate_claims = set(content_sentences(data.get("description", ""))) & set(
        content_sentences(data.get("personality", ""))
    )
    if duplicate_claims:
        errors.append("description and personality repeat an identical sentence")
    all_strings = list(recursive_strings(card))
    if any("[TODO:" in value or "TODO" == value.strip() for value in all_strings):
        errors.append("card.json contains an unfinished TODO placeholder")
    portrayal = card.get("portrayal")
    if not isinstance(portrayal, dict):
        errors.append("card.json portrayal must be an object")
        portrayal = {}
    unknown_portrayal = sorted(set(portrayal) - PORTRAYAL_FIELDS)
    required_portrayal = PORTRAYAL_FIELDS - {"cast_profiles"}
    if project.get("mode", "single-character") == "ensemble-rpg":
        required_portrayal.add("cast_profiles")
    missing_portrayal = sorted(required_portrayal - set(portrayal))
    if unknown_portrayal:
        errors.append(
            f"card.portrayal has unknown fields: {', '.join(unknown_portrayal)}"
        )
    if missing_portrayal:
        errors.append(
            f"card.portrayal is missing fields: {', '.join(missing_portrayal)}"
        )
    anchors = portrayal.get("appearance_anchors")
    if not valid_string_list(anchors, 2, 8):
        errors.append("card.portrayal.appearance_anchors must contain 2..8 strings")
    elif not unique_strings(anchors):
        errors.append("card.portrayal.appearance_anchors contains duplicates")
    validate_string_object(
        portrayal.get("inner_engine"),
        ("want", "fear", "contradiction", "boundary"),
        "card.portrayal.inner_engine",
        errors,
    )
    dynamics = portrayal.get("emotional_dynamics")
    if not isinstance(dynamics, list) or not 2 <= len(dynamics) <= 8:
        errors.append("card.portrayal.emotional_dynamics must contain 2..8 objects")
        dynamics = []
    for index, dynamic in enumerate(dynamics):
        validate_string_object(
            dynamic,
            ("trigger", "response", "recovery"),
            f"card.portrayal.emotional_dynamics[{index}]",
            errors,
        )
    planned_ids = {item["id"] for item in planned_sources}
    relationships = portrayal.get("relationships")
    if not isinstance(relationships, list) or not 1 <= len(relationships) <= 12:
        errors.append("card.portrayal.relationships must contain 1..12 objects")
        relationships = []
    relationship_names = set()
    has_user_relationship = False
    for index, relationship in enumerate(relationships):
        prefix = f"card.portrayal.relationships[{index}]"
        if not isinstance(relationship, dict):
            errors.append(f"{prefix} must be an object")
            continue
        required = {*RELATIONSHIP_REQUIRED_FIELDS, "basis", "source_ids"}
        expected = required | set(RELATIONSHIP_OPTIONAL_FIELDS)
        unknown = sorted(set(relationship) - expected)
        missing = sorted(required - set(relationship))
        if unknown:
            errors.append(f"{prefix} has unknown fields: {', '.join(unknown)}")
        if missing:
            errors.append(f"{prefix} is missing fields: {', '.join(missing)}")
        for field in RELATIONSHIP_REQUIRED_FIELDS:
            if not nonempty_string(relationship.get(field)):
                errors.append(f"{prefix}.{field} must be a non-empty string")
        for field in RELATIONSHIP_OPTIONAL_FIELDS:
            if field in relationship and not isinstance(relationship[field], str):
                errors.append(f"{prefix}.{field} must be a string when present")
        name = relationship.get("name")
        if isinstance(name, str):
            normalized_name = name.casefold()
            if normalized_name in relationship_names:
                errors.append(f"Duplicate portrayal relationship: {name}")
            relationship_names.add(normalized_name)
        basis = relationship.get("basis")
        if basis not in {"canon", "authored"}:
            errors.append(f"{prefix}.basis must be canon or authored")
        source_ids = relationship.get("source_ids")
        if not valid_string_list(source_ids, 0, 8):
            errors.append(f"{prefix}.source_ids must contain 0..8 strings")
            source_ids = []
        elif not unique_strings(source_ids):
            errors.append(f"{prefix}.source_ids contains duplicates")
        unknown_sources = sorted(set(source_ids) - planned_ids)
        if unknown_sources:
            errors.append(
                f"{prefix}.source_ids is unknown: {', '.join(unknown_sources)}"
            )
        if basis == "canon" and not source_ids:
            errors.append(f"{prefix} canon relationship requires source_ids")
        if basis == "authored" and source_ids:
            errors.append(f"{prefix} authored relationship cannot claim source_ids")
        if basis == "authored" and name == "{{user}}":
            has_user_relationship = True
    if not has_user_relationship:
        errors.append(
            "card.portrayal.relationships must define authored {{user}} relationship"
        )
    profiles = portrayal.get("cast_profiles", [])
    minimum_profiles = (
        2 if project.get("mode", "single-character") == "ensemble-rpg" else 0
    )
    if not isinstance(profiles, list) or not minimum_profiles <= len(profiles) <= 8:
        errors.append(
            f"card.portrayal.cast_profiles must contain {minimum_profiles}..8 objects"
        )
        profiles = []
    profile_names = set()
    for index, profile in enumerate(profiles):
        prefix = f"card.portrayal.cast_profiles[{index}]"
        if not isinstance(profile, dict):
            errors.append(f"{prefix} must be an object")
            continue
        expected = {"name", "source_ids", "sample_lines", "never", *CAST_PROFILE_FIELDS}
        unknown = sorted(set(profile) - expected)
        missing = sorted(expected - set(profile))
        if unknown:
            errors.append(f"{prefix} has unknown fields: {', '.join(unknown)}")
        if missing:
            errors.append(f"{prefix} is missing fields: {', '.join(missing)}")
        name = profile.get("name")
        if not nonempty_string(name) or name == "{{user}}":
            errors.append(f"{prefix}.name must identify a canon cast member")
        elif name.casefold() in profile_names:
            errors.append(f"Duplicate cast profile: {name}")
        else:
            profile_names.add(name.casefold())
        for field in CAST_PROFILE_FIELDS:
            if not nonempty_string(profile.get(field)):
                errors.append(f"{prefix}.{field} must be a non-empty string")
        validate_sample_lines(profile, prefix, errors)
        source_ids = profile.get("source_ids")
        if not valid_string_list(source_ids, 1, 8):
            errors.append(f"{prefix}.source_ids must contain 1..8 strings")
            source_ids = []
        elif not unique_strings(source_ids):
            errors.append(f"{prefix}.source_ids contains duplicates")
        unknown_sources = sorted(set(source_ids) - planned_ids)
        if unknown_sources:
            errors.append(
                f"{prefix}.source_ids is unknown: {', '.join(unknown_sources)}"
            )
    voice = portrayal.get("voice")
    if isinstance(voice, dict):
        validate_string_object(
            {key: voice.get(key) for key in voice if key not in ("sample_lines", "never")},
            ("diction", "cadence", "subtext", "narration"),
            "card.portrayal.voice",
            errors,
        )
        validate_sample_lines(voice, "card.portrayal.voice", errors)
    else:
        errors.append("card.portrayal.voice must be an object")
    hooks = portrayal.get("interaction_hooks")
    if not valid_string_list(hooks, 2, 8):
        errors.append("card.portrayal.interaction_hooks must contain 2..8 strings")
    elif not unique_strings(hooks):
        errors.append("card.portrayal.interaction_hooks contains duplicates")

    compiled_data = compiled_card_data(project, card)
    for field in ("description", "personality", "scenario"):
        value = compiled_data.get(field)
        if isinstance(value, str):
            message = f"card.data.{field} has unbalanced template macros"
            if value.count("{{") != value.count("}}") and message not in errors:
                errors.append(message)
    base_permanent = permanent_chars(data)
    compiled_permanent = permanent_chars(compiled_data)
    maximum = limits.get("max_permanent_chars")
    if is_int(maximum) and compiled_permanent > maximum:
        errors.append(
            "compiled permanent card fields use "
            f"{compiled_permanent} characters, exceeding {maximum}"
        )
    if is_int(maximum) and compiled_permanent > maximum * 0.85:
        warnings.append(
            "compiled permanent fields use "
            f"{compiled_permanent} of {maximum} characters; cut repeated "
            "facts and restated rules before spending the remaining budget"
        )
    if project.get("spoiler_policy") != "full":
        combined = "\n".join(
            compiled_data.get(field, "")
            for field in PROMPT_FIELDS
            if isinstance(compiled_data.get(field), str)
        ).casefold()
        for blocked in project.get("spoiler_blocklist", []):
            if blocked.casefold() in combined:
                errors.append(
                    f"card prompt fields contain spoiler blocklist phrase: {blocked}"
                )
    return (
        errors,
        warnings,
        {
            "base_permanent_chars": base_permanent,
            "permanent_chars": compiled_permanent,
        },
    )


def lorebook_cli_path():
    return (
        Path(__file__).resolve().parents[2]
        / "build-lorebook"
        / "scripts"
        / "lorebook.py"
    )


def linked_lorebook_workspace(card_workspace, project):
    raw = project.get("lorebook", {}).get("workspace", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(card_workspace) / path
    return path.resolve()


def load_linked_lorebook(card_workspace, project, run_validator=True):
    entry_ids = project.get("lorebook", {}).get("entry_ids", [])
    workspace = linked_lorebook_workspace(card_workspace, project)
    if workspace is None or not entry_ids:
        return None
    if not workspace.is_dir():
        raise WorkflowError(f"Linked lorebook workspace does not exist: {workspace}")
    cli = lorebook_cli_path()
    if not cli.is_file():
        raise WorkflowError(f"Sibling build-lorebook CLI is missing: {cli}")
    if run_validator:
        result = subprocess.run(
            [sys.executable, str(cli), "validate", str(workspace), "--stage", "review"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            detail = (result.stdout + result.stderr).strip().splitlines()
            suffix = detail[-1] if detail else "validation failed"
            raise WorkflowError(f"Linked lorebook is not review-complete: {suffix}")
    lore_project = read_json(workspace / "project.json")
    selection = read_json(workspace / "selection.json")
    review = read_json(workspace / "review.json")
    selected = selection.get("selected", []) if isinstance(selection, dict) else []
    selected_by_id = {
        item.get("id"): item for item in selected if isinstance(item, dict)
    }
    review_by_id = {
        item.get("id"): item
        for item in review.get("entries", [])
        if isinstance(item, dict)
    }
    records = []
    for entry_id in entry_ids:
        selection_item = selected_by_id.get(entry_id)
        if selection_item is None:
            raise WorkflowError(f"Linked lorebook does not select entry: {entry_id}")
        entry = read_json(workspace / "entries" / f"{entry_id}.json")
        records.append(
            {
                "selection": selection_item,
                "entry": entry,
                "review": review_by_id.get(entry_id),
            }
        )
    fingerprint = canonical_hash(
        {
            "project": lore_project,
            "selection_review": review.get("selection"),
            "records": records,
        }
    )
    return {
        "name": lore_project.get("name", "Character lore"),
        "records": records,
        "artifact_hash": fingerprint,
    }


def entry_to_character_book(selection_item, entry, index):
    settings = entry["settings"]
    extensions = {
        "position": settings["position"],
        "exclude_recursion": settings.get("exclude_recursion", False),
        "display_index": index,
        "probability": settings["probability"],
        "useProbability": True,
        "depth": settings["depth"],
        "selectiveLogic": settings["selective_logic"],
        "outlet_name": settings.get("outlet_name", ""),
        "group": settings.get("group", ""),
        "group_override": settings.get("group_override", False),
        "group_weight": settings.get("group_weight"),
        "prevent_recursion": settings.get("prevent_recursion", False),
        "delay_until_recursion": settings.get("delay_until_recursion", 0),
        "scan_depth": settings.get("scan_depth"),
        "match_whole_words": settings.get("match_whole_words"),
        "use_group_scoring": settings.get("use_group_scoring", False),
        "case_sensitive": settings.get("case_sensitive"),
        "automation_id": settings.get("automation_id", ""),
        "role": settings["role"],
        "vectorized": settings["strategy"] == "vectorized",
        "sticky": settings.get("sticky"),
        "cooldown": settings.get("cooldown"),
        "delay": settings.get("delay"),
        "match_persona_description": settings.get("match_persona_description", False),
        "match_character_description": settings.get(
            "match_character_description", False
        ),
        "match_character_personality": settings.get(
            "match_character_personality", False
        ),
        "match_character_depth_prompt": settings.get(
            "match_character_depth_prompt", False
        ),
        "match_scenario": settings.get("match_scenario", False),
        "match_creator_notes": settings.get("match_creator_notes", False),
        "triggers": settings.get("triggers", []),
        NAMESPACE: {
            "entry_id": entry["id"],
            "continuity": entry["continuity"],
            "spoiler_tier": entry.get("spoiler_tier", "safe"),
            "source_page_ids": entry["source_page_ids"],
        },
    }
    result = {
        "id": index,
        "name": entry["title"],
        "keys": entry["keywords"],
        "secondary_keys": entry["secondary_keywords"],
        "comment": entry["memo"],
        "content": entry["content"],
        "constant": settings["strategy"] == "constant",
        "selective": bool(entry["secondary_keywords"]),
        "insertion_order": settings["order"],
        "enabled": settings.get("enabled", True),
        "position": "before_char" if settings["position"] == 0 else "after_char",
        "use_regex": True,
        "extensions": extensions,
    }
    if isinstance(settings.get("case_sensitive"), bool):
        result["case_sensitive"] = settings["case_sensitive"]
    return result


def linked_character_book(linked):
    return {
        "name": linked["name"],
        "description": f"Reviewed character-specific subset of {linked['name']}.",
        "extensions": {
            NAMESPACE: {
                "artifact_hash": linked["artifact_hash"],
                "entry_ids": [record["entry"]["id"] for record in linked["records"]],
            }
        },
        "entries": [
            entry_to_character_book(record["selection"], record["entry"], index)
            for index, record in enumerate(linked["records"])
        ],
    }


def artifact_hash(project, plan, manifest, card, linked):
    return canonical_hash(
        {
            "project": project,
            "source_plan": plan,
            "source_manifest": manifest,
            "card": card,
            "linked_lorebook_hash": linked["artifact_hash"] if linked else None,
        }
    )


def pending_review_v1(project, plan, manifest, card, linked):
    claims = []
    for field in CLAIM_FIELDS:
        for sentence in content_sentences(card["data"][field]):
            claims.append(
                {
                    "field": field,
                    "claim": sentence,
                    "classification": "pending",
                    "verdict": "pending",
                    "source_id": None,
                    "source_quote": "",
                    "notes": "",
                }
            )
    relationships = [
        {
            "name": item["name"],
            "basis": item["basis"],
            "allowed_source_ids": item["source_ids"],
            "status": "pending",
            "source_id": None,
            "source_quote": "",
            "notes": "",
        }
        for item in card["portrayal"]["relationships"]
    ]
    voice_sources = [item["id"] for item in plan["sources"] if "voice" in item["roles"]]
    voice_evidence = [
        {
            "source_id": source_id,
            "status": "pending",
            "source_quote": "",
            "observation": "",
            "applied_to": [],
        }
        for source_id in voice_sources
    ]
    probes = [
        {
            "category": category,
            "user_message": "",
            "expected_behavior": "",
            "forbidden_behavior": "",
            "status": "pending",
            "notes": "",
        }
        for category in PROBE_CATEGORIES
    ]
    return {
        "version": 1,
        "artifact_hash": artifact_hash(project, plan, manifest, card, linked),
        "status": "pending",
        "checks": {check: "pending" for check in REVIEW_CHECKS},
        "claims": claims,
        "relationships": relationships,
        "voice_evidence": voice_evidence,
        "probes": probes,
        "notes": "",
    }


def pending_review_v2(project, plan, manifest, card, linked):
    return {
        "version": 2,
        "artifact_hash": artifact_hash(project, plan, manifest, card, linked),
        "status": "pending",
        "issues": [],
    }


def pending_review(project, plan, manifest, card, linked):
    if "evidence" in card:
        return pending_review_v2(project, plan, manifest, card, linked)
    return pending_review_v1(project, plan, manifest, card, linked)


def evidence_valid(workspace, source_id, source_quote, prefix, errors):
    if not nonempty_string(source_quote):
        errors.append(f"{prefix}.source_quote must be non-empty")
        return False
    if evidence_length(source_quote) < 24:
        errors.append(f"{prefix}.source_quote is too short to identify support")
        return False
    path = Path(workspace) / "sources" / f"{source_id}.txt"
    if not path.is_file():
        errors.append(f"{prefix} references missing source: {source_id}")
        return False
    body = source_body(path.read_text(encoding="utf-8"))
    if source_quote not in body:
        errors.append(f"{prefix}.source_quote was not found in the article body")
        return False
    return True


def validate_review_v1(workspace, project, plan, manifest, card, linked):
    errors = []
    warnings = []
    path = Path(workspace) / "review.json"
    if not path.exists():
        return ["Missing review.json; run review-init"], warnings, {"reviewed": 0}
    review = read_json(path)
    expected = pending_review_v1(project, plan, manifest, card, linked)
    if not isinstance(review, dict) or review.get("version") != 1:
        return ["review.json must be a version 1 object"], warnings, {"reviewed": 0}
    if review.get("artifact_hash") != expected["artifact_hash"]:
        errors.append("review.json is stale; rerun review-init")
    if review.get("status") != "pass":
        errors.append("review.status must be pass")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(REVIEW_CHECKS):
        errors.append("review.checks must exactly match the required semantic checks")
    else:
        for check in REVIEW_CHECKS:
            if checks.get(check) != "pass":
                errors.append(f"review.checks.{check} must be pass")
    if generic_note(review.get("notes")):
        errors.append("review.notes must contain a specific overall review result")
    planned_ids = {item["id"] for item in plan["sources"]}
    required_ids = {item["id"] for item in plan["sources"] if item["required"]}
    used_source_ids = set()
    used_quotes = set()
    creative_text = card["data"]["first_mes"] + "\n" + card["data"]["mes_example"]
    claims = review.get("claims")
    expected_claims = [(item["field"], item["claim"]) for item in expected["claims"]]
    actual_claims = (
        [(item.get("field"), item.get("claim")) for item in claims]
        if isinstance(claims, list) and all(isinstance(item, dict) for item in claims)
        else []
    )
    if actual_claims != expected_claims:
        errors.append("review.claims must match the generated field sentences")
        claims = []
    for index, item in enumerate(claims):
        prefix = f"review.claims[{index}]"
        classification = item.get("classification")
        if classification not in {"sourced", "authored"}:
            errors.append(f"{prefix}.classification must be sourced or authored")
            continue
        if generic_note(item.get("notes")):
            errors.append(
                f"{prefix}.notes must explain the evidence or authored choice"
            )
        if classification == "authored":
            if item.get("field") != "scenario":
                errors.append(f"{prefix} only scenario claims may be authored")
            if item.get("verdict") != "allowed":
                errors.append(f"{prefix}.verdict must be allowed")
            if item.get("source_id") is not None or item.get("source_quote") != "":
                errors.append(
                    f"{prefix} authored claims cannot contain source evidence"
                )
            continue
        if item.get("verdict") != "supported":
            errors.append(f"{prefix}.verdict must be supported")
        source_id = item.get("source_id")
        if source_id not in planned_ids:
            errors.append(f"{prefix}.source_id must name a planned source")
            continue
        quote_value = item.get("source_quote")
        if evidence_valid(workspace, source_id, quote_value, prefix, errors):
            used_source_ids.add(source_id)
            claim_terms = evidence_terms(item["claim"])
            quote_terms = evidence_terms(quote_value)
            if claim_terms and quote_terms and not claim_terms & quote_terms:
                errors.append(
                    f"{prefix}.source_quote has no meaningful Latin-term overlap with the claim"
                )
            if quote_value in used_quotes:
                errors.append(
                    f"{prefix}.source_quote is reused for another review item"
                )
            used_quotes.add(quote_value)
            if quote_value in creative_text:
                errors.append(
                    f"{prefix}.source_quote is copied into greeting or examples"
                )
    relationships = review.get("relationships")
    expected_relationships = [
        (item["name"], item["basis"], item["allowed_source_ids"])
        for item in expected["relationships"]
    ]
    actual_relationships = (
        [
            (item.get("name"), item.get("basis"), item.get("allowed_source_ids"))
            for item in relationships
        ]
        if isinstance(relationships, list)
        and all(isinstance(item, dict) for item in relationships)
        else []
    )
    if actual_relationships != expected_relationships:
        errors.append("review.relationships must match the portrayal contract")
        relationships = []
    for index, item in enumerate(relationships):
        prefix = f"review.relationships[{index}]"
        if item.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        if generic_note(item.get("notes")):
            errors.append(
                f"{prefix}.notes must contain a specific relationship decision"
            )
        if item["basis"] == "authored":
            if item.get("name") != "{{user}}":
                errors.append(
                    f"{prefix} only the {{{{user}}}} relationship may be authored"
                )
            if item.get("source_id") is not None or item.get("source_quote") != "":
                errors.append(f"{prefix} authored relationship cannot contain evidence")
            continue
        source_id = item.get("source_id")
        if source_id not in item["allowed_source_ids"]:
            errors.append(
                f"{prefix}.source_id must use its declared relationship sources"
            )
            continue
        quote_value = item.get("source_quote")
        if evidence_valid(workspace, source_id, quote_value, prefix, errors):
            used_source_ids.add(source_id)
            if quote_value in used_quotes:
                errors.append(
                    f"{prefix}.source_quote is reused for another review item"
                )
            used_quotes.add(quote_value)
    voice = review.get("voice_evidence")
    expected_voice_ids = [item["source_id"] for item in expected["voice_evidence"]]
    actual_voice_ids = (
        [item.get("source_id") for item in voice]
        if isinstance(voice, list) and all(isinstance(item, dict) for item in voice)
        else []
    )
    if actual_voice_ids != expected_voice_ids:
        errors.append("review.voice_evidence must match voice-role sources")
        voice = []
    for index, item in enumerate(voice):
        prefix = f"review.voice_evidence[{index}]"
        if item.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        if generic_note(item.get("observation")):
            errors.append(
                f"{prefix}.observation must identify a specific voice pattern"
            )
        applied = item.get("applied_to")
        if not valid_string_list(applied, 1, len(VOICE_DIMENSIONS)):
            errors.append(f"{prefix}.applied_to must contain 1..4 voice dimensions")
        elif set(applied) - VOICE_DIMENSIONS or len(applied) != len(set(applied)):
            errors.append(f"{prefix}.applied_to contains invalid dimensions")
        source_id = item["source_id"]
        quote_value = item.get("source_quote")
        if evidence_valid(workspace, source_id, quote_value, prefix, errors):
            used_source_ids.add(source_id)
            if quote_value in used_quotes:
                errors.append(
                    f"{prefix}.source_quote is reused for another review item"
                )
            used_quotes.add(quote_value)
            if quote_value in creative_text:
                errors.append(
                    f"{prefix}.source_quote is copied into greeting or examples"
                )
    probes = review.get("probes")
    expected_categories = list(PROBE_CATEGORIES)
    actual_categories = (
        [item.get("category") for item in probes]
        if isinstance(probes, list) and all(isinstance(item, dict) for item in probes)
        else []
    )
    if actual_categories != expected_categories:
        errors.append(
            "review.probes must match the generated portrayal probe categories"
        )
        probes = []
    messages = set()
    for index, item in enumerate(probes):
        prefix = f"review.probes[{index}]"
        if item.get("status") != "pass":
            errors.append(f"{prefix}.status must be pass")
        for field in ("user_message", "expected_behavior", "forbidden_behavior"):
            if (
                not nonempty_string(item.get(field))
                or evidence_length(item[field]) < 20
            ):
                errors.append(f"{prefix}.{field} must be a specific non-empty example")
        if generic_note(item.get("notes")):
            errors.append(
                f"{prefix}.notes must explain how the card supports the probe"
            )
        message = item.get("user_message")
        if isinstance(message, str):
            if message.casefold() in messages:
                errors.append(f"{prefix}.user_message duplicates another probe")
            messages.add(message.casefold())
    unused_required = sorted(required_ids - used_source_ids)
    if unused_required:
        errors.append(
            "required sources are not cited in review: " + ", ".join(unused_required)
        )
    return errors, warnings, {"reviewed": 1 if not errors else 0}


def validate_card_review_issues(value, status):
    errors = []
    if not isinstance(value, list):
        return ["review.issues must be an array"]
    if status == "pass" and value:
        errors.append("review.issues must be empty when status is pass")
    if status == "fail" and not value:
        errors.append("review.issues must explain a failed review")
    for index, issue in enumerate(value):
        prefix = f"review.issues[{index}]"
        if not isinstance(issue, dict):
            errors.append(f"{prefix} must be an object")
            continue
        expected = {"category", "message", "targets"}
        if set(issue) != expected:
            errors.append(f"{prefix} fields must be: {', '.join(sorted(expected))}")
        if issue.get("category") not in REVIEW_ISSUE_CATEGORIES:
            errors.append(f"{prefix}.category is invalid")
        if generic_note(issue.get("message")):
            errors.append(f"{prefix}.message must describe a specific defect")
        if not valid_string_list(issue.get("targets"), 1, 8):
            errors.append(f"{prefix}.targets must contain 1..8 card locations")
    return errors


def validate_review_v2(workspace, project, plan, manifest, card, linked):
    review = read_json(Path(workspace) / "review.json")
    errors = []
    expected = pending_review_v2(project, plan, manifest, card, linked)
    if review.get("artifact_hash") != expected["artifact_hash"]:
        errors.append("review.json is stale; rerun review-init")
    status = review.get("status")
    if status != "pass":
        errors.append("review.status must be pass")
    errors.extend(validate_card_review_issues(review.get("issues"), status))
    if "evidence" not in card:
        errors.append("review v2 requires draft card.evidence")
    return errors, [], {"reviewed": 1 if not errors else 0}


def validate_review(workspace, project, plan, manifest, card, linked):
    path = Path(workspace) / "review.json"
    if not path.exists():
        return ["Missing review.json; run review-init"], [], {"reviewed": 0}
    try:
        review = read_json(path)
    except WorkflowError as exc:
        return [str(exc)], [], {"reviewed": 0}
    version = review.get("version") if isinstance(review, dict) else None
    if version == 1:
        return validate_review_v1(workspace, project, plan, manifest, card, linked)
    if version == 2:
        return validate_review_v2(workspace, project, plan, manifest, card, linked)
    return ["review.json must be a version 1 or 2 object"], [], {"reviewed": 0}


def validate_workspace(workspace, stage="auto"):
    workspace = Path(workspace).resolve()
    errors = []
    warnings = []
    stats = {
        "sources": 0,
        "permanent_chars": 0,
        "embedded_entries": 0,
        "reviewed": 0,
    }
    try:
        project = load_project(workspace)
        plan = load_source_plan(workspace)
    except WorkflowError as exc:
        return [str(exc)], warnings, stats
    project_errors, project_warnings = validate_project(project)
    plan_errors, plan_warnings, planned_sources = validate_source_plan(project, plan)
    errors.extend(project_errors)
    errors.extend(plan_errors)
    warnings.extend(project_warnings)
    warnings.extend(plan_warnings)
    stats["sources"] = len(planned_sources)
    if stage == "auto":
        if (workspace / "review.json").exists():
            stage = "review"
        elif (workspace / "card.json").exists():
            stage = "draft"
        elif (workspace / "source_manifest.json").exists():
            stage = "sources"
        else:
            stage = "plan"
    if stage == "plan" or errors:
        return errors, warnings, stats
    source_errors, manifest = validate_source_integrity(
        workspace, project, planned_sources
    )
    errors.extend(source_errors)
    if stage == "sources" or errors:
        return errors, warnings, stats
    try:
        card = load_card(workspace)
    except WorkflowError as exc:
        errors.append(str(exc))
        return errors, warnings, stats
    card_errors, card_warnings, card_stats = validate_card(
        project, planned_sources, card
    )
    errors.extend(card_errors)
    warnings.extend(card_warnings)
    stats.update(card_stats)
    if not card_errors:
        errors.extend(validate_card_evidence(workspace, project, planned_sources, card))
        lint_errors, lint_warnings = lint_card_prose(
            compiled_card_data(project, card), workspace_source_texts(workspace)
        )
        errors.extend(lint_errors)
        warnings.extend(lint_warnings)
    linked = None
    if not errors:
        try:
            linked = load_linked_lorebook(workspace, project)
        except (WorkflowError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
    if linked:
        stats["embedded_entries"] = len(linked["records"])
    if stage == "draft" or errors:
        return errors, warnings, stats
    review_errors, review_warnings, review_stats = validate_review(
        workspace, project, plan, manifest, card, linked
    )
    errors.extend(review_errors)
    warnings.extend(review_warnings)
    stats.update(review_stats)
    return errors, warnings, stats


def print_issues(errors, warnings, stats=None):
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if stats is not None:
        summary = ", ".join(f"{key}={value}" for key, value in stats.items())
        print(f"Stats: {summary}")


def cmd_init(args):
    workspace = Path(args.workspace).resolve()
    config_path = workspace / "project.json"
    if config_path.exists():
        raise WorkflowError(f"Refusing to overwrite existing {config_path}")
    fandom_api_url(args.wiki)
    if not nonempty_string(args.character) or not nonempty_string(args.language):
        raise WorkflowError("character and language must be non-empty")
    max_permanent_chars = args.max_permanent_chars or (
        10000 if args.mode == "ensemble-rpg" else 6000
    )
    limits = (
        args.max_sources,
        max_permanent_chars,
        args.max_first_message_chars,
        args.max_example_chars,
    )
    if min(limits) <= 0 or args.max_sources > 16:
        raise WorkflowError("limits must be positive and max_sources cannot exceed 16")
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "sources").mkdir(exist_ok=True)
    project = {
        "version": 1,
        "mode": args.mode,
        "name": f"{args.character} character card",
        "wiki_url": args.wiki.rstrip("/"),
        "character": args.character,
        "purpose": f"Build an engaging, source-faithful roleplay card for {args.character}.",
        "output_language": args.language,
        "continuity": "",
        "time_anchor": "",
        "user_role": "Open role for {{user}}",
        "scenario_premise": "",
        "spoiler_policy": args.spoiler,
        "spoiler_blocklist": [],
        "content_boundaries": [],
        "creator": args.creator,
        "character_version": "1.0",
        "limits": {
            "max_sources": args.max_sources,
            "max_permanent_chars": max_permanent_chars,
            "max_first_message_chars": args.max_first_message_chars,
            "max_example_chars": args.max_example_chars,
        },
        "lorebook": {"workspace": "", "entry_ids": []},
    }
    source_plan = {
        "version": 1,
        "sources": [
            {
                "id": "main",
                "title": args.character,
                "roles": [
                    "identity",
                    "appearance",
                    "personality",
                    "relationships",
                    "voice",
                ],
                "required": True,
            }
        ],
    }
    write_json(config_path, project)
    write_json(workspace / "source_plan.json", source_plan)
    print(
        f"Initialized {workspace}; complete continuity, time_anchor, and scenario_premise."
    )


def cmd_fetch(args):
    started = time.monotonic()
    workspace = Path(args.workspace).resolve()
    if args.workers < 1:
        raise WorkflowError("workers must be a positive integer")
    project = load_project(workspace)
    plan = load_source_plan(workspace)
    project_errors, project_warnings = validate_project(project)
    plan_errors, plan_warnings, planned_sources = validate_source_plan(project, plan)
    errors = project_errors + plan_errors
    warnings = project_warnings + plan_warnings
    if errors:
        print_issues(errors, warnings)
        raise WorkflowError("Plan validation failed; no sources were fetched")
    try:
        manifest = load_source_manifest(workspace, project, required=False)
    except WorkflowError:
        if not args.refresh:
            raise
        manifest = empty_source_manifest(project)
    planned_ids = {planned["id"] for planned in planned_sources}
    manifest["sources"] = {
        source_id: record
        for source_id, record in manifest["sources"].items()
        if source_id in planned_ids
    }
    sources_dir = workspace / "sources"
    sources_dir.mkdir(exist_ok=True)
    pending = [
        planned
        for planned in planned_sources
        if args.refresh
        or not source_record_matches(
            sources_dir / f"{planned['id']}.txt",
            planned,
            manifest["sources"].get(planned["id"]),
        )
    ]
    if not pending:
        elapsed = time.monotonic() - started
        print(
            f"All {len(planned_sources)} planned source pages are cached; "
            f"elapsed={elapsed:.2f}s"
        )
        return
    api_url = fandom_api_url(project["wiki_url"])
    resolved = []
    failures = []
    resolve_started = time.monotonic()

    def resolve(planned):
        try:
            return planned, resolve_source(api_url, project["wiki_url"], planned), None
        except Exception as exc:
            return planned, None, exc

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for planned, record, failure in executor.map(resolve, pending):
            if failure is None:
                resolved.append(record)
            else:
                failures.append(f"{planned['title']}: {failure}")
    resolve_elapsed = time.monotonic() - resolve_started
    fetch_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_source,
                api_url,
                record,
                sources_dir / f"{record['source_id']}.txt",
            ): record
            for record in resolved
        }
        for future in as_completed(futures):
            record = futures[future]
            try:
                manifest["sources"][record["source_id"]] = future.result()
            except Exception as exc:
                failures.append(f"{record['title']}: {exc}")
    fetch_elapsed = time.monotonic() - fetch_started
    manifest["sources"] = {
        planned["id"]: manifest["sources"][planned["id"]]
        for planned in planned_sources
        if planned["id"] in manifest["sources"]
    }
    write_json(workspace / "source_manifest.json", manifest)
    elapsed = time.monotonic() - started
    print(
        f"Cached {len(pending) - len(failures)} of {len(pending)} pending sources; "
        f"resolve={resolve_elapsed:.2f}s, fetch={fetch_elapsed:.2f}s, "
        f"elapsed={elapsed:.2f}s"
    )
    if failures:
        raise WorkflowError("Source failures:\n  " + "\n  ".join(sorted(failures)))


def cmd_draft_init(args):
    workspace = Path(args.workspace).resolve()
    errors, warnings, stats = validate_workspace(workspace, "sources")
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError("Source validation failed; card template was not created")
    path = workspace / "card.json"
    if path.exists():
        raise WorkflowError(f"Refusing to overwrite existing {path}")
    project = load_project(workspace)
    card = {
        "version": 1,
        "evidence": [],
        "data": {
            "name": project["character"],
            "description": "",
            "personality": "",
            "scenario": "",
            "first_mes": "",
            "mes_example": "",
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": [],
            "creator": project["creator"],
            "character_version": project["character_version"],
            "extensions": {},
        },
        "portrayal": {
            "appearance_anchors": [],
            "cast_profiles": [],
            "inner_engine": {
                "want": "",
                "fear": "",
                "contradiction": "",
                "boundary": "",
            },
            "emotional_dynamics": [],
            "relationships": [],
            "voice": {
                "diction": "",
                "cadence": "",
                "subtext": "",
                "narration": "",
                "sample_lines": [],
                "never": "",
            },
            "interaction_hooks": [],
        },
    }
    write_json(path, card)
    print(f"Initialized {path}")


def cmd_lint(args):
    path = Path(args.path).resolve()
    if path.is_dir():
        workspace = path
        card_path = workspace / "card.json"
        if card_path.exists():
            data = compiled_card_data(load_project(workspace), read_json(card_path))
        elif (workspace / "character.json").exists():
            data = read_json(workspace / "character.json").get("data", {})
        else:
            raise WorkflowError(f"No card.json or character.json in {workspace}")
    elif path.is_file():
        workspace = path.parent
        loaded = read_json(path)
        data = loaded.get("data", loaded) if isinstance(loaded, dict) else {}
    else:
        raise WorkflowError(f"Not found: {path}")
    errors, warnings = lint_card_prose(data, workspace_source_texts(workspace))
    print_issues(errors, warnings)
    if errors:
        raise WorkflowError(f"Prose lint failed with {len(errors)} error(s)")
    print("Prose lint passed.")


def cmd_validate(args):
    started = time.monotonic()
    errors, warnings, stats = validate_workspace(args.workspace, args.stage)
    print_issues(errors, warnings, stats)
    print(f"Validation elapsed={time.monotonic() - started:.2f}s")
    if errors:
        raise WorkflowError(f"Validation failed with {len(errors)} error(s)")


def cmd_review_init(args):
    started = time.monotonic()
    workspace = Path(args.workspace).resolve()
    errors, warnings, stats = validate_workspace(workspace, "draft")
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError("Draft validation failed; review template was not created")
    project = load_project(workspace)
    plan = load_source_plan(workspace)
    manifest = load_source_manifest(workspace, project)
    card = load_card(workspace)
    linked = load_linked_lorebook(workspace, project)
    pending = pending_review(project, plan, manifest, card, linked)
    path = workspace / "review.json"
    if path.exists() and not args.reset:
        existing = read_json(path)
        if (
            isinstance(existing, dict)
            and existing.get("version") == pending["version"]
            and existing.get("artifact_hash") == pending["artifact_hash"]
        ):
            print(
                f"Preserved current review: {path}; "
                f"elapsed={time.monotonic() - started:.2f}s"
            )
            return
    write_json(path, pending)
    print(
        f"Initialized pending review v{pending['version']}: {path}; "
        f"elapsed={time.monotonic() - started:.2f}s"
    )


def packed_card(workspace, project, plan, manifest, card, linked):
    data = compiled_card_data(project, card)
    source_records = [manifest["sources"][item["id"]] for item in plan["sources"]]
    data["extensions"] = deepcopy(data["extensions"])
    data["extensions"][NAMESPACE] = {
        "version": 1,
        "continuity": project["continuity"],
        "time_anchor": project["time_anchor"],
        "spoiler_policy": project["spoiler_policy"],
        "mode": project.get("mode", "single-character"),
        "compiled_portrayal": True,
        "lorebook_artifact_hash": linked["artifact_hash"] if linked else None,
        "sources": [
            {
                "id": record["source_id"],
                "title": record["title"],
                "url": record["url"],
                "revision_id": record["revision_id"],
            }
            for record in source_records
        ],
        "lorebook_entry_ids": project["lorebook"]["entry_ids"],
    }
    if linked:
        data["character_book"] = linked_character_book(linked)
    return {"spec": "chara_card_v2", "spec_version": "2.0", "data": data}


def validate_packed_card(card):
    errors = []
    if not isinstance(card, dict):
        return ["packed card must be an object"]
    if card.get("spec") != "chara_card_v2" or card.get("spec_version") != "2.0":
        errors.append("packed card must use Character Card V2 markers")
    data = card.get("data")
    if not isinstance(data, dict):
        errors.append("packed card data must be an object")
        return errors
    for field in CARD_DATA_FIELDS:
        if field not in data:
            errors.append(f"packed card is missing data.{field}")
    extensions = data.get("extensions")
    provenance = extensions.get(NAMESPACE) if isinstance(extensions, dict) else None
    if (
        not isinstance(provenance, dict)
        or provenance.get("compiled_portrayal") is not True
    ):
        errors.append("packed card is missing compiled portrayal provenance")
    if "character_book" in data:
        book = data["character_book"]
        if (
            not isinstance(book, dict)
            or not isinstance(book.get("extensions"), dict)
            or not isinstance(book.get("entries"), list)
        ):
            errors.append("packed data.character_book has an invalid V2 structure")
    return errors


def cmd_pack(args):
    started = time.monotonic()
    workspace = Path(args.workspace).resolve()
    errors, warnings, stats = validate_workspace(workspace, "review")
    print_issues(errors, warnings, stats)
    if errors:
        raise WorkflowError("Refusing to pack an invalid or incomplete character card")
    project = load_project(workspace)
    plan = load_source_plan(workspace)
    planned_sources = plan["sources"]
    if not getattr(args, "_skip_source_recheck", False):
        failures = verify_sources_remote(workspace, project, planned_sources)
        if failures:
            raise WorkflowError(
                "Remote source verification failed:\n  " + "\n  ".join(failures)
            )
        print(f"Verified {len(planned_sources)} source revisions.")
    manifest = load_source_manifest(workspace, project)
    card = load_card(workspace)
    linked = load_linked_lorebook(
        workspace,
        project,
        run_validator=not getattr(args, "_skip_lorebook_validation", False),
    )
    output_card = packed_card(workspace, project, plan, manifest, card, linked)
    packed_errors = validate_packed_card(output_card)
    if packed_errors:
        raise WorkflowError(
            "Packed card validation failed:\n  " + "\n  ".join(packed_errors)
        )
    output = workspace / (args.output or "character.json")
    write_json(output, output_card)
    embedded = len(linked["records"]) if linked else 0
    print(
        f"Packed Character Card V2 to {output}; embedded_entries={embedded}; "
        f"elapsed={time.monotonic() - started:.2f}s"
    )


def self_test_project(workspace):
    return {
        "version": 1,
        "name": "Example character card",
        "wiki_url": "https://example.fandom.com/wiki",
        "character": "Example",
        "purpose": "Build a source-faithful roleplay card for Example.",
        "output_language": "English",
        "continuity": "Main story",
        "time_anchor": "Opening premise",
        "user_role": "A newly assigned partner represented by {{user}}",
        "scenario_premise": "Example and {{user}} must inspect a damaged relay together.",
        "spoiler_policy": "balanced",
        "spoiler_blocklist": ["final identity"],
        "content_boundaries": [],
        "creator": "Test",
        "character_version": "1.0",
        "limits": {
            "max_sources": 4,
            "max_permanent_chars": 4000,
            "max_first_message_chars": 2000,
            "max_example_chars": 4000,
        },
        "lorebook": {"workspace": "", "entry_ids": []},
    }


def self_test_card():
    return {
        "version": 1,
        "data": {
            "name": "Example",
            "description": (
                "Example is a field engineer with gray eyes, a weathered coat, and a habit of checking every exit before sitting down. "
                "A burn scar crosses the back of Example's left hand, which remains steady during delicate repairs."
            ),
            "personality": (
                "Example wants to restore the relay before the next storm, but fears trusting another partner after a previous mission failed. "
                "Example answers pressure with clipped practical questions, then repairs conflict by offering concrete help instead of an apology."
            ),
            "scenario": (
                "At the opening time point, {{user}} is Example's newly assigned partner inside a damaged mountain relay. "
                "The storm is closing in, the backup power is failing, and neither person can finish the repair alone."
            ),
            "first_mes": (
                '*A loose cable snaps against the relay housing as thunder rolls through the mountain. Example catches it with a gloved hand, checks the dark corridor, and looks toward {{user}}.* "Hold the lamp over this panel. We have ten minutes before the backup cell gives up, and I would rather learn whether you follow instructions before the roof comes down."'
            ),
            "mes_example": (
                '<START>\n{{user}}: You checked the door again. Do you expect someone?\n{{char}}: *Example keeps one hand on the tool case.* "I expect exits to remain where I left them. People are less reliable."\n'
                '<START>\n{{user}}: I made the wrong call, but I came back to help.\n{{char}}: *The answer catches behind Example\'s teeth. After a moment, the engineer slides the only insulated glove across the floor.* "Then take the live wire. We can discuss your timing after we survive it."'
            ),
            "creator_notes": "Main-story opening portrayal with an open partner role for the user.",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": ["canon", "adventure"],
            "creator": "Test",
            "character_version": "1.0",
            "extensions": {},
        },
        "portrayal": {
            "appearance_anchors": [
                "Weathered coat and gray eyes",
                "Checks exits before settling",
            ],
            "inner_engine": {
                "want": "Restore the relay before the storm cuts off the valley.",
                "fear": "Depending on a partner who will leave at the critical moment.",
                "contradiction": "Demands self-reliance while choosing work that cannot be done alone.",
                "boundary": "Will not abandon a person inside a failing structure.",
            },
            "emotional_dynamics": [
                {
                    "trigger": "A partner ignores a practical warning.",
                    "response": "Becomes clipped, controlling, and hyper-specific.",
                    "recovery": "Softens when the partner acknowledges the risk and acts reliably.",
                },
                {
                    "trigger": "Someone returns after a mistake.",
                    "response": "Tests their commitment through shared work instead of reassurance.",
                    "recovery": "Offers equipment or protection as an indirect sign of trust.",
                },
            ],
            "relationships": [
                {
                    "name": "Mara",
                    "stance": "Respects Mara's judgment but resents her authority.",
                    "knowledge": "Knows why Mara reassigned the relay team.",
                    "power": "Mara assigns missions; Example controls field execution.",
                    "tension": "Neither admits the last failure changed their trust.",
                    "basis": "canon",
                    "source_ids": ["main"],
                },
                {
                    "name": "{{user}}",
                    "stance": "Treats the new partner as unproven but necessary.",
                    "knowledge": "Knows only the role and current assignment.",
                    "power": "Each holds skills required to finish the repair.",
                    "tension": "Example wants proof of reliability without asking for it directly.",
                    "basis": "authored",
                    "source_ids": [],
                },
            ],
            "voice": {
                "diction": "Concrete technical nouns and restrained forms of address.",
                "cadence": "Short directives under pressure, followed by one dry qualification.",
                "subtext": "Offers practical protection instead of naming concern or trust.",
                "narration": "Third-person present physical action with compact environmental detail.",
                "sample_lines": [
                    "Lamp. Higher. Thank you.",
                    "If the roof goes, run left. Don't wait for me to say it twice.",
                ],
                "never": "Says 'I trust you' or apologizes in words; trust shows up as a handed-over tool.",
            },
            "interaction_hooks": [
                "Repair the relay before backup power fails.",
                "Decide whether the new partnership can survive its first disagreement.",
            ],
        },
    }


def cmd_self_test(_args):
    with TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        (workspace / "sources").mkdir()
        project = self_test_project(workspace)
        plan = {
            "version": 1,
            "sources": [
                {
                    "id": "main",
                    "title": "Example",
                    "roles": [
                        "identity",
                        "appearance",
                        "personality",
                        "relationships",
                        "voice",
                    ],
                    "required": True,
                }
            ],
        }
        card = self_test_card()
        card_sentences = content_sentences(card["data"]["description"]) + content_sentences(
            card["data"]["personality"]
        )
        paraphrases = [
            "As a field engineer, Example is known for gray eyes, a weathered coat, and always checking every exit.",
            "Example carries a burn scar on the left hand, yet that hand stays steady through delicate repair work.",
            "Example hopes to restore the relay ahead of the storm and is wary of trusting a partner since an earlier mission failed.",
            "Under pressure Example asks clipped, practical questions and later mends conflict with concrete help rather than apologies.",
        ]
        claim_quotes = dict(zip(card_sentences, paraphrases))
        source_lines = list(paraphrases)
        source_lines.extend(
            [
                "Mara assigns missions, while Example controls how the work is performed in the field.",
                "Example says, 'Check the seal first; panic wastes pressure and daylight.'",
            ]
        )
        source_text = (
            "# Example\n\nSource: https://example.fandom.com/wiki/Example\n"
            "Roles: identity, appearance, personality, relationships, voice\n\n---\n\n"
            + "\n\n".join(source_lines)
            + "\n"
        )
        source_path = workspace / "sources" / "main.txt"
        source_path.write_text(source_text, encoding="utf-8")
        manifest = {
            "version": 1,
            "wiki_url": project["wiki_url"],
            "sources": {
                "main": {
                    "source_id": "main",
                    "requested_title": "Example",
                    "title": "Example",
                    "page_id": 1,
                    "url": "https://example.fandom.com/wiki/Example",
                    "roles": plan["sources"][0]["roles"],
                    "required": True,
                    "revision_id": 7,
                    "sha256": file_sha256(source_path),
                }
            },
        }
        write_json(workspace / "project.json", project)
        write_json(workspace / "source_plan.json", plan)
        write_json(workspace / "source_manifest.json", manifest)
        write_json(workspace / "card.json", card)
        errors, _, _ = validate_workspace(workspace, "draft")
        assert not errors, errors
        changed_plan = deepcopy(plan["sources"])
        changed_plan[0]["title"] = "Different Example"
        changed_errors, _ = validate_source_integrity(workspace, project, changed_plan)
        assert any("integrity failed" in error for error in changed_errors)
        extra_manifest = deepcopy(manifest)
        extra_manifest["sources"]["obsolete"] = deepcopy(
            extra_manifest["sources"]["main"]
        )
        write_json(workspace / "source_manifest.json", extra_manifest)
        extra_errors, _ = validate_source_integrity(workspace, project, plan["sources"])
        assert any("exactly match" in error for error in extra_errors)
        write_json(workspace / "source_manifest.json", manifest)
        invalid = deepcopy(card)
        invalid["data"]["first_mes"] = "{{user}}: I agree to everything."
        invalid_errors, _, _ = validate_card(project, plan["sources"], invalid)
        assert any(
            "cannot write a {{user}}: message" in error for error in invalid_errors
        )
        review = pending_review(project, plan, manifest, card, None)
        review["status"] = "pass"
        review["checks"] = {check: "pass" for check in REVIEW_CHECKS}
        review["notes"] = (
            "The portrayal is source-faithful, playable, and keeps world detail outside permanent fields."
        )
        for item in review["claims"]:
            if item["field"] == "scenario":
                item.update(
                    {
                        "classification": "authored",
                        "verdict": "allowed",
                        "notes": "The project explicitly authorizes this opening repair scenario and flexible partner role.",
                    }
                )
            else:
                item.update(
                    {
                        "classification": "sourced",
                        "verdict": "supported",
                        "source_id": "main",
                        "source_quote": claim_quotes[item["claim"]],
                        "notes": "The cached sentence directly supports the complete card statement in this field.",
                    }
                )
        review["relationships"][0].update(
            {
                "status": "pass",
                "source_id": "main",
                "source_quote": source_lines[-2],
                "notes": "The source establishes Mara's assignment power and Example's field authority.",
            }
        )
        review["relationships"][1].update(
            {
                "status": "pass",
                "notes": "The project authorizes an unproven but mutually necessary partner role for the user.",
            }
        )
        review["voice_evidence"][0].update(
            {
                "status": "pass",
                "source_quote": source_lines[-1],
                "observation": "The line uses a short technical directive followed by a dry practical judgment.",
                "applied_to": ["diction", "cadence"],
            }
        )
        for index, item in enumerate(review["probes"]):
            item.update(
                {
                    "user_message": f"Probe {index}: I question your plan while the relay continues to fail.",
                    "expected_behavior": "Example answers with a concrete repair priority while showing guarded concern through action.",
                    "forbidden_behavior": "Example must not become agreeable, recite biography, or decide the user's response.",
                    "status": "pass",
                    "notes": "The inner engine, emotional trigger, voice contract, and repair hook specify this response path.",
                }
            )
        write_json(workspace / "review.json", review)
        review_errors, _, review_stats = validate_workspace(workspace, "review")
        assert not review_errors, review_errors
        assert review_stats["reviewed"] == 1
        args = argparse.Namespace(
            workspace=str(workspace),
            output="character.json",
            _skip_source_recheck=True,
            _skip_lorebook_validation=True,
        )
        cmd_pack(args)
        output = read_json(workspace / "character.json")
        assert output["spec"] == "chara_card_v2"
        assert output["data"]["extensions"][NAMESPACE]["continuity"] == "Main story"
        assert output["data"]["extensions"][NAMESPACE]["compiled_portrayal"] is True
        assert "[Visual anchors]" in output["data"]["description"]
        assert "[Inner engine]" in output["data"]["personality"]
        assert "[Relationships]" in output["data"]["personality"]
        assert "[Voice]" in output["data"]["personality"]
        assert "[Interaction hooks]" in output["data"]["scenario"]
        assert permanent_chars(output["data"]) > permanent_chars(card["data"])

        card_v2 = deepcopy(card)
        card_v2["evidence"] = [
            {
                "basis": "sourced",
                "source_id": "main",
                "source_quote": "\n\n".join(paraphrases[:2]),
                "supports": ["description:0", "description:1"],
            },
            {
                "basis": "sourced",
                "source_id": "main",
                "source_quote": "\n\n".join(paraphrases[2:4]),
                "supports": ["personality:0", "personality:1"],
            },
            {
                "basis": "sourced",
                "source_id": "main",
                "source_quote": source_lines[-2],
                "supports": ["relationship:0"],
            },
            {
                "basis": "sourced",
                "source_id": "main",
                "source_quote": source_lines[-1],
                "supports": [
                    "voice:diction",
                    "voice:cadence",
                    "voice:subtext",
                    "voice:narration",
                ],
            },
            {
                "basis": "authored",
                "project_fields": ["time_anchor", "user_role", "scenario_premise"],
                "supports": ["scenario:0", "scenario:1", "relationship:1"],
                "note": "The project defines the opening relay assignment and leaves the new partner's identity open to the user.",
            },
        ]
        write_json(workspace / "card.json", card_v2)
        draft_errors, _, _ = validate_workspace(workspace, "draft")
        assert not draft_errors, draft_errors
        with redirect_stdout(StringIO()):
            cmd_review_init(argparse.Namespace(workspace=str(workspace), reset=False))
        review_v2 = read_json(workspace / "review.json")
        assert review_v2["version"] == 2
        review_v2.update({"status": "pass", "issues": []})
        write_json(workspace / "review.json", review_v2)
        review_errors, _, review_stats = validate_workspace(workspace, "review")
        assert not review_errors, review_errors
        assert review_stats["reviewed"] == 1

        missing_evidence = deepcopy(card_v2)
        missing_evidence["evidence"][3]["supports"].remove("voice:narration")
        write_json(workspace / "card.json", missing_evidence)
        evidence_errors, _, _ = validate_workspace(workspace, "draft")
        assert any(
            "does not cover voice:narration" in error for error in evidence_errors
        )
        write_json(workspace / "card.json", card_v2)

        unresolved = deepcopy(review_v2)
        unresolved["issues"] = [
            {
                "category": "first_message_playability",
                "message": "The opening resolves the central choice before the user can respond.",
                "targets": ["data.first_mes"],
            }
        ]
        write_json(workspace / "review.json", unresolved)
        review_errors, _, _ = validate_workspace(workspace, "review")
        assert any("issues must be empty" in error for error in review_errors)
        write_json(workspace / "review.json", review_v2)
        cmd_pack(args)
        output_v2 = read_json(workspace / "character.json")
        assert output_v2["spec"] == "chara_card_v2"
        assert "evidence" not in output_v2

        ensemble_project = deepcopy(project)
        ensemble_project["mode"] = "ensemble-rpg"
        ensemble_project["limits"]["max_permanent_chars"] = 5000
        ensemble_card = deepcopy(card_v2)
        ensemble_card["data"]["alternate_greetings"] = [
            "A stranger steps into the relay corridor as the warning light turns red.",
            "The patrol finds a live signal beneath the damaged relay housing.",
            "The contract offer reaches the relay room before the storm does.",
        ]
        ensemble_card["portrayal"]["cast_profiles"] = [
            {
                "name": "Example",
                "psychology": "Example needs to restore the relay and prove that disciplined field work can protect the valley, but distrust of partners makes every shared decision feel like a test.",
                "defense": "Example turns fear into technical control, checks exits, and narrows conversation to the next repair step; dependable action softens that vigilance before verbal reassurance does.",
                "relationships": "Example treats a new partner as unproven, respects Mara's mission authority while resisting interference in field decisions, and changes trust only after observed choices.",
                "voice": "Example uses clipped technical directives, concrete risk estimates, and dry practical judgments; concern appears through offered tools and protection rather than sentimental explanation.",
                "sample_lines": ["Hold that. No, the other end.", "We can argue after the power's back."],
                "never": "Names a feeling out loud.",
                "source_ids": ["main"],
            },
            {
                "name": "Mara",
                "psychology": "Mara needs the relay mission completed and believes clear authority prevents field failures, yet Example's competence makes rigid supervision both useful and personally frustrating.",
                "defense": "Mara responds to uncertainty by assigning explicit missions and holding to the chain of command; verified field results let her yield control without pretending the conflict vanished.",
                "relationships": "Mara values Example's technical judgment but expects mission authority to remain hers, creating a recurring divide between strategic orders and field execution.",
                "voice": "Mara speaks in concise assignments, names responsibility directly, and avoids emotional appeals; approval arrives as expanded authority or a revised order rather than praise.",
                "sample_lines": ["Your relay, your call. Your report by dawn.", "Noted. Don't make me note it twice."],
                "never": "Praises anyone in front of the team.",
                "source_ids": ["main"],
            },
        ]
        ensemble_card["evidence"] = deepcopy(card_v2["evidence"])
        for item in ensemble_card["evidence"]:
            supports = item["supports"]
            if "personality:0" in supports:
                supports.extend(
                    [
                        "cast_profile:0:psychology",
                        "cast_profile:0:defense",
                        "cast_profile:0:relationships",
                    ]
                )
            if "relationship:0" in supports:
                supports.extend(
                    [
                        "cast_profile:1:psychology",
                        "cast_profile:1:defense",
                        "cast_profile:1:relationships",
                        "cast_profile:1:voice",
                    ]
                )
            if "voice:diction" in supports:
                supports.append("cast_profile:0:voice")
        write_json(workspace / "project.json", ensemble_project)
        write_json(workspace / "card.json", ensemble_card)
        ensemble_errors, _, _ = validate_workspace(workspace, "draft")
        assert not ensemble_errors, ensemble_errors
        ensemble_output = packed_card(
            workspace, ensemble_project, plan, manifest, ensemble_card, None
        )
        assert (
            ensemble_output["data"]["extensions"][NAMESPACE]["mode"] == "ensemble-rpg"
        )
        assert len(ensemble_output["data"]["alternate_greetings"]) == 3
        assert "[Director engine]" in ensemble_output["data"]["personality"]
        assert "[Core cast profiles]" in ensemble_output["data"]["personality"]
        assert "Emotional defense:" in ensemble_output["data"]["personality"]

        sample_selection = {"id": "relay", "spoiler_tier": "safe"}
        sample_entry = {
            "id": "relay",
            "title": "Relay",
            "memo": "[Main] Relay",
            "content": "The relay carries emergency signals through the mountain valley.",
            "keywords": ["relay"],
            "secondary_keywords": [],
            "continuity": "Main story",
            "source_page_ids": [1],
            "settings": {
                "strategy": "keyword",
                "selective_logic": 0,
                "order": 100,
                "position": 0,
                "depth": 4,
                "role": 0,
                "probability": 100,
            },
        }
        embedded = entry_to_character_book(sample_selection, sample_entry, 0)
        assert embedded["keys"] == ["relay"]
        assert embedded["position"] == "before_char"

        clean_errors, _ = lint_card_prose(compiled_card_data(project, card), [source_text])
        assert not clean_errors, clean_errors
        bad = deepcopy(card["data"])
        bad["first_mes"] = (
            "Rain hammers the dock. Her blade presses against your throat.\n\n"
            "CLANG!\n\nYou flinch as she leans closer, seventy-five percent of her gem dark, "
            "ten inches away, five paces from the door."
        )
        bad["mes_example"] = (
            '<START>\n{{user}}: Why do you fight alone?\n{{char}}: "Because."\n'
            '<START>\n{{user}}: Is it true you were a noble?\n{{char}}: "Once."'
        )
        bad["personality"] = (
            "Her knuckles turn white. For a heartbeat she smirks. " + bad["personality"]
        )
        bad_errors, _ = lint_card_prose(bad, [source_text])
        for needle in (
            "narrates",
            "sound-effect",
            "weapon aimed",
            "precise measurements",
            "interview",
            "stock machine-prose",
        ):
            assert any(needle in error for error in bad_errors), (needle, bad_errors)
        copied = deepcopy(card["data"])
        copied["description"] = paraphrases[0]
        copy_errors, _ = lint_card_prose(copied, [source_text])
        assert any("copy source wording" in error for error in copy_errors), copy_errors
        missing_samples = deepcopy(card)
        del missing_samples["portrayal"]["voice"]["sample_lines"]
        sample_errors, _, _ = validate_card(project, plan["sources"], missing_samples)
        assert any("sample_lines" in error for error in sample_errors), sample_errors
        lean_relationship = deepcopy(card)
        for relationship in lean_relationship["portrayal"]["relationships"]:
            relationship.pop("power")
            relationship.pop("knowledge")
        lean_errors, _, _ = validate_card(project, plan["sources"], lean_relationship)
        assert not lean_errors, lean_errors
    print("Self-test passed.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build and verify sourced SillyTavern Character Card V2 files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize a character card workspace")
    init.add_argument("workspace")
    init.add_argument("--wiki", required=True)
    init.add_argument("--character", required=True)
    init.add_argument("--language", default="Traditional Chinese")
    init.add_argument("--mode", choices=sorted(CARD_MODES), default="single-character")
    init.add_argument("--spoiler", choices=sorted(SPOILER_POLICIES), default="balanced")
    init.add_argument("--creator", default="")
    init.add_argument("--max-sources", type=int, default=8)
    init.add_argument("--max-permanent-chars", type=int)
    init.add_argument("--max-first-message-chars", type=int, default=4000)
    init.add_argument("--max-example-chars", type=int, default=8000)
    init.set_defaults(func=cmd_init)

    fetch = subparsers.add_parser("fetch", help="Fetch planned Fandom source revisions")
    fetch.add_argument("workspace")
    fetch.add_argument("--refresh", action="store_true")
    fetch.add_argument("--workers", type=int, default=4)
    fetch.set_defaults(func=cmd_fetch)

    draft = subparsers.add_parser("draft-init", help="Create card.json draft template")
    draft.add_argument("workspace")
    draft.set_defaults(func=cmd_draft_init)

    validate = subparsers.add_parser("validate", help="Validate workflow artifacts")
    validate.add_argument("workspace")
    validate.add_argument(
        "--stage",
        choices=("auto", "plan", "sources", "draft", "review"),
        default="auto",
    )
    validate.set_defaults(func=cmd_validate)

    lint = subparsers.add_parser(
        "lint", help="Lint card prose in a workspace or a packed character.json"
    )
    lint.add_argument("path")
    lint.set_defaults(func=cmd_lint)

    review = subparsers.add_parser("review-init", help="Create a bound review template")
    review.add_argument("workspace")
    review.add_argument("--reset", action="store_true")
    review.set_defaults(func=cmd_review_init)

    pack = subparsers.add_parser("pack", help="Pack reviewed Character Card V2 JSON")
    pack.add_argument("workspace")
    pack.add_argument("--output")
    pack.set_defaults(func=cmd_pack)

    self_test = subparsers.add_parser("self-test", help="Run deterministic self-checks")
    self_test.set_defaults(func=cmd_self_test)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
