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
