# Independent Review Policy

Review is a separate verification pass, not the final paragraph of drafting. Assume every draft may be fluent but wrong. Do not use selection reasons, `spoiler_review.notes`, or model memory as evidence.

## Procedure

1. Finish and structurally validate all entries.
2. Run `review-init <workspace>` to create `review.json` with hashes and one claim row per content sentence.
3. Review selection coverage from `project.json`, `candidates.jsonl`, and `selection.json`. For each named scope, satisfy its structured continuity, required-title, and type-minimum contract. Distinct scopes cannot claim an identical single-entry backbone.
4. Start review in a fresh task or fresh-context reviewer. Give it only the workspace artifacts, not drafting rationale, previous conclusions, or the intended verdict. If no fresh context is available, stop and leave review pending.
5. Review one entry at a time with only that entry and its cached primary and supporting `sources/<page_id>.txt` files open.
6. For every factual sentence, copy a distinct quotation from the article body that supports the entire sentence. Do not quote the cached title, `Source:`, `Categories:`, separators, URLs, or navigation text. Explain specifically what the evidence establishes; `Valid.` and equivalent notes are not review.
7. Judge safe content by meaning. Identities, former forms, hidden motives, rewritten realities, loops, deaths, outcomes, and ending-dependent affiliations remain spoilers even when paraphrased.
8. Check continuity and atomicity. Split contradictory timelines and independently triggered revelations.
9. For relationship claims, confirm that the cited page actually supports the direction and state of the relationship. Cross-check the counterpart's page when the claim is asymmetric, disputed, or especially important to RP; preserve ambiguity when sources disagree. Cite every declared supporting source at least once or remove it.
10. Add realistic trigger tests. For keyword entries include at least one positive and one confusable negative. For conditional entries include at least two of each, including parent-only or adjacent non-reveal language. `review-init` derives canonical blocklisted trigger names into `exact_spoiler_terms`; every listed term must activate by itself.
11. Fix failed artifacts, rerun `review-init`, and review any reset records. Pack only after `validate --stage review` passes.

`sources/` and `source_manifest.json` are fetched evidence owned by the CLI. Never edit either to make a claim pass. Run `fetch --refresh` when a source is genuinely wrong or stale, then review every record reset by the changed source hash. Do not automate approval: scripts may inspect pending work, but they must not write statuses, verdicts, quotations, notes, exact spoiler terms, or trigger tests.

Trigger tests use the entry's explicit match settings. Inherited `null` values are tested conservatively as case-insensitive substring matching; set an explicit value when the user's global SillyTavern setting is essential.

Use realistic, entry-specific positive and confusable-negative messages. Reused placeholders such as `This is totally unrelated`, synthetic strings such as `AutomatedTriggerPass...`, and generic reasons such as `Matches topic` are invalid. `exact_spoiler_terms` must remain exactly the canonical list produced by `review-init`.

The validator accepts evidence only from the article body, requires at least 32 effective characters (CJK characters count double), rejects reused quotations for different claims, and requires meaningful Latin-term overlap when both the claim and quotation contain Latin words. These checks prevent fabricated review records; they do not replace semantic judgment.

## Review Record

`review-init` owns hashes, IDs, sentence text, and scope names. Do not alter those to force a pass. Fill the pending fields:

```json
{
  "version": 1,
  "selection": {
    "artifact_hash": "generated",
    "status": "pass",
    "scope_reviews": [
      {
        "scope": "Main Anime",
        "status": "pass",
        "covered_entry_ids": ["protagonist", "magic-system", "central-city"],
        "missing": [],
        "notes": "The premise, central cast, system, place, and pivotal threat are represented."
      }
    ],
    "notes": "Coverage checked independently against the requested scope."
  },
  "entries": [
    {
      "id": "magic-system",
      "artifact_hash": "generated",
      "status": "pass",
      "checks": {
        "source_fidelity": "pass",
        "spoiler_safety": "pass",
        "trigger_precision": "pass",
        "continuity": "pass",
        "atomicity": "pass"
      },
      "claims": [
        {
          "claim": "The exact generated sentence.",
          "verdict": "supported",
          "page_id": 123,
          "source_quote": "An exact article-body quotation that supports the complete sentence.",
          "notes": "The quotation supports the complete sentence."
        }
      ],
      "exact_spoiler_terms": [],
      "trigger_tests": [
        {
          "text": "A realistic matching message",
          "expected": true,
          "reason": "Contains the canonical concept name."
        },
        {
          "text": "A confusable but unrelated message",
          "expected": false,
          "reason": "Must not inject this entry."
        }
      ],
      "notes": "Reviewed from cached sources after drafting."
    }
  ]
}
```

Use `fail` while an issue remains. Do not describe an issue and mark the same record `pass`.
