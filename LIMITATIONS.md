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
