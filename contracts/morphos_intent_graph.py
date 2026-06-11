# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# MORPHOS: a living intent graph on GenLayer.
#
# Each node is a natural-language intent (an agreement, obligation, or claim)
# whose validity is NOT fixed at creation time. Anyone can trigger a
# re-evaluation: the leader optionally fetches fresh web context, an LLM
# judges whether the intent still holds under current conditions, and
# validators reach consensus on the verdict. Deprecated intents propagate
# instability to dependent intents deterministically.
#
# What this deliberately does NOT do (because the platform doesn't support it):
# - no self-triggering recursive loops: every re-evaluation is one transaction,
#   triggered externally (user, cron, bridge)
# - no contract-side model routing: validators choose their own models,
#   the contract only defines the prompt and the validation predicate
# - no raw embedding vectors in storage: drift is an LLM-judged 0-100 scalar

import json
import dataclasses
from genlayer import *

HISTORY_LIMIT = 5
DRIFT_UNSTABLE_THRESHOLD = 70

STATUS_ACTIVE = "active"
STATUS_UNSTABLE = "unstable"
STATUS_DEPRECATED = "deprecated"


@allow_storage
@dataclasses.dataclass
class IntentNode:
    author: str
    text: str
    context_url: str
    depends_on: str       # comma-separated intent ids, "" if none
    status: str           # active | unstable | deprecated
    confidence: u256      # 0-100, last consensus confidence that intent holds
    drift: u256           # 0-100, semantic drift vs previous evaluation
    evaluations: u256     # how many consensus re-evaluations ran
    reasoning: str        # last consensus reasoning
    history: str          # JSON array of last HISTORY_LIMIT snapshots


def _addr_key(addr: Address) -> str:
    return str(addr)


def _parse_deps(depends_on: str) -> list:
    return [d.strip() for d in depends_on.split(",") if d.strip()]


class MorphosIntentGraph(gl.Contract):
    owner: str
    nodes: TreeMap[str, IntentNode]
    node_count: u256
    total_evaluations: u256

    def __init__(self):
        self.owner = _addr_key(gl.message.sender_address)
        self.node_count = u256(0)
        self.total_evaluations = u256(0)

    # ------------------------------------------------------------------
    # Graph mutation (deterministic)
    # ------------------------------------------------------------------

    @gl.public.write
    def create_intent(self, text: str, context_url: str, depends_on: str) -> str:
        text = text.strip()
        if not text:
            raise Exception("intent text required")
        if len(text) > 2000:
            raise Exception("intent text too long (max 2000 chars)")

        for dep_id in _parse_deps(depends_on):
            if dep_id not in self.nodes:
                raise Exception(f"unknown dependency: {dep_id}")

        intent_id = str(int(self.node_count))
        self.nodes[intent_id] = IntentNode(
            author=_addr_key(gl.message.sender_address),
            text=text,
            context_url=context_url.strip(),
            depends_on=",".join(_parse_deps(depends_on)),
            status=STATUS_ACTIVE,
            confidence=u256(100),
            drift=u256(0),
            evaluations=u256(0),
            reasoning="not yet evaluated",
            history="[]",
        )
        self.node_count += u256(1)
        return intent_id

    @gl.public.write
    def deprecate_intent(self, intent_id: str) -> None:
        if intent_id not in self.nodes:
            raise Exception("unknown intent")
        node = self.nodes[intent_id]
        if node.author != _addr_key(gl.message.sender_address):
            raise Exception("only the author can deprecate an intent")
        node.status = STATUS_DEPRECATED
        node.confidence = u256(0)
        node.reasoning = "deprecated by author"
        self.nodes[intent_id] = node

    # ------------------------------------------------------------------
    # Semantic re-evaluation (non-deterministic, consensus-gated)
    # ------------------------------------------------------------------

    @gl.public.write
    def reevaluate(self, intent_id: str) -> None:
        if intent_id not in self.nodes:
            raise Exception("unknown intent")
        node = self.nodes[intent_id]
        if node.status == STATUS_DEPRECATED:
            raise Exception("intent is deprecated, cannot re-evaluate")

        # Deterministic dependency propagation, before any LLM work:
        # an intent resting on dead dependencies cannot stay fully active.
        dep_summaries = []
        has_dead_dependency = False
        for dep_id in _parse_deps(node.depends_on):
            dep = self.nodes[dep_id]
            if dep.status == STATUS_DEPRECATED:
                has_dead_dependency = True
            dep_summaries.append(
                f"[{dep_id}] status={dep.status} confidence={int(dep.confidence)}: {dep.text[:200]}"
            )

        verdict = self._evaluate(node, dep_summaries)

        new_status = verdict["status"]
        if has_dead_dependency and new_status == STATUS_ACTIVE:
            new_status = STATUS_UNSTABLE
            verdict["reasoning"] += " (downgraded: a dependency is deprecated)"
        if verdict["drift"] > DRIFT_UNSTABLE_THRESHOLD and new_status == STATUS_ACTIVE:
            new_status = STATUS_UNSTABLE
            verdict["reasoning"] += " (downgraded: semantic drift above threshold)"

        snapshots = json.loads(node.history)
        snapshots.append({
            "status": new_status,
            "confidence": verdict["confidence"],
            "drift": verdict["drift"],
            "reasoning": verdict["reasoning"],
        })
        snapshots = snapshots[-HISTORY_LIMIT:]

        node.status = new_status
        node.confidence = u256(verdict["confidence"])
        node.drift = u256(verdict["drift"])
        node.reasoning = verdict["reasoning"]
        node.evaluations += u256(1)
        node.history = json.dumps(snapshots)
        self.nodes[intent_id] = node
        self.total_evaluations += u256(1)

    def _evaluate(self, node: IntentNode, dep_summaries: list) -> dict:
        intent_text = node.text
        context_url = node.context_url
        prev_reasoning = node.reasoning
        prev_confidence = int(node.confidence)
        deps_block = "\n".join(dep_summaries) if dep_summaries else "(no dependencies)"

        def leader_fn() -> str:
            context_block = "(no external context configured)"
            if context_url:
                try:
                    raw_ctx = gl.nondet.web.request(context_url, method="GET")
                    context_block = str(raw_ctx)[:4000]
                except Exception:
                    context_block = "(context fetch failed; judge from intent text alone)"

            prompt = f"""You are a semantic validity judge for a decentralized intent graph.

INTENT UNDER EVALUATION:
{intent_text}

DEPENDENCIES (intents this one relies on):
{deps_block}

CURRENT EXTERNAL CONTEXT:
{context_block}

PREVIOUS CONSENSUS EVALUATION:
confidence={prev_confidence}, reasoning: {prev_reasoning}

Judge whether this intent is still meaningful and valid TODAY, under the
current context and the state of its dependencies. Do not judge whether it
was valid when written. Then estimate semantic drift: how much the practical
meaning of this intent has changed since the previous evaluation (0 = same
meaning, 100 = the words now mean something entirely different).

Reply ONLY valid JSON of the form:
{{"status": "active" | "unstable" | "deprecated", "confidence": <int 0-100>, "drift": <int 0-100>, "reasoning": "<two short sentences>"}}

No markdown, no code fences, no extra text.
"""
            raw = gl.nondet.exec_prompt(prompt)
            text = raw if isinstance(raw, str) else json.dumps(raw)
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            return json.dumps(parsed)

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                parsed = json.loads(leader_result.calldata)
                if parsed.get("status") not in (STATUS_ACTIVE, STATUS_UNSTABLE, STATUS_DEPRECATED):
                    return False
                c = parsed.get("confidence")
                d = parsed.get("drift")
                if not isinstance(c, int) or c < 0 or c > 100:
                    return False
                if not isinstance(d, int) or d < 0 or d > 100:
                    return False
                return isinstance(parsed.get("reasoning"), str)
            except Exception:
                return False

        result_str = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        return json.loads(result_str)

    # ------------------------------------------------------------------
    # Views (free reads)
    # ------------------------------------------------------------------

    @gl.public.view
    def read_intent(self, intent_id: str) -> dict:
        if intent_id not in self.nodes:
            return {"exists": False}
        node = self.nodes[intent_id]
        return {
            "exists": True,
            "id": intent_id,
            "author": node.author,
            "text": node.text,
            "context_url": node.context_url,
            "depends_on": _parse_deps(node.depends_on),
            "status": node.status,
            "confidence": int(node.confidence),
            "drift": int(node.drift),
            "evaluations": int(node.evaluations),
            "reasoning": node.reasoning,
        }

    @gl.public.view
    def read_history(self, intent_id: str) -> list:
        if intent_id not in self.nodes:
            return []
        return json.loads(self.nodes[intent_id].history)

    @gl.public.view
    def graph_stats(self) -> dict:
        counts = {STATUS_ACTIVE: 0, STATUS_UNSTABLE: 0, STATUS_DEPRECATED: 0}
        total = int(self.node_count)
        for i in range(total):
            node = self.nodes[str(i)]
            counts[node.status] += 1
        return {
            "nodes": total,
            "active": counts[STATUS_ACTIVE],
            "unstable": counts[STATUS_UNSTABLE],
            "deprecated": counts[STATUS_DEPRECATED],
            "total_evaluations": int(self.total_evaluations),
        }
