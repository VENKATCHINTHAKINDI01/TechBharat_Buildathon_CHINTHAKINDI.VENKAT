"""CommitGuard: evidence-backed meeting commitment agent.

This package is deliberately isolated from the rest of ``app`` (the
Nexvi.Meets meeting-summarization product). See ``docs/architecture.md``
at the repo root for the module boundary rules, in particular that the
LLM-facing code here must never import or call ``tools/github_issues_tool``
directly -- only the deterministic safety gate and the human review flow
may authorize that call.
"""
