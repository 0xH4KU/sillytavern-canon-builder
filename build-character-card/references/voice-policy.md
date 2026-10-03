# Voice And Opening Policy

## Source Voice, Do Not Copy It

Use canonical quotes, transcripts, or dialogue-bearing pages as evidence for patterns. Identify:

- vocabulary level, favored forms of address, directness, and recurring verbal habits;
- sentence length, pauses, interruptions, questions, and rhythm;
- what the character says directly versus leaves as subtext;
- how speech changes under anger, fear, vulnerability, authority, or intimacy;
- the balance of spoken dialogue, internal observation, gesture, and environmental description.

For `ensemble-rpg`, describe the narrator's prose contract separately from the recurring cast. Put each principal NPC's observable speaking pattern in its `cast_profiles[].voice`, including the contrast in diction, cadence, and subtext that survives both quiet and pressured scenes; do not make every speaker sound like the narrator.

Record short source quotations in `card.evidence` and map them to the voice dimensions they support. Write new `first_mes` and `mes_example` text; never assemble them from copied canonical lines. The fresh reviewer verifies the mapping and reports only unsupported or copied prose as issues.

## Prose Contract

Make `portrayal.voice` specific enough to guide new writing without prescribing identical sentences:

- `diction`: Word choice, formality, names, honorifics, slang, technical language, or evasions.
- `cadence`: Sentence and paragraph rhythm, hesitation, compression, repetition, or interruption.
- `subtext`: What the character conceals, implies, deflects, or tests in conversation.
- `narration`: Point of view, tense, sensory focus, gesture density, and typical response length.
- `sample_lines`: Two to six short lines that demonstrate the voice. In single-character cards they are the character's lines; in ensemble cards they are sample narrator sentences in the intended prose register. Each cast profile carries its own `sample_lines`.
- `never`: One concrete portrayal failure to avoid, such as explaining every joke or giving strangers an unsolicited psychological self-analysis. If it concerns vulnerability or disclosure, qualify it by the relevant trust or knowledge condition; do not forbid earned gratitude, apologies, explanation, or character growth forever.

Descriptions of a voice are weaker than demonstrations of it. Write sample lines first, then describe what they have in common. Lines are original unless they are short, well-known catchphrases (at most two per character); never paste long canonical dialogue. If the card claims a verbal habit (German interjections, a verbal tic, honorifics), at least one sample line and one greeting or example must actually use it.

In an ensemble card, `portrayal.voice.narration` is the director voice; individual voices belong in the cast profiles. Character-specific facts belong in the linked lorebook when they are not needed on every turn.

Do not use generic instructions such as `write vividly`, `stay in character`, or `be engaging` as substitutes for a prose contract. Read [prose-style.md](prose-style.md) for register rules, banned patterns, and exemplars.

## First Message Test

A passing first message:

1. starts in a concrete place and moment;
2. shows the character doing or pursuing something;
3. demonstrates the intended dialogue and narration style;
4. makes the main thread clear: a live problem, an immediate NPC objective, and why it matters now, at an intensity suited to the premise;
5. gives `{{user}}` a concrete intervention point and several plausible responses without listing them as an either/or question;
6. leaves the user's thoughts, speech, feelings, reflexes, sensations, and past decisions unwritten;
7. avoids biography dumps, technobabble, fake precision, sound-effect lines, and instructions about how to roleplay.

The main greeting never opens with a weapon aimed at `{{user}}`. Each alternate greeting also needs a legible main thread; vary place, mood, intensity and entry angle rather than escalating the same peak. A calm scene can pass when it carries a consequential objective, and a crisis can pass when it preserves agency and room for subsequent development. See [card-policy.md](card-policy.md#main-thread).

Do not confuse length with quality. End as soon as the scene, voice, tension, and user affordance are established.

## Example Range

Use at least two `<START>` blocks. Across them, demonstrate materially different conditions, such as:

- ordinary baseline and disagreement;
- competence and uncertainty;
- guardedness and earned vulnerability;
- a canon relationship and the authored `{{user}}` relationship.

At least one block is low-stakes or funny. At least one shows the character feeling something and not saying it.

Examples teach behavior by demonstration. Do not turn them into interviews where the character lists their traits: `{{user}}` lines must not ask the character about their own personality, powers, or past. Cut each block from the middle of a scene instead.
