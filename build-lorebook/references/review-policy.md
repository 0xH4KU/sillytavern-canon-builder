# AI-Native Independent Review

Review is a fresh semantic verification pass. The draft carries candidate evidence; the reviewer checks it rather than rebuilding a citation ledger.

## Procedure

1. Finish all entries and pass `validate --stage entries`.
2. Run `review-init`. Entries with `source_evidence` receive review v2; unchanged legacy work may remain on review v1.
3. Use one fresh-context reviewer with only workspace artifacts. Keep it for the repair loop and never fan entries out across replacement reviewers.
4. Review pending entries in small batches. For each entry, read its content, `source_evidence`, and only the cited cached source pages.
5. Try to falsify the draft evidence: verify that each quote supports every mapped sentence without omitted qualifiers, continuity drift, or relationship-direction errors. A quote may support several related sentences.
6. Judge semantic spoiler safety and atomicity. Keep independent revelations and contradictory continuities separate.
7. Let the CLI check quote presence, cache integrity, source coverage, basic activation logic, and exact spoiler terms. Add `risk_tests` only for realistic ambiguity, alias collision, or false-positive cases requiring semantic imagination.
8. Set the entry status to `pass` with an empty issue list only when no defect remains. For a failure, add concise issues with category, affected targets, and an actionable message.
9. Review selection once at the project level. Report only concrete coverage or scope defects.
10. Return all defects together. After the host fixes them, rerun `review-init` without `--reset` and recheck only reset records once.

Never edit `sources/` or `source_manifest.json` to make evidence pass. Never copy source metadata, navigation, or URLs as evidence. Do not approve from model memory.

## Draft Evidence

New `entries/<id>.json` files carry proof candidates outside the packed lorebook:

```json
{
  "content": "First factual sentence. Second related sentence.",
  "source_page_ids": [123],
  "source_evidence": [
    {
      "page_id": 123,
      "source_quote": "An exact article-body passage supporting both statements.",
      "supports": [0, 1]
    }
  ]
}
```

Every content sentence must be covered. Every declared source page must contribute evidence. Exact quote presence is deterministic; semantic entailment remains the reviewer's job.

## Review V2

`review-init` owns IDs and hashes. The reviewer changes only statuses, issues, and optional risk tests:

```json
{
  "version": 2,
  "selection": {
    "artifact_hash": "generated",
    "status": "pass",
    "issues": []
  },
  "entries": [
    {
      "id": "magic-system",
      "artifact_hash": "generated",
      "status": "pass",
      "issues": [],
      "risk_tests": [
        {
          "text": "A realistic confusable phrase",
          "expected": false,
          "reason": "Explains the specific alias collision being guarded against."
        }
      ]
    }
  ]
}
```

Issue categories are `coverage`, `source_fidelity`, `spoiler_safety`, `trigger_precision`, `continuity`, `atomicity`, and `relationship_fidelity`. Each issue contains `category`, `message`, and one or more artifact `targets`. A passing record cannot contain issues.
