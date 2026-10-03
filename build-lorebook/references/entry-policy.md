# Entry Policy

## Contents

- [Entry Content](#entry-content)
- [Draft Evidence](#draft-evidence)
- [Relationship Enrichment](#relationship-enrichment)
- [Temporal Applicability](#temporal-applicability)
- [Spoiler Policy](#spoiler-policy)
- [Conditional Spoiler Layers](#conditional-spoiler-layers)
- [SillyTavern Settings](#sillytavern-settings)
- [`entries/<id>.json`](#entriesidjson)

## Entry Content

- Write a standalone reference, not a plot synopsis.
- Prefer stable identity, appearance, function, rules, limitations, relationships, and roleplay-relevant behavior.
- Attribute the continuity in the prose when confusion is plausible.
- Preserve uncertainty from the source. Do not upgrade speculation into fact.
- Use only cached selected sources. If a detail is absent, omit it; familiarity with the canon is not evidence.
- Prefer literal, source-supported wording over decorative specificity. Do not add architecture, motives, powers, quantities, or causal explanations merely because they sound plausible.
- Keep each sentence easy to map to one exact source-body quotation. Split compound sentences when their clauses require different evidence.
- Keep title and memo distinct: `title` is the canonical concept name; `memo` is a concise operator label such as `[Main] Soul Gem`.
- Use distinctive names and genuine aliases as keys. Do not use the franchise name or broad generic words as triggers.

## Draft Evidence

Add `source_evidence` to every new entry while the relevant source is already open. Each record contains `page_id`, an exact article-body `source_quote`, and zero-based `supports` indexes into the entry's content sentences. One passage may support several related sentences. Cover every sentence and cite every declared source page. This field is validated with the draft and omitted from the packed lorebook.

## Relationship Enrichment

- For core and recurring entities, include stable RP-relevant ties: what each party knows, wants, owes, fears, trusts, contests, or controls.
- Read the primary page first. When its account is thin or one-sided, follow the named counterpart, faction, family, or canonical `/Relationships` page and add its ID to `supporting_page_ids` before fetching it.
- Use at most three supporting pages per entry and only for concrete relationship claims. Do not summarize every interaction or reproduce another character's biography.
- State the relevant continuity or time point when a relationship changes. Keep later betrayals, identities, deaths, and outcome-dependent affiliations in conditional entries.
- Prefer relationship facts that change dialogue or behavior in RP. Omit trivia that does not affect how entities perceive or respond to one another.

## Temporal Applicability

- Default to one reusable canon reference, not a separate book for each character card's opening. Stable identity and world rules belong in base entries; split materially changed status, relationships, powers, and event outcomes into applicable layers. Use existing conditional children when these layers reuse a parent's source page, respecting the project's spoiler policy.
- Put the relevant continuity, period or prerequisite, and any character-knowledge limit in `content`, not only in `memo`, `settings_rationale`, or export metadata. Only prompt-visible wording can guide the model after retrieval. Use source-supported periods and knowledge claims; applicability framing must not invent facts and remains subject to sentence-level evidence review.
- Describe canon events as events in the source chronology, not scheduled events in the current session. A later fate or affiliation does not overwrite an earlier-period portrayal, a survival divergence, or a different outcome established in play. Stable world rules still apply unless the user deliberately changes the premise.
- Separate an objective fact from who knows it. Receiving secret mechanics in model context does not let every NPC explain them; state the sourced knowledge asymmetry where it affects play. Do not equate spoiler permission with character knowledge.
- Topic activation is not event confirmation. A hypothetical question such as "Can Sayaka avoid becoming a witch?" may retrieve a canon outcome, but does not establish that she has transformed. A layer should describe its canon context without asserting that context is the current session.
- For standalone use, make temporal entries understandable without a companion card. For composition, the card supplies the opening and the current session summary supplies changes and divergences. Keep session-specific progress out of the reusable canon source book; recommend an existing chat summary or memory when progression needs tracking.
- In a companion book, cover facts needed to pursue the card's main thread, such as relevant locations, authority, resources and constraints. Keep authored opening goals and immediate stakes in the card, so an inactive keyword cannot hide the direction. Do not turn sourced event entries into a compulsory quest order or invent canonical facts to justify an authored plot.
- Keywords and recursion isolation control retrieval, not chronological state. These artifacts provide semantic applicability guidance, not automatic phase advancement or guaranteed secret isolation. When strict isolation is requested, keep unavailable layers disabled or outside the active subset until deliberately enabled; an external runtime gate is needed for automatic enforcement.

For example, a later-outcome layer can describe a transformation as occurring in the original story after its prerequisite events, rather than saying the character "is now" transformed. If the current chat instead establishes that the character was saved, that outcome remains canon reference, not the session's present state. Keep any reveal-specific example out of a safe entry.

## Spoiler Policy

- `avoid`: Opening-premise facts only. Remove later events, outcomes, causes, discoveries, changed status, secret identities, deaths, transformations, and ending information.
- `balanced`: Put stable facts in `safe` entries and RP-useful reveals in separate `conditional` entries. Do not place final fates, endgame events, hidden identities, or twist-dependent forms in a safe entry.
- `full`: Canonical spoilers are allowed, but continuities must remain separate. Conditional retrieval may still be used to save context.
- A concept whose title is itself a spoiler must be `conditional` under `balanced` unless the user explicitly overrides it.
- Perform a fresh spoiler review after drafting; do not rely on the drafting pass to review itself.
- Treat euphemisms and paraphrases as the same reveal. A phrase such as "higher divine realm" does not make an ending-dependent affiliation safe.

## Conditional Spoiler Layers

Make every conditional entry a child of a safe entry with `spoiler_parent_id`. Keep it out of normal context with both deterministic retrieval and recursion isolation:

1. Use `strategy: keyword`; never use `constant` or `vectorized`.
2. Set `exclude_recursion: true` so text inserted by another lorebook entry cannot reveal it.
3. Set `prevent_recursion: true` so its revealed content cannot cascade into further entries.
4. For a distinct spoiler name, use only that name and real aliases as primary keys, such as `Oktavia von Seckendorff` or `圓環之理`.
5. To answer questions such as "What is Kyubey's true purpose?", reuse the safe parent keys as primary keys and require reveal-intent terms such as `真相`, `真正目的`, `熵`, or `結局` as secondary keys with `selective_logic: 0` (AND ANY).
6. Never use generic reveal words such as `秘密`, `結局`, or `真相` alone as primary keys.
7. Start the memo with `[Spoiler]` so the operator can recognize the layer. The memo itself is not inserted into model context.
8. Choose exactly one activation mode per entry: distinct spoiler names as primary keys with no secondary filter, or safe parent keys plus specific reveal-intent secondary keys. Do not put a distinct spoiler name in the secondary list where it cannot activate alone.
9. Keep one reveal boundary per conditional entry. Time-loop origins and a later-film transformation need separate entries because a question about one must not inject the other.

This keeps spoilers out of prompt context until a matching topic activates the entry; it does not enforce story prerequisites or character knowledge, and does not hide content from a human opening the lorebook JSON or editor. See Temporal Applicability above.

## SillyTavern Settings

Choose settings for behavior, not cosmetic variation:

- `strategy`: Use `keyword` for normal factual lore. Use `constant` only for a tiny amount of always-required global context. Use `vectorized` only when semantic retrieval is intentionally available.
- `secondary_keywords` and `selective_logic`: Add only to prevent false activation or distinguish concepts. Empty means no optional filter.
- `order`: Larger values are inserted later and have more impact. A useful baseline is 200 for foundational rules, 150 for core concepts, and 100 for supporting entries; change it when prompt priority actually differs.
- `position`: Usually 0 (before character definitions). Use 1 for lore that should outweigh character definitions, 4 only for deliberate in-chat injection, and 7 only with a real outlet name.
- `depth` and `role`: Matter only at position 4. Keep explicit values so the decision remains visible.
- `probability`: Keep factual lore at 100. Lower it only for intentionally random events.
- `scan_depth`, `case_sensitive`, and `match_whole_words`: `null` inherits the user's global setting. Set `match_whole_words: false` whenever an entry has Chinese or Japanese keys because whole-word matching depends on whitespace.
- `triggers`: Empty means all generation types. Never list every trigger; that is redundant.
- Inclusion groups, timed effects, automation IDs, outlets, recursion flags, and additional matching sources stay empty/default unless the entry has a specific operational requirement. Conditional spoilers are the explicit recursion-flag exception described above.
- Explain every meaningful deviation in `settings_rationale`. Defaults do not need artificial variation.

See the current SillyTavern World Info documentation when uncertain: <https://docs.sillytavern.app/usage/core-concepts/worldinfo/>.

## `entries/<id>.json`

```json
{
  "id": "soul-gem",
  "title": "Soul Gem",
  "memo": "[Main] Soul Gem",
  "content": "A Soul Gem is the magical focus carried by a contracted magical girl. It stores power, supports transformation, and becomes clouded as magic is spent.",
  "keywords": ["Soul Gem"],
  "secondary_keywords": [],
  "entity_type": "item",
  "importance": "core",
  "continuity": "Main anime",
  "source_page_ids": [123, 124],
  "source_evidence": [
    {
      "page_id": 123,
      "source_quote": "An exact article-body passage supporting the entry's first sentence.",
      "supports": [0]
    },
    {
      "page_id": 124,
      "source_quote": "An exact article-body passage supporting the second sentence.",
      "supports": [1]
    }
  ],
  "spoiler_tier": "safe",
  "spoiler_review": {
    "policy": "balanced",
    "checked": true,
    "notes": "Removed endgame mechanics and outcomes."
  },
  "settings": {
    "strategy": "keyword",
    "selective_logic": 0,
    "order": 150,
    "position": 0,
    "depth": 4,
    "role": 0,
    "probability": 100,
    "scan_depth": null,
    "case_sensitive": null,
    "match_whole_words": null,
    "triggers": []
  },
  "settings_rationale": "Core factual item; ordinary keyword activation with stronger insertion priority."
}
```

A conditional child that reuses the safe keys must add a reveal-intent filter:

```json
{
  "id": "soul-gem-hidden-mechanics",
  "title": "Soul Gem: Hidden mechanics",
  "memo": "[Spoiler][Main] Soul Gem truth",
  "content": "The reveal-only explanation is written here as a standalone sourced reference of at least eighty characters.",
  "keywords": ["Soul Gem", "靈魂寶石"],
  "secondary_keywords": ["真相", "魔女化", "真正本質"],
  "entity_type": "item",
  "importance": "recommended",
  "continuity": "Main anime",
  "source_page_ids": [123],
  "source_evidence": [
    {
      "page_id": 123,
      "source_quote": "An exact reveal-bearing article passage supporting this entry.",
      "supports": [0]
    }
  ],
  "spoiler_tier": "conditional",
  "spoiler_parent_id": "soul-gem",
  "spoiler_review": {
    "policy": "balanced",
    "checked": true,
    "notes": "Major reveal isolated behind explicit intent terms."
  },
  "settings": {
    "strategy": "keyword",
    "selective_logic": 0,
    "order": 150,
    "position": 0,
    "depth": 4,
    "role": 0,
    "probability": 100,
    "scan_depth": null,
    "case_sensitive": null,
    "match_whole_words": false,
    "exclude_recursion": true,
    "prevent_recursion": true,
    "triggers": []
  },
  "settings_rationale": "Reveal only after the item and a truth-seeking term are both present; recursion is blocked."
}
```

Rare settings may be omitted; the packer supplies conservative SillyTavern defaults. The fields shown above are required so important behavior is reviewed rather than silently defaulted.

`source_page_ids` must include both defining `page_ids` and any `supporting_page_ids` declared by the selection. The `spoiler_review` object records the drafting decision only. The mandatory independent verdict belongs in `review.json`; see [review-policy.md](review-policy.md).
