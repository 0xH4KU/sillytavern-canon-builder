# Selection Policy

## Contents

- [Goal](#goal)
- [`project.json`](#projectjson)
- [Selection Method](#selection-method)
- [Relationship Sources](#relationship-sources)
- [Spoilers And Continuity](#spoilers-and-continuity)
- [`selection.json`](#selectionjson)

## Goal

Select a compact, balanced set of concepts before reading full articles. Favor coverage and canonical importance over exhaustive character lists.

## `project.json`

Set these fields deliberately:

- `purpose`: The intended roleplay or writing use.
- `scope`: Included works, eras, media, or themes.
- `scope_requirements`: One enforceable contract per scope, containing its allowed continuities, premise-safe required titles, and per-type coverage minimums.
- `continuities`: Names the output must use when facts differ.
- `required_titles`: Canonical Fandom page titles that must appear in a core selection.
- `coverage_minimums`: Minimum selected entries by entity type. Use only types relevant to this fandom.
- `spoiler_blocklist`: Reveal-specific words or phrases forbidden from restricted output.
- `exclude_title_patterns`: Additional regular expressions for deterministic exclusion.
- `exclude_category_patterns`: Additional category regular expressions for narrowing large wikis or excluding out-of-scope continuities.
- `relationship_mode`: Use `targeted` for relationship-aware RP lorebooks and `off` only when cross-entity relationships are irrelevant.
- `limits`: Hard caps. Raise them only after reviewing the discovered catalog.

For a request described as comprehensive, list every named series, film, game, manga, or continuity in `scope`. Do not silently narrow the request to the main work. Resolve scope before selection.

Use project schema version 3 for new work. Draft the scope contract before selecting entries:

```json
{
  "version": 3,
  "scope": ["Example Side Story"],
  "continuities": ["Side Story"],
  "scope_requirements": [
    {
      "scope": "Example Side Story",
      "continuities": ["Side Story"],
      "required_titles": ["Side Story Protagonist"],
      "coverage_minimums": {"character": 2, "location": 1, "world_lore": 1}
    }
  ],
  "relationship_mode": "targeted"
}
```

Multi-scope projects require version 3. Each scope contract must name at least two backbone titles and require at least two entity types, including a central actor type (`character`, `faction`, or `species`) and a setting/system type (`world_lore`, `location`, `item`, `event`, or `species`). This prevents a sequel or side story from passing coverage with one token entry.

Let the agent propose this compact contract from candidate metadata. The operator reviews it once; they do not classify the whole catalog manually.

## Selection Method

1. Inventory categories and likely core pages with `catalog`, `rg`, and `jq`.
2. Build the backbone first: defining world rules, principal characters, central locations and factions, pivotal items, and premise-level major events.
3. Add recommended concepts only when they recur, connect core entries, or carry a distinct roleplay function.
4. Omit one-scene characters, variants, costumes, songs, merchandise, episode pages, galleries, histories, walkthroughs, and narrow trivia unless the project scope explicitly requires them.
5. Merge pages that define the same concept by listing several `page_ids`; never create duplicate concepts for aliases or supplemental subpages.
6. Put uncertain essentials in `manual_review`. Omitted ordinary candidates need no decision record.
7. Verify entity types semantically. A coverage quota is not satisfied by relabeling an enemy, person, or event as a faction.

After drafting the selection, perform a separate coverage pass from `project.json` rather than defending the first pass. For every item in `scope`, identify its central actor, defining system, important location or faction, and pivotal item or event where applicable. A global quota does not prove that each included work is represented. If a named scope has only one generic location or mechanic, either add its missing backbone or remove that scope with the user's approval.

Entity types are fixed:

`world_lore | character | location | faction | item | event | species | other`

Importance is fixed for selected concepts:

`core | recommended`

Spoiler tiers are fixed:

- `safe`: Normal lore that may activate from ordinary names and aliases. Only safe entries count toward coverage minimums and required-title checks.
- `conditional`: A reveal layer that enters context only after an explicit spoiler topic or a parent concept plus reveal-intent terms is mentioned. Set `spoiler_parent_id` to a selected safe entry.

A conditional entry may reuse its safe parent's primary source page. Other duplicate primary assignments remain invalid. `supporting_page_ids` are evidence-only pages and may be shared without creating entries or affecting coverage.

## Relationship Sources

After fetching primary pages, inspect core and recurring concepts for RP-relevant relationships: trust, conflict, dependence, hierarchy, family, affiliation, obligations, and asymmetric knowledge. Follow a related canonical page only when it can verify or materially clarify such a relationship.

- Put up to three related candidate IDs in `supporting_page_ids`; keep defining pages in `page_ids`.
- In `targeted` mode, give every core character or faction at least one supporting source. Remove a supporting source if no final claim uses it.
- A canonical `/Relationships` subpage may be used as supporting evidence even though deterministic rules exclude it as a standalone entry.
- Prefer another selected concept's canonical page over adding a duplicate relationship entry.
- Do not follow every named link, fetch one-scene contacts, or add pages merely to fill the allowance.
- Keep relationship facts in the correct continuity and move identity, betrayal, death, or ending-dependent changes into conditional layers.

## Spoilers And Continuity

- `avoid`: Select only `safe` premise facts. Any moderate or major risk requires an explicit override.
- `balanced`: Keep ordinary entries `safe`. Preserve RP-useful identities, transformations, motives, loops, fates, and endings as `conditional` entries instead of deleting or exposing them. A safe entry with moderate or major risk still requires an override.
- `full`: Permit canonical spoilers, while still using `conditional` entries when on-demand retrieval saves context.
- Judge spoilers semantically, not by blocklist wording. Rephrasing a forbidden reveal with a euphemism is still a spoiler.
- Inclusion of a sequel or spin-off does not make revelations about earlier works safe. Write its stable premise in `safe`; isolate prior identities, rewritten worlds, secret origins, and ending-dependent status in `conditional` children.
- Split a safe identity from every hidden former identity or transformation. For example, a character profile must not disclose that the character was previously a named Witch merely because both facts occur on one source page.
- Do not merge contradictory timelines. Use one entry per continuity when the same concept materially differs.
- Keep safe-entry `reason` and `spoiler_reason` spoiler-free because they appear during review. Label conditional entries explicitly for the operator.

## `selection.json`

```json
{
  "selected": [
    {
      "id": "soul-gem",
      "title": "Soul Gem",
      "page_ids": [123],
      "supporting_page_ids": [124],
      "entity_type": "item",
      "importance": "core",
      "continuity": "Main anime",
      "confidence": 0.98,
      "manual_override": false,
      "reason": "Defining object used by every magical girl.",
      "spoiler_risk": "none",
      "spoiler_reason": "Only premise-safe mechanics belong in this base entry.",
      "spoiler_override": false,
      "spoiler_tier": "safe",
      "allow_rule_excluded": false
    },
    {
      "id": "soul-gem-hidden-mechanics",
      "title": "Soul Gem: Hidden mechanics",
      "page_ids": [123],
      "entity_type": "item",
      "importance": "recommended",
      "continuity": "Main anime",
      "confidence": 0.98,
      "manual_override": false,
      "reason": "Reveal layer for direct questions about the item's true nature.",
      "spoiler_risk": "major",
      "spoiler_reason": "Contains a central transformation reveal.",
      "spoiler_override": false,
      "spoiler_tier": "conditional",
      "spoiler_parent_id": "soul-gem",
      "allow_rule_excluded": false
    }
  ],
  "manual_review": [
    {
      "page_id": 456,
      "reason": "Unclear whether this spin-off is in scope."
    }
  ]
}
```

Use short ASCII kebab-case IDs. `page_ids` must refer to defining canonical candidates. `supporting_page_ids` is optional, evidence-only, reusable, and limited to three pages per entry. Set an override only when the user or stated scope justifies it.
