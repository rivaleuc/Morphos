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

## Live Deployment

- **Network:** GenLayer Bradbury
- **Contract:** [`0x02Cb8B1daD4B903457184aF43EC390D3999d0C26`](https://explorer-bradbury.genlayer.com/address/0x02Cb8B1daD4B903457184aF43EC390D3999d0C26)

Verified end to end: an intent ("ETH gas is cheap enough for retail today") was created, then `reevaluate` ran a real web fetch plus LLM consensus across validators. The endpoint was unreachable, so consensus dropped confidence 100 → 10, set drift to 95, and moved the node to `deprecated` with reasoning. The verdict is stored in the node history.

## Calling it on Bradbury (CLI)

The Bradbury RPC exposes no contract schema, so `genlayer-js` cannot see Python default arguments and the CLI coerces numeric-looking strings to int. The contract is written defensively around this:

```bash
# Create. Always pass all three args. Use " " for "no dependencies".
genlayer write <addr> create_intent \
  --args "ETH gas is cheap enough for retail today" \
         "https://api.etherscan.io/api?module=gastracker&action=gasoracle" " "

# Re-evaluate node 0 (runs the web fetch + LLM consensus).
genlayer write <addr> reevaluate --args "0"

# Free reads.
genlayer call <addr> read_intent  --args "0"
genlayer call <addr> read_history --args "0"
genlayer call <addr> graph_stats
```

To depend on existing nodes, pass `depends_on` as a comma-separated id string, e.g. `"0,1"`.
