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

In an ensemble card, `portrayal.voice.narration` is the director voice; individual voices belong in the cast profiles. Character-specific facts belong in the linked lorebook when they are not needed on every turn.

Do not use generic instructions such as `write vividly`, `stay in character`, or `be engaging` as substitutes for a prose contract.

## First Message Test

A passing first message:

1. starts in a concrete place and moment;
2. shows the character doing or pursuing something;
3. demonstrates the intended dialogue and narration style;
4. introduces an unresolved pressure, want, or choice;
5. gives `{{user}}` useful information and several plausible responses;
6. leaves the user's thoughts, speech, feelings, and actions unwritten;
7. avoids biography dumps and instructions about how to roleplay.

Do not confuse length with quality. End as soon as the scene, voice, tension, and user affordance are established.

## Example Range

Use at least two `<START>` blocks. Across them, demonstrate materially different conditions, such as:

- ordinary baseline and disagreement;
- competence and uncertainty;
- guardedness and earned vulnerability;
- a canon relationship and the authored `{{user}}` relationship.

Examples teach behavior by demonstration. Do not turn them into interviews where the character lists their traits.
