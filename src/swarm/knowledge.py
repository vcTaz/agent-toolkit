"""Deterministic knowledge services: projection, consolidation, conflicts, invalidation.

No model decides anything here. Duplicate detection is exact, conflict detection is
restricted to contradictions the host can actually establish, and every original finding
identity stays inspectable.
"""
import json
from dataclasses import dataclass, replace
from .context import digest
from .domain import (AgentGroup, Assignment, Conflict, ConflictKind, ConflictStatus, Finding,
                     FindingStatus, GroupStatus, Message, SwarmState, Task, TaskStatus, invalidate,
                     now, transition)
from .events import EventDraft, EventType
from .serialization import encode

KNOWN = (FindingStatus.PROPOSED, FindingStatus.CRITIQUED, FindingStatus.VALIDATED)
CANDIDATE = (FindingStatus.PROPOSED, FindingStatus.CRITIQUED)
STATUS_RANK = {FindingStatus.VALIDATED: 3, FindingStatus.CRITIQUED: 2, FindingStatus.PROPOSED: 1}
MAX_FAILED_APPROACHES = 8


def normalize_claim(claim: str) -> str:
    """Whitespace and case only. Similar prose is not a duplicate."""
    return ' '.join(str(claim).lower().split())


def evidence_signature(finding: Finding) -> str:
    """Content of the evidence, not its per-execution identifiers."""
    return digest([[item.kind, item.tool_name, item.arguments_json, item.value]
                   for item in finding.evidence])


def duplicate_key(finding: Finding):
    return normalize_claim(finding.claim), evidence_signature(finding)


@dataclass(frozen=True)
class DuplicateGroup:
    claim: str
    signature: str
    canonical_id: str
    member_ids: tuple[str, ...]

    @property
    def duplicate_ids(self):
        return tuple(i for i in self.member_ids if i != self.canonical_id)


@dataclass(frozen=True)
class ConsolidationReport:
    groups: tuple[DuplicateGroup, ...]
    canonical_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]


def findings_of(snapshot, run_id=None):
    return tuple(sorted((r for r in snapshot.values() if isinstance(r, Finding)
                         and (run_id is None or r.run_id == run_id)), key=lambda f: f.id))


def duplicate_groups(snapshot, run_id=None) -> tuple[DuplicateGroup, ...]:
    """Exact normalized-claim plus evidence-signature grouping, insertion-order independent."""
    buckets = {}
    for finding in findings_of(snapshot, run_id):
        if finding.status in KNOWN:
            buckets.setdefault(duplicate_key(finding), []).append(finding)
    groups = []
    for (claim, signature), members in sorted(buckets.items()):
        ordered = sorted(members, key=lambda f: (-STATUS_RANK[f.status], f.id))
        groups.append(DuplicateGroup(claim, signature, ordered[0].id,
                                     tuple(sorted(f.id for f in members))))
    return tuple(groups)


def consolidate(snapshot, run_id=None) -> ConsolidationReport:
    groups = duplicate_groups(snapshot, run_id)
    conflicts = tuple(sorted(c.id for c in snapshot.values()
                             if isinstance(c, Conflict) and c.status == ConflictStatus.OPEN
                             and (run_id is None or c.run_id == run_id)))
    return ConsolidationReport(groups, tuple(sorted(g.canonical_id for g in groups)),
                               tuple(sorted(i for g in groups for i in g.duplicate_ids)), conflicts)


# --- conflicts ------------------------------------------------------------------

@dataclass(frozen=True)
class ConflictSpec:
    kind: ConflictKind
    finding_ids: tuple[str, ...]
    reason: str

    @property
    def signature(self):
        return digest({'kind': str(self.kind), 'findings': list(self.finding_ids)})


def detect_conflicts(snapshot, structured_value, run_id=None) -> tuple[ConflictSpec, ...]:
    """Only contradictions the system can establish: incompatible structured values for the
    same known property, and contradictions a host fixture declared explicitly."""
    validated = [f for f in findings_of(snapshot, run_id) if f.status == FindingStatus.VALIDATED]
    known = {f.id for f in validated}
    specs = {}
    def open_conflict(spec):
        specs.setdefault(spec.signature, spec)
    properties = {}
    for finding in validated:
        pair = structured_value(finding)
        if pair is not None:
            properties.setdefault(pair[0], []).append((finding.id, pair[1]))
    for name, entries in sorted(properties.items()):
        if len({value for _, value in entries}) > 1:
            open_conflict(ConflictSpec(ConflictKind.CONTRADICTORY_VALUE,
                                       tuple(sorted(i for i, _ in entries)),
                                       f'incompatible values for {name}: '
                                       + ', '.join(f'{i}={v}' for i, v in sorted(entries))))
    for finding in validated:
        if 'contradiction' not in finding.tags:
            continue
        for other in sorted(set(finding.related_finding_ids) & known):
            open_conflict(ConflictSpec(ConflictKind.DECLARED_CONTRADICTION,
                                       tuple(sorted((finding.id, other))),
                                       f'{finding.id} declares a contradiction with {other}'))
    return tuple(specs[key] for key in sorted(specs))


def maintain_conflicts(snapshot, run_id, identity, structured_value):
    """Open conflicts the fixture or structured values establish; resolve the ones whose
    participants are no longer validated. Never mutates a finding's claim."""
    records, events, working = [], [], dict(snapshot)
    # A resolved conflict stays history; the same contradiction reappearing opens a fresh record.
    standing = {c.signature for c in snapshot.values() if isinstance(c, Conflict)
                and c.run_id == run_id and c.status == ConflictStatus.OPEN}
    for spec in detect_conflicts(snapshot, structured_value, run_id):
        if spec.signature in standing:
            continue
        participants = [snapshot[i] for i in spec.finding_ids]
        conflict = Conflict(id=identity('conflict'), run_id=run_id, finding_ids=spec.finding_ids,
                            finding_revisions=tuple(f.revision for f in participants),
                            kind=spec.kind, signature=spec.signature, reason=spec.reason,
                            criterion_ids=tuple(sorted({c for f in participants for c in f.criterion_ids})))
        records.append(conflict)
        working[conflict.id] = conflict
        events.append(EventDraft(type=EventType.CONFLICT_OPENED, record_id=conflict.id,
                                 record_revision=conflict.revision,
                                 detail_json=json.dumps({'finding_ids': list(spec.finding_ids),
                                                         'finding_revisions': list(conflict.finding_revisions),
                                                         'kind': str(spec.kind), 'reason': spec.reason})))
    for conflict in sorted((c for c in snapshot.values() if isinstance(c, Conflict)
                            and c.run_id == run_id and c.status == ConflictStatus.OPEN), key=lambda c: c.id):
        stale = [i for i in conflict.finding_ids
                 if not isinstance(snapshot.get(i), Finding)
                 or snapshot[i].status != FindingStatus.VALIDATED]
        if not stale:
            continue
        resolved = replace(transition(conflict, ConflictStatus.RESOLVED),
                           resolution='PARTICIPANT_NOT_VALIDATED: ' + ', '.join(sorted(stale)),
                           resolved_at=now())
        records.append(resolved)
        working[resolved.id] = resolved
        events.append(EventDraft(type=EventType.CONFLICT_RESOLVED, record_id=resolved.id,
                                 record_revision=resolved.revision,
                                 detail_json=json.dumps({'resolution': resolved.resolution,
                                                         'finding_ids': list(resolved.finding_ids)})))
    return records, events, working


# --- coverage -------------------------------------------------------------------

@dataclass(frozen=True)
class Coverage:
    criterion_id: str
    supporting_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]

    @property
    def clean(self):
        """Supported by validated knowledge and untouched by an unresolved conflict."""
        return bool(self.supporting_ids) and not self.conflict_ids


def criterion_coverage(snapshot, run_id):
    """Per-criterion readiness. An open conflict over a supporting finding is not clean
    coverage, however individually validated each side is."""
    run = snapshot[run_id]
    validated = [f for f in findings_of(snapshot, run_id) if f.status == FindingStatus.VALIDATED]
    conflicts = [c for c in snapshot.values() if isinstance(c, Conflict) and c.run_id == run_id
                 and c.status == ConflictStatus.OPEN]
    coverage = {}
    for criterion in run.acceptance_criteria:
        supporting = tuple(sorted(f.id for f in validated if criterion.id in f.criterion_ids))
        touched = tuple(sorted(c.id for c in conflicts if set(c.finding_ids) & set(supporting)))
        coverage[criterion.id] = Coverage(criterion.id, supporting, touched)
    return coverage


# --- projection -----------------------------------------------------------------

def failed_approaches(snapshot, run_id):
    rejected = [f'{f.id}: {f.claim}' for f in findings_of(snapshot, run_id)
                if f.status in (FindingStatus.REJECTED, FindingStatus.INVALIDATED)]
    failed = [f'{t.id}: {t.outcome}' for t in sorted(
        (r for r in snapshot.values() if isinstance(r, Task) and r.run_id == run_id
         and r.status in (TaskStatus.FAILED, TaskStatus.CANCELLED) and r.outcome), key=lambda t: t.id)]
    return tuple((rejected + failed)[:MAX_FAILED_APPROACHES])


def project(snapshot, state: SwarmState) -> SwarmState | None:
    """Recompute the compact projection; return None when nothing changed.

    ``validated_findings`` carries canonical representatives only, so a duplicated claim is
    offered once while every original record stays queryable.
    """
    run_id = state.run_id
    canonical = {g.canonical_id for g in duplicate_groups(snapshot, run_id)}
    findings = findings_of(snapshot, run_id)
    updated = replace(state,
        validated_findings=tuple(f.id for f in findings
                                 if f.status == FindingStatus.VALIDATED and f.id in canonical),
        candidate_findings=tuple(f.id for f in findings if f.status in CANDIDATE),
        invalidated_findings=tuple(f.id for f in findings if f.status == FindingStatus.INVALIDATED),
        rejected_findings=tuple(f.id for f in findings if f.status == FindingStatus.REJECTED),
        open_conflict_ids=tuple(sorted(c.id for c in snapshot.values() if isinstance(c, Conflict)
                                       and c.run_id == run_id and c.status == ConflictStatus.OPEN)),
        active_task_ids=tuple(sorted(t.id for t in snapshot.values() if isinstance(t, Task)
                                     and t.run_id == run_id
                                     and t.status in (TaskStatus.READY, TaskStatus.RUNNING))),
        active_group_ids=tuple(sorted(g.id for g in snapshot.values() if isinstance(g, AgentGroup)
                                      and g.run_id == run_id and g.status == GroupStatus.ACTIVE)),
        failed_approaches=failed_approaches(snapshot, run_id),
        revision=state.revision + 1)
    return updated if encode(replace(updated, revision=state.revision)) != encode(state) else None


# --- invalidation ---------------------------------------------------------------

def consumers(snapshot, finding_id):
    """Who received or relied on this finding. Stage 6 turns this into retraction routing."""
    delivered = sorted({recipient for m in snapshot.values() if isinstance(m, Message)
                        and finding_id in m.reference_ids for recipient in m.delivered_to})
    pinned = sorted({(a.id, a.agent_id, a.task_id) for a in snapshot.values()
                     if isinstance(a, Assignment) and finding_id in a.input_finding_ids})
    return {'delivered_to': delivered,
            'consumed_by': [{'assignment_id': a, 'agent_id': g, 'task_id': t} for a, g, t in pinned]}


def invalidate_closure(snapshot, run_id, finding_id, reason):
    """Invalidate a validated finding and, transitively, every validated dependent.

    Unvalidated dependents are not silently rejected: they simply cannot be promoted while
    a dependency is invalid, and they are named in the removal event so later review sees it.
    """
    findings = findings_of(snapshot, run_id)
    if finding_id not in {f.id for f in findings}:
        raise ValueError('UNKNOWN_FINDING')
    changed = {new.id: new for old, new in zip(findings, invalidate(findings, finding_id)) if new is not old}
    if not changed:
        return [], []
    affected = set(changed)
    pending, unvalidated = sorted(affected), []
    while pending:
        current = pending.pop(0)
        for finding in findings:
            if current in finding.dependency_finding_ids and finding.id not in affected:
                affected.add(finding.id)
                pending.append(finding.id)
                if finding.status in CANDIDATE:
                    unvalidated.append(finding.id)
    events = [EventDraft(type=EventType.FINDING_INVALIDATED, record_id=new.id,
                         record_revision=new.revision,
                         detail_json=json.dumps({'root_finding_id': finding_id, 'reason': reason,
                                                 'finding_id': new.id, 'revision': new.revision,
                                                 'previous_revision': new.revision - 1,
                                                 **consumers(snapshot, new.id)}))
              for new in sorted(changed.values(), key=lambda f: f.id)]
    events.append(EventDraft(type=EventType.KNOWLEDGE_REMOVED,
                             detail_json=json.dumps({'root_finding_id': finding_id, 'reason': reason,
                                                     'removed': sorted(changed),
                                                     'unvalidated_dependents': sorted(unvalidated)})))
    return sorted(changed.values(), key=lambda f: f.id), events
