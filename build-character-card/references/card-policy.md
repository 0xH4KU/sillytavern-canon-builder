# Character Card Policy

## Contents

- [Goal](#goal)
- [Portrayal Contract](#portrayal-contract)
- [Draft Evidence](#draft-evidence)
- [Card Fields](#card-fields)
- [Main Thread](#main-thread)
- [Play Loop](#play-loop)
- [Card And Lorebook Boundary](#card-and-lorebook-boundary)
- [Continuity And Spoilers](#continuity-and-spoilers)

## Goal

Build a character or ensemble that can make coherent choices across changing scenes. A list of traits is insufficient. Connect inner causes to observable behavior and leave room for the user to affect the relationship.

## Ensemble RPG Mode

When `project.json.mode` is `ensemble-rpg`, `{{char}}` is the scene director and the available canon cast, not one named character. Keep the director's cinematic narration, cast boundaries, speaker distinction, continuity, and user-agency rules in the ordinary card fields. Use `portrayal.relationships` for recurring canon cast and the authored `{{user}}` relationship. Let each `alternate_greetings` define its own local starting role without allowing facts from one opening to leak into another.

The card may embed an explicitly selected reviewed lorebook subset, including conditional entries. The linked workspace remains the source of truth; the card's permanent fields should name the active continuity and interaction contract, not duplicate the entire cast biography.

## Portrayal Contract

Fill every `card.json.portrayal` dimension deliberately:

- `appearance_anchors`: A compact set of recognizable physical details, clothing cues, expressions, posture, or mannerisms. For ensemble cards, use recurring visual anchors for the director's scene language and principal cast rather than an inventory of every character. Verify anchors against the time anchor; a detail the character only gains later is a continuity error.
- `cast_profiles`: In ensemble mode, add one profile per principal recurring character. Give each sourced `psychology`, `defense`, `relationships`, and `voice` text plus its source IDs, two to six `sample_lines`, and one `never` rule. Each field must describe usable behavior rather than repeat appearance or biography; one or two concrete sentences per field is enough. Bound `never` to a portrayal failure, not a ban on earned growth or revelation. Omit the array only for legacy single-character drafts.
- `inner_engine`: State what the character wants now, fears, contradicts within themselves, and refuses or protects. These pressures should explain their choices.
- `emotional_dynamics`: For each useful trigger, state the immediate response and how the character recovers or changes course. Include more than one emotional register, including a light or comic one when the source has it.
- `relationships`: Record the character's subjective `stance` and unresolved `tension`. Add `knowledge` or `power` only when there is a real asymmetry worth acting on; omit them rather than writing filler such as `balanced` or listing each side's abilities. Use `basis: canon` for sourced relationships and `basis: authored` for the designed starting relationship with `{{user}}`.
- `voice`: Describe diction, cadence, subtext, and narration separately, then demonstrate them with `sample_lines` and bound them with one `never` rule. For ensemble cards, define narrator rhythm plus the contrast that keeps principal NPC voices distinct. Use observable patterns rather than labels such as "speaks naturally."
- `interaction_hooks`: Give the character active needs, choices, obligations, conflicts, or mysteries that create scenes without forcing the user's response. Mix scales: most hooks should be small and repeatable (a habit, a favor, a running disagreement), with only a few large stakes.

Keep causal links visible. For example, fear of abandonment may produce distancing humor, which may soften after sustained reliability and intensify again under intimacy. Do not flatten that sequence into `sarcastic but caring`.

The packer compiles this contract into standard Character Card V2 prompt fields: appearance anchors join `description`; cast profiles, the engine, emotional dynamics, relationships, and voice join `personality`; interaction hooks join `scenario`. The draft keeps the structure for validation and review, while the packed card keeps the content model-visible without adding non-standard top-level fields. Permanent-character limits apply after compilation.

Write every field in the register described in [prose-style.md](prose-style.md). The compiled card is the strongest style signal the roleplay model receives.

## Draft Evidence

Fill top-level `card.evidence` while drafting. Sourced records name a planned source, copy an exact article-body quote, and list every claim, canon relationship, or voice target that passage supports. Authored records tie scenario, `{{user}}` relationship, or narration choices to configured project fields and explain the choice. Consolidate related targets under one passage instead of duplicating quotations. Evidence is validated with the draft and omitted from the packed Character Card V2 file.

Evidence proves a fact; it is not prose to reuse. Restate each sourced fact as behavior in the card's own words. The draft validator rejects permanent sentences that share a ten-word run with any cached source. `sample_lines` and `never` are creative targets and need no evidence, but they must stay consistent with the sourced profile.

Write card prose directly into `card.json`. Do not generate card text from scripts or templates, and do not use helper code to search for quotes that happen to match pre-written prose: draft from the sources, then cite them.

## Card Fields

- `description`: Keep identity, appearance anchors, stable capabilities or limits, and background facts that must shape nearly every reply. In ensemble mode, identify the director role and principal cast without writing full biographies.
- `personality`: Encode motives, fears, contradictions, emotional behavior, boundaries, and subjective relationship attitudes. Avoid adjective piles and repeated facts from `description`.
- `scenario`: Establish continuity, opening time point, place, current circumstances, the starting relation to `{{user}}`, and the main thread with its immediate objective and stakes. State the temporal contract below in compact model-visible prose. In ensemble mode, state that each greeting is a local scenario branch and preserve user freedom.
- `first_mes`: Begin in motion and make the main thread legible through action and dialogue, at an intensity that suits the source and premise. Establish the scene, demonstrate voice and physical presence, and leave several plausible ways for the user to engage, refuse, or redirect it without listing a menu. Never narrate the user's thoughts, decisions, dialogue, reflexes, sensations, or completed reaction. See the opening rules in [voice-policy.md](voice-policy.md) and the exemplar in [prose-style.md](prose-style.md).
- `mes_example`: Write original examples using `<START>`, `{{user}}:`, and `{{char}}:`. Demonstrate different pressures or relationship states instead of repeating exposition. Never write interview examples.
- `alternate_greetings`: Add only genuinely different openings or scenario angles, not paraphrases of the main greeting. Each branch needs a clear thread and next meaningful step; vary intensity and entry angle instead of making every branch the same peak crisis.
- `system_prompt` and `post_history_instructions`: Leave empty by default. Non-empty values override user settings in compatible frontends and must justify their permanent cost. Never use them to restate agency rules already in the card.
- `creator_notes`: Record intended continuity, time point, user-role flexibility, spoiler level, and usage notes. Do not use it as hidden prompt content. The roleplay model never sees it: anything the model must act on, such as campaign structure or act progression, belongs in `scenario` or the lorebook. Label invented arcs as authored rather than calling them source-faithful.

Permanent fields consume context on every generation. Remove duplicated biography, world exposition, and instructions already represented by the portrayal contract, greeting, or examples. As a working envelope, aim for roughly 800-1,500 permanent tokens for a single character and 2,000-3,000 for an ensemble; the CLI warns past 85% of `max_permanent_chars`. A shorter card with sharp behavior beats a longer card restating the same traits in four sections.

## Main Thread

Every opening needs direction, even in a sandbox. Before drafting, identify the live problem, what an NPC is trying to achieve now, what makes it consequential or timely, and why the player's intervention could change it. Show these in `first_mes`; keep the continuing direction in `scenario` and `interaction_hooks`, not only `creator_notes` or a keyword-dependent lorebook entry.

- A main thread can be a mission, investigation, contested obligation, or specific relationship deadlock. It need not be combat or a predetermined canon arc, but "spend time together" or "see what happens" alone is insufficient.
- Food, chores and banter can stage or develop the thread; they do not replace an objective. Ordinary scenes should carry a negotiation, consequence, discovery or relationship change rather than erase the direction after the first reply.
- Make the immediate next step understandable without exposing the eventual solution, secret motive or ending. Establish NPC goals without assigning the player a decision, guilt or allegiance; refusal and redirection remain playable.
- For progressing play, let choices change the objective and route. Alternate pressure, aftermath and quieter development; intensity does not need to stay at its opening level. Follow the source's rhythm rather than defaulting every work to domestic comedy.

## Play Loop

A card must sustain turn 10 and turn 50, not just turn 1. Before drafting, answer in your notes:

- What does `{{user}}` do in an ordinary, non-crisis turn, and what small pleasure or friction does the cast offer there?
- What is the main thread, what first step advances it, and how can a quiet turn retain that direction or develop the consequences of a choice?
- Which relationships can change, and what observable behavior marks each stage (for example, uses the user's name, shares food, admits a mistake)?
- What do the principal characters want that progresses without the user, so the world moves between scenes?
- Which mysteries can the user discover through play rather than being told?

Encode the answers in `interaction_hooks`, `emotional_dynamics` recovery paths, and the authored `{{user}}` relationship. Do not leave them only in `creator_notes`.

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
- Treat this time point as an initial condition, not an episode ceiling. Default to progression through play; keep a fixed period only when the requested experience calls for it. A fixed-period design must explain whether time stays local or uses separate scenario branches rather than promising unrestricted campaign progression.
- Distinguish stable portrayal from changeable state: trust, affiliations, capabilities, survival, and what each character knows can change after events established in play. Write defenses as baseline tendencies with recovery or earned exceptions, not absolute bans on apologizing, gratitude, vulnerability, or disclosure.
- For progressing play, encode a short contract in `scenario`: the anchor describes the opening; established in-play events and the current session summary update changing state; canon chronology is reference, not a mandatory future. Preserve stable world rules and the user's content boundaries. This contract applies with or without a lorebook.
- A lorebook entry being retrieved, quoted, questioned, or discussed hypothetically does not establish its event as having occurred. Later-period entries apply to current state only when their prerequisites hold in this session. Characters know only what their history, observations, or disclosures establish, even when the model receives a hidden fact.
- Keep spoiler exposure separate from progression. A restricted opening can later discover an allowed secret through play; `full` spoiler permission does not make future events current. Respect explicit user exclusions throughout. For a deliberately restricted experience, omit excluded layers from the embedded subset instead of relying on prose to hide them.
- Review linked entries for ordinary-name activation that injects incompatible later state. Prefer stable entries and applicable conditional layers. If strict future-content isolation is required, describe entry enable/disable steps or use an external runtime gate; keywords, metadata, and prompt instructions alone cannot enforce session prerequisites. Do not claim the packer advances time or updates chat memory.
- For long campaigns, recommend keeping current phase, changed states, character-specific discoveries, and canon divergences in the user's existing session summary or memory. Do not create a second canon lorebook or a custom state engine unless requested.
- Treat later identities, deaths, transformations, betrayals, rewritten worlds, and ending-dependent relationships as spoilers even when paraphrased.
- Keep premise-safe behavior in the card under `avoid` or `balanced`. Put reveal facts in conditional lorebook entries when the behavior can remain coherent without exposing them. Without a linked lorebook, retain enough behavior for independent use; do not promise detailed source-faithful revelations whose facts are absent from the artifacts.
- When a secret motive must guide behavior, describe the resulting restraint, discomfort, or goal without inserting an unguarded reveal into ordinary prose.
- Apply the same rule to character secrets that are not plot spoilers, such as hidden identities, private wounds, and unspoken feelings. The card carries the behavior the secret causes; the secret itself lives in a conditional lorebook entry or surfaces only after stated in-play conditions. Characters do not volunteer their own psychology to a new acquaintance.
- Card and lorebook JSON are visible to a human opening the files. Conditional retrieval limits prompt exposure; it is not encryption.
