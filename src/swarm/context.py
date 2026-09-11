"""Deterministic, bounded, immutable context construction from deliberate domain selections."""
import hashlib
import json
from dataclasses import dataclass
from .domain import (Conflict, ConflictStatus, Finding, FindingStatus, Result, ReviewRecord,
                     SwarmState, Task, blocking_keys)
from .messaging import unread_messages
from .output import OUTPUT_CONTRACT
from .scope import visible_finding
from .serialization import encode

RECONSIDER = 'RECONSIDER'

AVAILABLE = (FindingStatus.VALIDATED, FindingStatus.PROPOSED, FindingStatus.CRITIQUED)
CANDIDATE_STATUSES = (FindingStatus.PROPOSED, FindingStatus.CRITIQUED)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ContextError(ValueError):
    pass


@dataclass(frozen=True)
class ContextSnapshot:
    json: str
    hash: str
    size: int
    finding_ids: tuple[str, ...]
    finding_revisions: tuple[int, ...]
    message_ids: tuple[str, ...]
    message_revisions: tuple[int, ...]
    propagation_ids: tuple[str, ...]
    propagation_revisions: tuple[int, ...]
    selected_ids: tuple[str, ...]
    omitted_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    criterion_ids: tuple[str, ...]
    criterion_hashes: tuple[str, ...]
    state_id: str | None
    state_revision: int


class _Accumulator:
    """Bounded, auditable payload assembly. Every admission and omission is recorded."""

    def __init__(self, data, caps, measure, limit):
        self.data, self.caps, self.measure, self.limit = data, caps, measure, limit
        self.counts = dict.fromkeys(caps, 0)
        self.selected, self.omitted, self.reasons = [], [], []

    def drop(self, identity, reason):
        self.omitted.append(identity)
        self.reasons.append(f'{identity}:{reason}')

    def add(self, identity, category, value, key, indispensable=False):
        if self.counts[category] >= self.caps[category]:
            if indispensable:
                raise ContextError('INDISPENSABLE_COUNT_OVERFLOW')
            self.drop(identity, 'COUNT_LIMIT')
            return False
        self.data[key].append(value)
        if self.measure() > self.limit:
            self.data[key].pop()
            if indispensable:
                raise ContextError('INDISPENSABLE_CONTEXT_OVERFLOW')
            self.drop(identity, 'SIZE_LIMIT')
            return False
        self.selected.append(identity)
        self.reasons.append(f'{identity}:' + ('REQUIRED' if indispensable else category.upper()))
        self.counts[category] += 1
        return True

    def add_group(self, entries):
        """Admit a dependency-closed group atomically; a partial pin is never recorded."""
        mark = ({k: list(v) for k, v in self.data.items() if isinstance(v, list)},
                list(self.selected), list(self.omitted), list(self.reasons), dict(self.counts))
        for record, category, value, key in entries:
            if self.add(record.id, category, value, key):
                continue
            lists, selected, omitted, reasons, counts = mark
            self.data.update({k: list(v) for k, v in lists.items()})
            self.selected[:], self.omitted[:], self.reasons[:] = selected, omitted, reasons
            self.counts.update(counts)
            for dropped, *_ in entries:
                self.drop(dropped.id, 'GROUP_DROPPED')
            return False
        return True


class _Build:
    """One context construction. Disclosure decisions live here, never in the executor."""

    def __init__(self, builder, snapshot, task, agent, role, tool_specs, assignment_id):
        self.builder, self.snapshot, self.task = builder, snapshot, task
        self.agent, self.role, self.tool_specs = agent, role, tool_specs
        self.assignment_id = assignment_id
        self.run = snapshot[task.run_id]
        self.findings, self.messages, self.propagations = [], [], []
        self.pinned, self.closures = set(), {}
        self.open_conflicts = sorted((c for c in snapshot.values() if isinstance(c, Conflict)
                                      and c.run_id == self.run.id and c.status == ConflictStatus.OPEN),
                                     key=lambda c: c.id)

    def run_build(self):
        criteria = self.criteria()
        state = self.state()
        allowed = self.candidates_allowed()
        required = self.required_closure(allowed)
        data = self.scaffold(criteria)
        caps = {'validated': self.builder.max_validated, 'candidate': self.builder.max_candidates,
                'message': self.builder.max_messages, 'failure': self.builder.max_failures,
                'propagation': self.builder.max_propagations}
        self.out = _Accumulator(data, caps, self.measure, self.builder.max_characters)
        if self.measure() > self.builder.max_characters:
            raise ContextError('INDISPENSABLE_CONTEXT_OVERFLOW')
        self.select_required(required)
        self.select_reviews()
        self.select_propagations()
        self.select_validated(state)
        self.select_messages()
        self.select_candidates(allowed)
        self.select_failures(state)
        return self.result(criteria, state)

    # --- inputs -----------------------------------------------------------------

    def criteria(self):
        criteria = {c.id: c for c in self.run.acceptance_criteria}
        if not set(self.task.acceptance_criterion_ids) <= criteria.keys():
            raise ContextError('UNKNOWN_CRITERION')
        return criteria

    def state(self):
        states = [s for s in self.snapshot.values()
                  if isinstance(s, SwarmState) and s.run_id == self.run.id]
        if len(states) > 1:
            # Serving one of several projections would silently pick stale knowledge.
            raise ContextError('AMBIGUOUS_SWARM_STATE')
        return states[0] if states else None

    def candidates_allowed(self):
        allowed = set(self.task.candidate_finding_ids)
        if self.task.allow_dependency_candidates:
            allowed |= {f.id for f in self.snapshot.values() if isinstance(f, Finding)
                        and f.task_id in self.task.dependency_ids and f.run_id == self.task.run_id}
        return allowed

    def required_closure(self, allowed):
        """Host-assigned evidence, transitively closed. These are controller decisions and
        deliberately cross group scope; automatic selection never does."""
        required = set(self.task.required_finding_ids)
        if self.task.target_finding_id:
            required.add(self.task.target_finding_id)
        pending = sorted(required)
        while pending:
            identity = pending.pop(0)
            f = self.snapshot.get(identity)
            if not isinstance(f, Finding) or f.run_id != self.task.run_id:
                raise ContextError('REQUIRED_FINDING_MISSING')
            if f.status not in AVAILABLE and not (identity == self.task.target_finding_id
                                                  and f.status == FindingStatus.INVALIDATED):
                # Re-criticism is the only route from INVALIDATED back to knowledge, so the
                # target is exempt; supporting evidence is not.
                raise ContextError('REQUIRED_FINDING_UNAVAILABLE')
            if (f.status != FindingStatus.VALIDATED and identity not in allowed
                    and identity != self.task.target_finding_id):
                raise ContextError('CANDIDATE_NOT_PERMITTED')
            for dependency in sorted(f.dependency_finding_ids):
                if dependency not in required:
                    required.add(dependency)
                    pending.append(dependency)
        return required

    def dependencies(self):
        dependencies = []
        for identity in self.task.dependency_ids:
            dep = self.snapshot.get(identity)
            if not isinstance(dep, Task) or dep.run_id != self.task.run_id:
                raise ContextError('DEPENDENCY_MISSING')
            dependencies.append({'id': dep.id, 'revision': dep.revision, 'objective': dep.objective,
                                 'status': dep.status, 'outcome': dep.outcome})
        return dependencies

    def scaffold(self, criteria):
        task, run = self.task, self.run
        self.data = {'assignment_id': self.assignment_id,
                     'task': {'id': task.id, 'objective': task.objective, 'description': task.description},
                     'criteria': [encode(criteria[i]) for i in task.acceptance_criterion_ids],
                     'dependencies': self.dependencies(), 'target_id': task.target_finding_id,
                     'target_revision': getattr(self.snapshot.get(task.target_finding_id), 'revision', None),
                     'findings': [], 'reviews': [], 'messages': [], 'propagations': [],
                     'failed_approaches': [],
                     'tools': [encode(t) for t in self.tool_specs],
                     'limits': {'remaining_requests': run.provider_request_limit - run.provider_requests,
                                'remaining_tool_calls': run.tool_call_limit - run.tool_calls}}
        # Both keys are conditional so no existing context shape or hash changes: a task
        # that neither reviews a result nor synthesizes one sees exactly what it saw before.
        if task.limitations:
            self.data['limitations'] = list(task.limitations)
        target = self.snapshot.get(task.target_result_id) if task.target_result_id else None
        if task.target_result_id:
            if not isinstance(target, Result) or target.run_id != run.id:
                raise ContextError('TARGET_RESULT_MISSING')
            self.data['result'] = self.result_value(target)
        return self.data

    @staticmethod
    def result_value(result):
        """The exact result version under review. Its citations, never its transcript."""
        return {'id': result.id, 'revision': result.revision, 'version': result.version,
                'status': str(result.status), 'answer': result.answer,
                'criterion_ids': list(result.criterion_ids),
                'coverage': [{'criterion_id': e.criterion_id, 'finding_ids': list(e.finding_ids),
                              'required': e.required} for e in result.coverage],
                'claims': [{'claim': c.claim, 'finding_ids': list(c.finding_ids)}
                           for c in result.claims],
                'limitations': list(result.limitations),
                'unresolved_issues': list(result.unresolved_issues)}

    # --- measurement and disclosure ---------------------------------------------

    def packed(self):
        return json.dumps(self.data, sort_keys=True, separators=(',', ':'))

    def measure(self):
        # Measure the actual initial executor framing, including JSON escaping.
        return (len(self.role.instructions) + len(OUTPUT_CONTRACT)
                + len(json.dumps({'objective': self.task.objective, 'context': self.packed(),
                                  'allowed_output_fields': self.role.output_fields})))

    def conflicts_for(self, f):
        return [c for c in self.open_conflicts if f.id in c.finding_ids]

    def value(self, f, full):
        """A contested finding never appears without its conflicts.

        Peer *claims* are included when they are available and disclosable; when they are
        not, the metadata still marks the claim as contested rather than uncontested.
        """
        value = {'id': f.id, 'revision': f.revision, 'status': f.status, 'claim': f.claim}
        conflicts = self.conflicts_for(f)
        if conflicts:
            value['conflicts'] = [{'id': c.id, 'kind': str(c.kind), 'reason': c.reason,
                                   'with': [i for i in c.finding_ids if i != f.id]} for c in conflicts]
        if full:
            value['evidence'] = [encode(e) for e in f.evidence]
        return value

    def peers(self, f):
        """Other validated participants of f's open conflicts, in deterministic order."""
        identities = sorted({i for c in self.conflicts_for(f) for i in c.finding_ids} - {f.id} - self.pinned)
        peers = [self.snapshot.get(i) for i in identities]
        return [p for p in peers if isinstance(p, Finding) and p.status == FindingStatus.VALIDATED
                and visible_finding(p, self.task, self.snapshot)]

    def closure_members(self, identity):
        """Dependencies-first members of an optional finding, or None when any member is
        missing, unavailable or outside this task's disclosure scope.

        Iterative and memoized: a deep or widely shared dependency graph must cost bounded
        work and must never overflow the stack instead of returning a decision.
        """
        if identity in self.closures:
            return self.closures[identity]
        order, walked, stack = [], set(), [(identity, False)]
        while stack:
            current, expanded = stack.pop()
            if expanded:
                order.append(self.snapshot[current])
                continue
            if current in walked:
                continue
            walked.add(current)
            f = self.snapshot.get(current)
            if (not isinstance(f, Finding) or f.status not in AVAILABLE
                    or not visible_finding(f, self.task, self.snapshot)):
                self.closures[identity] = None
                return None
            stack.append((current, True))
            for dependency in sorted(f.dependency_finding_ids, reverse=True):
                stack.append((dependency, False))
        self.closures[identity] = tuple(order)
        return self.closures[identity]

    def admit_optional(self, identity):
        members = self.closure_members(identity)
        if members is None:
            self.out.drop(identity, 'NOT_DISCLOSABLE')
            return
        entries = [(f, self.category(f), self.value(f, False), 'findings')
                   for f in members if f.id not in self.pinned]
        if entries and self.out.add_group(entries):
            self.pinned.update(record.id for record, *_ in entries)
            self.findings.extend(record for record, *_ in entries)

    @staticmethod
    def category(f):
        return 'validated' if f.status == FindingStatus.VALIDATED else 'candidate'

    # --- selection phases --------------------------------------------------------

    def select_required(self, required):
        for identity in sorted(required, key=lambda i: (i != self.task.target_finding_id, i)):
            f = self.snapshot[identity]
            self.out.add(f.id, self.category(f), self.value(f, True), 'findings', True)
            self.findings.append(f)
            self.pinned.add(f.id)
        for identity in sorted(required):
            for peer in self.peers(self.snapshot[identity]):
                if self.out.add(peer.id, self.category(peer), self.value(peer, False), 'findings'):
                    self.findings.append(peer)
                    self.pinned.add(peer.id)

    def review_targets(self):
        """Which record's review history this assignment is entitled to see.

        A synthesis revision sees exactly the final review that asked for it — bounded
        feedback naming one result version, never the run's review history at large.
        """
        identities = [self.task.target_finding_id, self.task.target_result_id]
        if self.task.source_review_id:
            review = self.snapshot.get(self.task.source_review_id)
            if isinstance(review, ReviewRecord):
                identities.append(review.target_id)
        return [i for i in identities if isinstance(self.snapshot.get(i), (Finding, Result))]

    def select_reviews(self):
        """Host-assigned review history for the target claim; a validator must see the
        blocking issues it is expected to resolve, keyed so it can name them."""
        targets = self.review_targets()
        if not targets:
            return
        for review in sorted((r for r in self.snapshot.values() if isinstance(r, ReviewRecord)
                              and r.run_id == self.run.id and r.target_id in targets), key=lambda r: r.id):
            self.data['reviews'].append({
                'id': review.id, 'kind': str(review.kind), 'decision': str(review.decision),
                'target_revision': review.target_revision, 'summary': review.summary,
                'checks': list(review.checks), 'nonblocking_issues': list(review.nonblocking_issues),
                'blocking_issues': [{'key': key, 'issue': issue}
                                    for key, issue in zip(blocking_keys(review), review.blocking_issues)],
                **({'criterion_ids': list(review.criterion_ids),
                    'unsupported_claims': list(review.unsupported_claims)}
                   if review.criterion_ids or review.unsupported_claims else {})})
        if self.measure() > self.builder.max_characters:
            raise ContextError('INDISPENSABLE_CONTEXT_OVERFLOW')

    def select_propagations(self):
        """Cross-branch knowledge enters only through an explicit delivery record.

        Nothing here scans validated knowledge looking for something this agent might like:
        every entry names the propagation that authorized it, the exact source revision, the
        relevance score and the features that produced it, so the audit can answer why this
        assignment received this discovery. The payload is the bounded insight the decision
        recorded — never evidence, a transcript or another branch's history.
        """
        from .propagation import for_task
        for propagation, consumable in for_task(self.snapshot, self.task):
            value = {'id': propagation.id, 'kind': str(propagation.kind), 'action': RECONSIDER,
                     'consumable': consumable, 'finding_id': propagation.canonical_finding_id,
                     'finding_revision': propagation.knowledge_revision,
                     'insight': propagation.insight, 'why': propagation.reason,
                     'score': propagation.score,
                     'matched_features': list(propagation.matched_features),
                     'target_task_id': propagation.target_task_id}
            if propagation.conflict_id:
                value['conflict_id'] = propagation.conflict_id
            if propagation.retracts_id:
                value['retracts'] = propagation.retracts_id
            if propagation.outcome is not None:
                value['outcome'] = str(propagation.outcome)
            if self.out.add(propagation.id, 'propagation', value, 'propagations'):
                self.propagations.append(propagation)

    def relevant(self, f):
        task = self.task
        return visible_finding(f, task, self.snapshot) and (
            f.task_id in task.dependency_ids or f.task_id == task.id
            or bool(set(f.tags) & set(task.tags))
            or bool(set(f.criterion_ids) & set(task.acceptance_criterion_ids)))

    def select_validated(self, state):
        # Only validated knowledge explicitly projected into shared state is globally eligible.
        pool = [self.snapshot[i] for i in state.validated_findings
                if i in self.snapshot] if state else []
        eligible = (f for f in pool if isinstance(f, Finding) and f.run_id == self.task.run_id
                    and f.status == FindingStatus.VALIDATED and f.id not in self.pinned
                    and self.relevant(f))
        for f in sorted(eligible, key=lambda f: (f.task_id not in self.task.dependency_ids, f.id)):
            if f.id in self.pinned:
                continue
            # A conflicted finding is admitted with its peers or not at all, so optional
            # selection can never present one side of an open conflict as uncontested.
            entries = [(f, 'validated', self.value(f, True), 'findings')] + [
                (peer, 'validated', self.value(peer, False), 'findings') for peer in self.peers(f)]
            if self.out.add_group(entries):
                self.findings.extend(record for record, *_ in entries)
                self.pinned.update(record.id for record, *_ in entries)

    def select_messages(self):
        for message in unread_messages(self.snapshot, self.agent.id):
            if message.run_id != self.task.run_id:
                continue
            value = {'id': message.id, 'kind': message.kind, 'summary': message.summary,
                     'reference_ids': message.reference_ids}
            if not self.out.add(message.id, 'message', value, 'messages'):
                continue
            self.messages.append(message)
            # Pin what a delivered message points at, so a retraction invalidates the output.
            for identity in message.reference_ids:
                if isinstance(self.snapshot.get(identity), Finding) and identity not in self.pinned:
                    self.admit_optional(identity)

    def select_candidates(self, allowed):
        for identity in sorted(allowed - self.pinned):
            self.admit_optional(identity)

    def select_failures(self, state):
        for i, failure in enumerate(state.failed_approaches if state else ()):
            self.out.add(f'failure:{i}', 'failure', failure, 'failed_approaches')

    def result(self, criteria, state):
        out, task = self.out, self.task
        return ContextSnapshot(
            self.packed(), digest(self.data), self.measure(),
            tuple(f.id for f in self.findings), tuple(f.revision for f in self.findings),
            tuple(m.id for m in self.messages), tuple(m.delivery_revision for m in self.messages),
            tuple(p.id for p in self.propagations), tuple(p.revision for p in self.propagations),
            tuple(out.selected), tuple(out.omitted), tuple(out.reasons),
            task.acceptance_criterion_ids,
            tuple(digest(encode(criteria[i])) for i in task.acceptance_criterion_ids),
            state.id if state else None, state.revision if state else 0)


@dataclass(frozen=True)
class ContextBuilder:
    max_validated: int = 8
    max_candidates: int = 4
    max_messages: int = 5
    max_failures: int = 3
    max_propagations: int = 3
    max_characters: int = 24000

    def build(self, snapshot, task, agent, role, tool_specs, *, assignment_id):
        return _Build(self, snapshot, task, agent, role, tool_specs, assignment_id).run_build()
