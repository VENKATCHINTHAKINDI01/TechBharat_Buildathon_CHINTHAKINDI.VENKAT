"""The agents.

Seven agents run before human review, and one after it. Each declares the
tools it may use; none of them can reach an external system except
through the registry, and the four side-effecting tools additionally
require a gate decision plus a human approval that only
``app/services/approval.py`` can produce.

    IngestionAgent        parse the file into utterances
    NormalizationAgent    segment ids + optional code-switch translation
    ExtractionAgent       LLM extraction with deterministic fallback
    ValidationAgent       grade citations, drop unsupported evidence
    ResolutionAgent       owner + date + composite confidence
    GateAgent             the six deterministic rules, per item
    RecordAgent           structured meeting record + cross-meeting recall
    -------- human review interrupt --------
    ActionAgent           fires approved side effects (see services/approval.py)
"""
from __future__ import annotations

from app.agents.base import AgentContext, PipelineState
from app.domain.models import AuditStage
from app.services.extraction.base import EvidenceReport, ExtractionError


class IngestionAgent:
    name = "ingestion"
    description = "Parses the uploaded transcript into raw utterances."
    tools = ("parse_transcript",)

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        # Audio and video arrive already transcribed: speech-to-text runs
        # in the route, before the graph, because it is slow and needs to
        # stream progress. The agent records where the utterances came
        # from rather than silently accepting them.
        if state.utterances:
            await ctx.audit.record(
                AuditStage.ingestion,
                {
                    "outcome": "transcribed",
                    "filename": state.filename,
                    "utterances": len(state.utterances),
                    "source": state.media_source or "media",
                },
            )
            state._last_summary = f"{len(state.utterances)} utterances from audio"
            return state

        state.utterances = await ctx.tools.invoke(
            "parse_transcript", filename=state.filename, content=state.content
        )
        await ctx.audit.record(
            AuditStage.ingestion,
            {"outcome": "parsed", "filename": state.filename, "utterances": len(state.utterances)},
        )
        state._last_summary = f"parsed {len(state.utterances)} utterances"
        return state


class NormalizationAgent:
    name = "normalization"
    description = (
        "Assigns stable segment ids and, for code-switched speech, adds an English "
        "rendering alongside the original text (never replacing it)."
    )
    tools = ("normalize_segments", "translate_segments")

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        segments = await ctx.tools.invoke(
            "normalize_segments", utterances=state.utterances, meeting_id=state.meeting_id
        )

        if ctx.normalizer is not None and getattr(ctx.normalizer, "name", "none") != "none":
            segments = await ctx.tools.invoke(
                "translate_segments", segments=segments, normalizer=ctx.normalizer
            )
            state.normalizer_used = ctx.normalizer.name

        state.segments = segments
        translated = sum(1 for s in segments if s.normalized_text)
        await ctx.audit.record(
            AuditStage.normalization,
            {
                "segments": len(segments),
                "speakers": sorted({s.speaker for s in segments}),
                "normalizer": state.normalizer_used,
                "segments_translated": translated,
            },
        )
        state._last_summary = f"{len(segments)} segments, {translated} translated"
        return state


class ExtractionAgent:
    name = "extraction"
    description = "Extracts and classifies commitment candidates. Falls back to the deterministic extractor if the LLM fails."
    tools = ("extract_candidates",)

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        state.extractor_used = getattr(ctx.extractor, "name", "unknown")
        try:
            state.candidates = await ctx.tools.invoke(
                "extract_candidates",
                extractor=ctx.extractor,
                segments=state.segments,
                meeting_id=state.meeting_id,
            )
        except ExtractionError as exc:
            state.fallback_reason = str(exc)
            state.warnings.append(f"Primary extractor failed, used fallback: {exc}")
            state.extractor_used = getattr(ctx.fallback_extractor, "name", "reference")
            state.candidates = await ctx.tools.invoke(
                "extract_candidates",
                extractor=ctx.fallback_extractor,
                segments=state.segments,
                meeting_id=state.meeting_id,
            )

        await ctx.audit.record(
            AuditStage.extraction,
            {
                "extractor": state.extractor_used,
                "fallback_reason": state.fallback_reason,
                "candidates": len(state.candidates),
            },
        )
        state._last_summary = f"{len(state.candidates)} candidates via {state.extractor_used}"
        return state


class ValidationAgent:
    name = "validation"
    description = "Deletes evidence quotes that are not verbatim substrings of the segment they cite. An extractor does not grade its own citations."
    tools = ("grade_evidence",)

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        before = len(state.candidates)
        # The report is an out-parameter: the tool returns the surviving
        # items, and fills this in with what it removed and why. Going
        # through the registry (rather than calling the function directly)
        # is what keeps the tool-call trail complete.
        report = EvidenceReport()
        state.candidates = await ctx.tools.invoke(
            "grade_evidence",
            items=state.candidates,
            segments=state.segments,
            report=report,
        )
        dropped = before - len(state.candidates)
        if dropped:
            state.warnings.append(
                f"{dropped} candidate(s) dropped because the extractor quoted words that "
                f"are not in the transcript"
                + (f" — e.g. {report.examples[0]}" if report.examples else "")
            )

        await ctx.audit.record(
            AuditStage.validation,
            {
                "dropped_for_unsupported_evidence": dropped,
                "evidence_dropped_items": len(report.dropped_items),
                "evidence_quotes_dropped": report.quotes_dropped,
                "evidence_quotes_repaired": report.quotes_repaired,
                "warnings": state.warnings,
                "classifications": {
                    c: sum(1 for v in state.candidates if v.classification.value == c)
                    for c in sorted({v.classification.value for v in state.candidates})
                },
            },
        )
        state._last_summary = f"{dropped} dropped for bad citations"
        return state


class ResolutionAgent:
    name = "resolution"
    description = "Resolves each candidate's owner and due date deterministically, then blends resolution quality into a composite confidence score."
    tools = ("resolve_items",)

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        state.resolved = await ctx.tools.invoke(
            "resolve_items",
            items=state.candidates,
            participants=state.participants,
            meeting_date=state.meeting_date,
        )
        await ctx.audit.record(
            AuditStage.resolution,
            {
                "owners_resolved": sum(1 for r in state.resolved if r.owner_participant_id),
                "owners_unresolved": sum(1 for r in state.resolved if not r.owner_participant_id),
                "dates_resolved": sum(1 for r in state.resolved if r.due_date),
                "dates_unresolved": sum(1 for r in state.resolved if not r.due_date),
            },
        )
        resolved_owners = sum(1 for r in state.resolved if r.owner_participant_id)
        state._last_summary = f"{resolved_owners}/{len(state.resolved)} owners resolved"
        return state


class GateAgent:
    name = "gate"
    description = "Applies the six deterministic safety rules to every resolved item. This agent decides nothing itself; it calls the gate and records the verdict."
    tools = ("safety_gate",)

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        for item in state.resolved:
            decision = await ctx.tools.invoke(
                "safety_gate",
                item=item,
                confidence_threshold=ctx.settings.confidence_threshold,
            )
            state.gate_decisions[item.candidate_id] = decision
            await ctx.audit.record(
                AuditStage.gate,
                {"eligible": decision.eligible, "reasons": decision.reasons, "context": "pipeline"},
                candidate_id=item.candidate_id,
            )
        state._last_summary = f"{state.eligible_count}/{len(state.resolved)} eligible"
        return state


class RecordAgent:
    name = "record"
    description = "Builds the structured meeting record and recalls related commitments from previous meetings."
    tools = ("synthesize_record", "recall_memory")

    async def run(self, state: PipelineState, ctx: AgentContext) -> PipelineState:
        state.record = await ctx.tools.invoke(
            "synthesize_record", meeting_id=state.meeting_id, items=state.resolved
        )

        # Cross-meeting recall: what did this team already commit to that
        # looks like what they just discussed? Read-only and best-effort --
        # a memory backend outage must not fail an upload.
        if ctx.memory_store is not None:
            try:
                for item in state.resolved:
                    hits = await ctx.tools.invoke(
                        "recall_memory",
                        store=ctx.memory_store,
                        query=item.raw_text,
                        limit=3,
                        exclude_meeting_id=state.meeting_id,
                    )
                    for record, score in hits:
                        if score >= ctx.settings.memory_similarity_threshold:
                            state.carried_forward.append(
                                {
                                    "candidate_id": item.candidate_id,
                                    "memory": record.model_dump(mode="json"),
                                    "similarity": round(score, 3),
                                }
                            )
            except Exception as exc:  # noqa: BLE001 - recall is an enrichment
                state.warnings.append(f"Cross-meeting recall unavailable: {exc}")

        await ctx.repository.save_items(state.resolved)
        await ctx.repository.save_meeting_record(state.record)
        # Keep the transcript so the report can be rebuilt on demand.
        await ctx.repository.save_segments(
            state.meeting_id, [s.model_dump(mode="json") for s in state.segments]
        )
        state._last_summary = (
            f"record saved, {len(state.carried_forward)} carried-forward match(es)"
        )
        return state


PIPELINE_AGENTS = (
    IngestionAgent(),
    NormalizationAgent(),
    ExtractionAgent(),
    ValidationAgent(),
    ResolutionAgent(),
    GateAgent(),
    RecordAgent(),
)
