# MORPHOS

A living intent graph on [GenLayer](https://genlayer.com). Intents are natural-language commitments stored on chain whose validity is not fixed at creation time: anyone can trigger a re-evaluation, validators running different LLMs judge whether the intent still holds under current real-world context, and consensus updates its status, confidence, and semantic drift.

Most contracts execute agreements. MORPHOS re-asks what an agreement still means.

## What it actually does

- `create_intent(text, context_url, depends_on)` stores an intent node, optionally pointing at a live web source and at other intents it depends on.
- `reevaluate(intent_id)` fetches the context URL, asks an LLM whether the intent is still meaningful today (not whether it was valid when written), and estimates semantic drift since the last evaluation. Validators reach consensus on the verdict.
- Deprecated dependencies propagate: an intent resting on a dead one gets downgraded to `unstable` deterministically, before any LLM runs.
- Each node keeps a short history of past consensus verdicts, so meaning trajectories are auditable.

## Why GenLayer

A deterministic VM cannot do this. Judging whether "deliver the audit before the merge window closes" still means anything requires fetching live context and applying qualitative judgment under consensus. On EVM that needs a trusted oracle; on GenLayer it is a native write.

## Honest limits

- Re-evaluation is one transaction per call, triggered externally. There is no self-running loop; if you want continuous morphogenesis, point a cron at `reevaluate`.
- Drift is an LLM-judged 0-100 scalar, not an embedding distance.
- Validators pick their own models; the contract only defines the prompt and the validation predicate.

## Deployment

- **Status:** deployed and tested on GenLayer Studio (`0x38770f5754904E99244fEE4fFF45aF905b0C62Df`)
- **Bradbury:** not yet deployed
