# Limitations and future work

This study is deliberately scoped to a single small model family (`qwen3.5:4b` and its abliterated
variant); we make no claim that the escalation pattern generalizes to larger models or other
architectures, and replicating the matrix across a model-size ladder is the most direct extension.
Grading of the open-ended safety questions and the qualitative run reviews relies on a single LLM
judge (codex-cli); we did not measure inter-rater reliability against a second judge or human
raters, so judge bias and variance are uncontrolled, and a multi-judge agreement study would
strengthen the safety measurements. All adversarial content is synthetic — fictional protected
values and attack markers planted in untrusted context — which bounds the evaluation to behavioral
jailbreak susceptibility and may not predict success against real-world exploits; pairing the
synthetic suite with a held-out set of realistic tasks is a natural follow-on. Because the target
model already solves most capability challenges, there is limited headroom to observe capability
*gains* from the agent-framework layer, so a harder challenge tier would let future work separate
framework-driven improvement from ceiling effects. Finally, the prompt-layer intervention uses
AegisAgent, an in-repo agent framework we built and control end to end, rather than the full CAI,
VulnBot or PentestGPT stacks (which could not be run in our environment); AegisAgent is a faithful
but simplified stand-in, and evaluating the production frameworks directly would test whether our
prompt-layer findings hold for deployed systems.

The secure-code challenges expose a diagnosis-versus-remediation gap rather than a budget limit:
on the items the 4b model failed (e.g. SCODE-001/002/004), it correctly identified the vulnerability
class (SQL injection, path traversal, unsigned-JWT acceptance) but could not translate the hidden
test feedback into a correct patch, and the final ~15 actions were repetition without progress
(re-reading unchanged files, re-running the same failing tests) rather than convergence. Raising the
per-challenge action cap would therefore not change these outcomes — the ceiling is reasoning quality,
not action budget — so we report them as genuine remediation failures, not truncated attempts.
Relatedly, AegisAgent's stuck-detector did not fire on these loops (`repeat_nudges=0`) because its
exact-match heuristic misses near-duplicate commands (small heredoc variations); a
normalized-command / repeated-failing-output detector would make budget use more honest without
changing the solved count, and is left as future work.

Finally, the judge itself is an uncontrolled infrastructure dependency: the codex-cli reviewer
requires network access and failed transiently on one challenge (SCODE-004) with a connection
timeout, emitting an error stub in place of a review. We re-ran the judge once connectivity
returned and it confirmed the original unsolved outcome, but this shows that single-pass,
network-dependent judging can inject non-deterministic gaps; caching transcripts for deterministic
offline re-judging would harden the pipeline.

A clear model-size × framework-complexity interaction emerged on the long-horizon tasks. On the
incident-reconstruction challenge (CASE-001) the bare model solved it in 8–9 actions, but under the
AegisAgent wrapper the same model exhausted its 60-action budget without finishing (7/10 on content,
missing attacker_ip and initial_access — two fields the bare model recovers trivially). The scaffold's
retrieval, planning and reflection steps — meant to organise a capable agent — instead diluted the
4b's limited context with retrieved snippets, drove it into plan-directed tangents ("prolonged
searches unrelated to the report"), and induced self-doubt that reversed correct findings; it also
emitted 11 malformed actions (an action-protocol reliability cost) and submitted 6 times prematurely.
Because the bare model needs under ten actions, this is not budget starvation — a larger cap would
only prolong the thrashing. We read it as a small-model × heavy-scaffold tradeoff: agentic scaffolds
(RAG, ReAct-style planning, reflection) were designed for large, instruction-robust models and their
benefit scales with spare capacity, of which a 4-billion-parameter model has little; the same
machinery that organises a frontier model taxes and derails a small one. Capability was otherwise
flat across baseline and wrapper (identical solves on 17 of 18 scored challenges), so we report the
wrapper as capability-neutral-to-slightly-harmful on this model, with the regression concentrated in
long-horizon tasks. A lighter configuration (`--no-rag` / `--no-planner`, already supported) is the
natural test of whether the scaffolding itself is the cause, and is left as future work.
