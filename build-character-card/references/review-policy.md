# AI-Native Character Card Review

Review the card in one fresh context. The draft supplies candidate evidence; the reviewer verifies it and reports defects instead of rebuilding evidence tables.

## Procedure

1. Finish `card.json` and pass `validate --stage draft`.
2. Run `review-init`. Cards with `card.evidence` receive review v2; unchanged legacy cards may remain on review v1.
3. Use one fresh reviewer with only workspace artifacts. Keep it for one targeted repair cycle and do not fan the card out to replacement reviewers. When the host can choose, prefer a reviewer from a different model family than the drafter; a model rarely notices its own stock phrasing.
4. Read each evidence record beside only its cited cached source, loading each source once. Search linked lorebook entries by card terms and inspect only matching entries unless a concrete continuity question requires more; the deterministic validator already establishes the remaining entries' review status and artifact hash.
5. Run `character_card.py lint <work-directory>` and read its warnings as well as its errors. Lint warnings that survive into the final card need a reason.
6. Judge the card as a behavioral system, treating `card.portrayal` as model-visible compiled prompt content: causal portrayal, emotional range, relationship direction, distinctive voice, playable opening, user agency, context efficiency, spoiler safety, and lorebook complementarity. Apply the playability rubric below. For `ensemble-rpg`, verify every principal `cast_profile` has a motive-bearing psychology, a pressure-and-recovery defense pattern, relationship-specific behavior, an observable voice, sample lines that actually sound different, and a usable `never` rule; also check narrator/cast separation, speaker consistency, cast entry timing, and independent greeting branches.
7. Run these concrete tests internally. Record an issue only when a test exposes a defect:
   - **Opening direction:** Read each greeting alone and identify the live problem, immediate NPC objective, stakes or time pressure, and the player's intervention point. If these require unseen creator notes, an untriggered lorebook entry, or the player inventing the premise, report `first_message_playability` or `clarity`. Banter or atmosphere alone is not a main thread; a clear thread does not require a fixed solution or maximum danger.
   - **Passive player:** Starting from `first_mes`, imagine three consecutive `{{user}}` replies of `I look around.` Does the card give the model enough wants, hooks, and NPC agenda to move the scene without deciding anything for the user?
   - **Turn fifty:** Describe in one sentence what an ordinary mid-campaign turn looks like. If you cannot, the play loop is missing (`depth` or `execution`).
   - **Thread and rhythm:** After the first exchange, describe a next step and a quieter scene that develops the thread or its consequences. If the objective evaporates into unrelated meals or chores, or every turn must stay at peak intensity, report `execution` or, for sandbox cards, `depth`. Check that the player can reject or redirect the proposed route without the card declaring a mandatory canon outcome.
   - **Blind voice:** Strip the names from every `sample_lines` entry and example reply. Can you still tell who is speaking? Merged voices are a `voice_distinctiveness` issue.
   - **Register:** Read the compiled personality aloud. Does it read like an encyclopedia entry, a list of abstract nouns, or stacked adjectives? Would you want the roleplay model to write like this for a hundred turns?
   - **Canon spot-check:** Name three concrete details (appearance, verbal habit, relationship fact, event timing) most likely to be wrong for this time anchor and check each against the sources. Claimed verbal habits must appear in the samples or examples.
   - **Tone fidelity:** Does the card carry the source's ratio of humor, daily life, and crisis? Are the source's signature comic or uncomfortable traits still present within `content_boundaries`?
   - **Discovery:** List what a new player learns in the first three turns. If it includes the character's core wound, hidden identity, or full motive, report it.
   - **Agency:** Look for user reflexes, sensations, past decisions, canon names applied to an open-role user, and either/or closing questions.
   - **Progression:** For a progressing card, establish a later discovery and an earned relationship change. Can changing state advance without the permanent prompt restoring the opening or a `never` rule forbidding the change? For a requested fixed-period card, check that its stated limits match the experience instead.
   - **Temporal compatibility:** With linked lore, test an ordinary character name and a hypothetical question about a later event. Retrieval must not make that event current or give every character its knowledge. Then establish a different outcome in play: canon chronology must not overwrite it. Inspect relevant entries for unqualified later status and distinguish prompt guidance from actual activation gates.
   - **Independent use:** Without linked lore, does the card still support its intended play loop? Without the card, do the inspected entries identify their own continuity, period, and knowledge limits? Optional composition must not create an undeclared dependency.
8. Set `status` to `pass` with empty `issues` only when no defect remains. Do not pass a first draft by default: if you find nothing, re-run the register, blind-voice, and canon tests before passing. A failed issue names its semantic category, affected card targets, and an actionable message.
9. Return all defects together. After a batched repair, rerun `review-init` and have the same reviewer check the changed targets plus cross-cutting continuity, spoiler, agency, and lorebook-boundary behavior once. Do not reread unrelated unchanged sources.

Never edit cached sources to make evidence pass. Do not treat source headers, URLs, roles, categories, or model memory as evidence. Canon dialogue is evidence for voice patterns, not text to copy into greetings or examples.

## Playability Rubric

Treat a card as `SANDBOX` when its intended interaction is open-ended, multi-path play rather than a chiefly directed conversation or scene. This is independent of `project.mode`: a single-character card can be a sandbox, and an ensemble card need not be one. Infer the type from the stated purpose, scenario, and greeting structure.

Apply the first three dimensions to every card and the last two only to sandbox cards. Use them as semantic review dimensions, not required numeric scores. If the user requests ratings, report them outside `review.json` so its bound schema stays unchanged. These are design judgments rather than canon claims and need no source citation. Record an issue only when a weakness materially undermines the intended experience, prefer a more specific existing category when it identifies the repair better, and do not penalize intentional mystery when the user's available action is still clear.

- **Novelty** (`novelty`): Judge how clearly the core premise differs from common cards in the same lane. A familiar canon or trope can pass through a distinctive relationship position, constraint, interaction engine, or starting state; a setting reskin alone is not differentiation.
- **Clarity** (`clarity`): Judge how quickly the user can understand the setup, their role, the relevant relationship, and the expected interaction pattern from the permanent fields and opening.
- **Execution** (`execution`): Judge whether the card's construction actually delivers its stated purpose and interaction type. Use this category for an overall premise-to-implementation mismatch, not as a catch-all for a narrower defect.
- **Tension** (`tension`): Judge whether startup presents an immediate unresolved pressure, conflict, desire, or stake strong enough to invite action. Tension need not mean combat, danger, or world-scale stakes.
- **Depth** (`depth`): Judge whether the design supports materially different pathways, evolving relationships or state, and sustained replay rather than one premise repeated. Lore volume and token count are not depth by themselves.

## Draft Evidence

Target IDs use `description:N`, `personality:N`, `scenario:N`, `relationship:N`, `cast_profile:N:psychology|defense|relationships|voice`, and `voice:diction|cadence|subtext|narration`.

Sourced evidence may cover several related targets:

```json
{
  "basis": "sourced",
  "source_id": "main",
  "source_quote": "An exact article-body passage.",
  "supports": ["description:0", "description:1"]
}
```

Authored evidence ties choices to configured project fields:

```json
{
  "basis": "authored",
  "project_fields": ["user_role", "scenario_premise"],
  "supports": ["scenario:1", "relationship:0"],
  "note": "Explains why this open user relationship follows the requested premise."
}
```

Description, personality, and cast-profile targets are sourced. Canon relationships and diction, cadence, and subtext are sourced. Scenario targets may be sourced or authored; the `{{user}}` relationship is authored; narration may be sourced or deliberately authored. In ensemble mode, authored narration targets describe the director's prose contract.

`sample_lines` and `never` are creative demonstrations, not evidence targets. Review them for consistency with the sourced profile and for copied canon dialogue beyond two short catchphrases per character.

## Review V2

`review-init` owns the hash. The fresh reviewer changes only status and issues:

```json
{
  "version": 2,
  "artifact_hash": "generated",
  "status": "pass",
  "issues": []
}
```

Issue categories are the semantic dimensions listed in the skill: `source_fidelity`, `continuity`, `spoiler_safety`, `portrayal_coherence`, `emotional_range`, `relationship_fidelity`, `voice_distinctiveness`, `first_message_playability`, `user_agency`, `context_efficiency`, `lorebook_complementarity`, `novelty`, `clarity`, `execution`, `tension`, and `depth`. Use `tension` and `depth` only for sandbox cards. Each issue contains `category`, `message`, and one or more card `targets`. A passing review cannot contain issues.
