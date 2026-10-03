# Prose Style And Exemplars

Read this before writing any card field. Models imitate the register of the card they are given: a card written in abstract, adjective-stacked prose produces replies in the same register. Write every field in plain, concrete language that you would be happy to see echoed back for a hundred turns.

## Contents

- [Register](#register)
- [Behavior Over Labels](#behavior-over-labels)
- [Openings](#openings)
- [Example Dialogue](#example-dialogue)
- [Secrets And Discovery](#secrets-and-discovery)
- [Tone Fidelity](#tone-fidelity)
- [Banned Patterns](#banned-patterns)

## Register

- A wiki is a third-person encyclopedia. A card is a set of behavioral instructions. Never carry wiki sentence structure into the card. `card.evidence` proves a fact; the card states what the fact makes the character *do*. The lint rejects permanent sentences that share a ten-word run with a source.
- Prefer verbs and observable acts to abstract nouns. `Ariel evaluates every encounter through ruthless political utility cloaked in royal poise` gives the model nothing to perform. `Ariel asks what you want before she asks your name, remembers every favor, and brings it up later as if by accident` does.
- Avoid stacked triads (`fierce, proud, and unyielding`) and two adjectives per noun. One precise detail beats three general ones.
- State each rule once. Do not repeat agency rules in description, personality, scenario, and post-history instructions. No ALL-CAPS directives.

## Behavior Over Labels

Every principal character needs habits, sample lines, and one `never` rule. Labels like `tsundere`, `stoic`, or `melodious` may appear only when a concrete behavior follows.

Weak (label-driven):

```text
Kyoko Sakura
Psychology: Kyoko is a fierce, stubborn pragmatist who lost her entire family... Beneath this harsh mercenary exterior lies a deeply wounded, compassionate heart.
Voice: Rough, insolent, and informal, peppering sentences with casual dismissals and sarcastic nicknames.
```

Strong (behavior-driven):

```text
Kyoko Sakura
Psychology: Always eating. Offers food before she offers help, and the food is the help.
Defense: Argues the selfish position loudly, then does the unselfish thing quietly; gets angry if anyone notices.
Relationships: Calls Sayaka "rookie" or "idiot" and uses her name only when something breaks.
Sounds like: "You wanna die for strangers? Do it on your own time." / "Eat. You look like a ghost."
Never: Gives a new acquaintance an unsolicited account of her family's death.
```

`sample_lines` are original lines unless a line is a short, well-known catchphrase; at most two such catchphrases per character. Keep each line under one breath. They demonstrate rhythm and diction; they are not speeches.

## Openings

Direction and intensity:

- The main `first_mes` launches a clear thread with an immediate objective, stakes and player intervention point. Choose intensity for the source and premise; a quiet scene still needs direction, and slow relationship development can begin with a forceful scene.
- Alternate greetings each need direction and should vary entry angle, mood and stakes. Do not make them all repeat the same peak crisis or the same directionless daily routine.
- Do not open with a weapon aimed at `{{user}}`. The lint rejects it in `first_mes` and in more than one alternate.
- Do not end on an explicit either/or question or ultimatum. End on an NPC action or line that invites a response without listing the options.
- Do not write `{{user}}`'s past decisions, reflexes, sensations, or feelings (`you flinch`, `your trembling hand`, `you had deliberately waited`). Do not call `{{user}}` by a canon name unless `project.user_role` fixes that identity.
- No stand-alone sound-effect lines (`CLANG!`, `*BAM!*`). No fake precision (percentages, millimeters, exact seconds) unless the character would actually say the number.

Weak (peak crisis, technobabble, user flinches, ultimatum):

```text
She slams a digital telemetry binder down onto the console... "Five tenths of a second off on the synaptic response curve!"... "Or are you just as useless as the rest of the second-rate staff in this place?"
```

Strong (authored training dispute, clear objective, humor, subtext, open response):

```text
Asuka has spread a cancelled training request across the NERV locker-room bench. Her name is already on the replacement form; the space for her partner is blank.

"They want to clear us on paperwork. Apparently looking coordinated is cheaper than being coordinated."

She sets her pen beside the empty space. "Operations closes the schedule after the briefing. I want our joint drill back on it. They won't accept the request from one pilot."

Asuka smooths a fold in the paper that is already flat. "Read it before you start apologizing. I haven't blamed you for anything. Yet."
```

The problem is a cancelled joint drill; the objective is to restore it before the schedule closes. The player can question the plan, support it, refuse, or propose another route. The request exposes Asuka's need for cooperation without narrating the player's response or making a future Angel attack inevitable. These administrative details are authored, not asserted canon.

## Example Dialogue

- Never write `{{user}}` lines that ask the character about their own traits or past (`Why do you fight alone?`, `Is it true you have superhuman strength?`). The lint rejects example sets where half or more blocks do this.
- Cut examples from the middle of scenes: a task, an argument, a meal, a mistake.
- Include at least one low-stakes or funny block, and at least one block where the character feels something and does not say it.
- Characters do not narrate their own psychology. A reply that explains a wound (`When you left, I swore I would never cry again`) belongs only after sustained trust in play, never in an example.

## Secrets And Discovery

Curiosity is the main replay engine. Do not spend it in the permanent fields.

- Put the *behavior* a secret causes in the card: what the character avoids, what makes them go quiet, which name they react to.
- Put the secret itself in a conditional lorebook entry, or state the in-play condition that must be met before it surfaces.
- Do not write inner monologue revealing a hidden identity in a greeting unless the greeting's premise is that the user has just discovered it.

## Tone Fidelity

Before drafting, write down in one line what the source is like to *read*: its humor, pace, and ratio of daily life to crisis. The card must carry that ratio. A comedy-heavy or slice-of-life source does not become an action thriller because thrillers are easy to write. If a character's signature voice includes something uncomfortable or silly (a protagonist's embarrassing inner monologue, a running gag), keep it within `content_boundaries` rather than sanding it off.

Do not invent arcs and call the card source-faithful. Authored story beats are allowed; label them authored in `creator_notes`.

## Banned Patterns

The CLI lint (`character_card.py lint` and `validate --stage draft`) blocks these when they reach the error threshold. Do not dodge it with synonyms; remove the habit.

English: knuckles whitening, `for a heartbeat`, `a fraction of an inch`, `razor-sharp` / `razor's edge`, `breathtaking`, `intoxicating`, `silk and venom`, voices cracking or breaking, shivers down spines, smiles that don't reach eyes, `smirk`, `palpable`, `testament to`, `unwavering` / `unyielding`, `barely above a whisper`, thick air, `can't help but`, `ozone`, `predatory`.

Chinese: 指節發白, 心跳漏了一拍, 不易察覺, 嘴角勾起, 眼底閃過, 空氣凝固, 一絲玩味, 喉結滾動, 低沉磁性的嗓音, 不容置疑.

Also avoid, even though the lint cannot always catch them: every emotion shown at maximum (`hysterical`, `manic`, `shattered`); every sentence ending in a dramatic beat; technobabble standing in for character; narrator commentary that explains the subtext the scene already shows.
