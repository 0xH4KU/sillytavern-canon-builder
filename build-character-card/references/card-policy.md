# Character Card Policy

## Contents

- [Goal](#goal)
- [Portrayal Contract](#portrayal-contract)
- [Draft Evidence](#draft-evidence)
- [Card Fields](#card-fields)
- [Card And Lorebook Boundary](#card-and-lorebook-boundary)
- [Continuity And Spoilers](#continuity-and-spoilers)

## Goal

Build a character or ensemble that can make coherent choices across changing scenes. A list of traits is insufficient. Connect inner causes to observable behavior and leave room for the user to affect the relationship.

## Ensemble RPG Mode

When `project.json.mode` is `ensemble-rpg`, `{{char}}` is the scene director and the available canon cast, not one named character. Keep the director's cinematic narration, cast boundaries, speaker distinction, continuity, and user-agency rules in the ordinary card fields. Use `portrayal.relationships` for recurring canon cast and the authored `{{user}}` relationship. Let each `alternate_greetings` define its own local starting role without allowing facts from one opening to leak into another.

The card may embed an explicitly selected reviewed lorebook subset, including conditional entries. The linked workspace remains the source of truth; the card's permanent fields should name the active continuity and interaction contract, not duplicate the entire cast biography.

## Portrayal Contract

Fill every `card.json.portrayal` dimension deliberately:

- `appearance_anchors`: A compact set of recognizable physical details, clothing cues, expressions, posture, or mannerisms. For ensemble cards, use recurring visual anchors for the director's scene language and principal cast rather than an inventory of every character.
- `cast_profiles`: In ensemble mode, add one profile per principal recurring character. Give each sourced `psychology`, `defense`, `relationships`, and `voice` text plus its source IDs. Each field must describe usable behavior rather than repeat appearance or biography; omit the array only for legacy single-character drafts.
- `inner_engine`: State what the character wants now, fears, contradicts within themselves, and refuses or protects. These pressures should explain their choices.
- `emotional_dynamics`: For each useful trigger, state the immediate response and how the character recovers or changes course. Include more than one emotional register.
- `relationships`: Record the character's subjective stance, knowledge, power balance, and unresolved tension. Use `basis: canon` for sourced relationships and `basis: authored` for the designed starting relationship with `{{user}}`.
- `voice`: Describe diction, cadence, subtext, and narration separately. For ensemble cards, define narrator rhythm plus the contrast that keeps principal NPC voices distinct. Use observable patterns rather than labels such as "speaks naturally."
- `interaction_hooks`: Give the character active needs, choices, obligations, conflicts, or mysteries that create scenes without forcing the user's response.

Keep causal links visible. For example, fear of abandonment may produce distancing humor, which may soften after sustained reliability and intensify again under intimacy. Do not flatten that sequence into `sarcastic but caring`.

The packer compiles this contract into standard Character Card V2 prompt fields: appearance anchors join `description`; cast profiles, the engine, emotional dynamics, relationships, and voice join `personality`; interaction hooks join `scenario`. The draft keeps the structure for validation and review, while the packed card keeps the content model-visible without adding non-standard top-level fields. Permanent-character limits apply after compilation.

## Draft Evidence

Fill top-level `card.evidence` while drafting. Sourced records name a planned source, copy an exact article-body quote, and list every claim, canon relationship, or voice target that passage supports. Authored records tie scenario, `{{user}}` relationship, or narration choices to configured project fields and explain the choice. Consolidate related targets under one passage instead of duplicating quotations. Evidence is validated with the draft and omitted from the packed Character Card V2 file.

## Card Fields

- `description`: Keep identity, appearance anchors, stable capabilities or limits, and background facts that must shape nearly every reply. In ensemble mode, identify the director role and principal cast without writing full biographies.
- `personality`: Encode motives, fears, contradictions, emotional behavior, boundaries, and subjective relationship attitudes. Avoid adjective piles and repeated facts from `description`.
- `scenario`: Establish continuity, time point, place, current circumstances, the starting relation to `{{user}}`, and immediate pressure. In ensemble mode, state that each greeting is a local scenario branch and preserve user freedom.
- `first_mes`: Begin in motion. Establish the scene, demonstrate voice and physical presence, expose a live want or tension, and offer several plausible ways for the user to respond. Never narrate the user's thoughts, decisions, dialogue, or completed reaction.
- `mes_example`: Write original examples using `<START>`, `{{user}}:`, and `{{char}}:`. Demonstrate different pressures or relationship states instead of repeating exposition.
- `alternate_greetings`: Add only genuinely different openings or scenario angles, not paraphrases of the main greeting.
- `system_prompt` and `post_history_instructions`: Leave empty by default. Non-empty values override user settings in compatible frontends and must justify their permanent cost.
- `creator_notes`: Record intended continuity, time point, user-role flexibility, spoiler level, and usage notes. Do not use it as hidden prompt content.

Permanent fields consume context on every generation. Remove duplicated biography, world exposition, and instructions already represented by the portrayal contract, greeting, or examples.

## Card And Lorebook Boundary

Put information in the card when it must influence nearly every reply:

- self-identity and physical presence;
- active motives, fears, contradictions, boundaries, and emotional logic;
- subjective attitudes toward the user and a few defining relationships;
- voice, prose behavior, present scenario, and essential capabilities.

For ensemble RPG cards, this also includes narrator behavior, cast-switching rules, and compact psychology, defenses, relationship differences, and speech patterns for every principal recurring character.

Put information in the lorebook when relevance depends on the conversation:

- world rules, history, places, factions, items, and events;
- complete biographies of supporting characters;
- relationship chronology and event details;
- specialized abilities, terminology, and conditional spoilers.

Do not restate a lorebook entry in the card. Put the behavioral consequence in the card and the explanatory facts in the lorebook. Embed only entries that are useful in this character's chats; leave the comprehensive world book separate.

## Continuity And Spoilers

- Anchor the card to one continuity and usable time point. Do not merge incompatible portrayals.
- Treat later identities, deaths, transformations, betrayals, rewritten worlds, and ending-dependent relationships as spoilers even when paraphrased.
- Keep premise-safe behavior in the card under `avoid` or `balanced`. Put reveal facts in conditional lorebook entries when the behavior can remain coherent without exposing them.
- When a secret motive must guide behavior, describe the resulting restraint, discomfort, or goal without inserting an unguarded reveal into ordinary prose.
- Card and lorebook JSON are visible to a human opening the files. Conditional retrieval limits prompt exposure; it is not encryption.
