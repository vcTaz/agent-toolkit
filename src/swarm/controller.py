"""The work engine: identity, transactions, scheduling and the execution seam.

This is the part of the controller that turns one authorized task into one bounded
assignment and one bounded assignment into a validated batch of records. It owns no
workflow: which phase the run is in, whether it is ready to answer and when it ends belong
to ``orchestration`` above it, and the decisions themselves to the plain policy functions
beside it.

Executors hold no repository handle. Everything durable passes through ``commit``.
"""
import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from .domain import (Agent, AgentStatus, Task, TaskStatus, Assignment, AssignmentStatus,
                     Finding, Message, MessageStatus, Result, SwarmState, now, transition,
                     assign_role)
from .events import EventDraft, EventType
from .contracts import Budget, ExecutionContext, ExecutionError
from .execution import execute
from .audit import RepositoryAudit
from .persistence import StorageError
from .policies import (BudgetPolicy, compatible_agents, compatible_review_agents, eligible_agents,
                       ready_decision, reserved_for_review, review_kind, role_for, select_tasks,
                       retry_allowed, stopped, remaining_seconds, FINAL_REVIEW_KIND, SYNTHESIS_KIND)
from .context import ContextBuilder, ContextError, digest
from .admission import check_assignment_admissibility
from .outcomes import admit_proposals
from .messaging import route_message
from .review import ReviewPolicy, admit_review
from .verification import VerificationRegistry, structured_sum_value
from .propagation import PropagationPolicy, for_task, open_cycle
from .cycles import open_records
from .finalreview import admit_final_review, started_event as final_review_started
from .synthesis import admit_result
from . import knowledge
from .serialization import encode


class ControllerCore:
    """Own a run's work on one event-loop thread; synchronous commits never interleave.

    Exactly one live controller may own a run. Existing active assignments are refused;
    this is intentionally not a crash-resume service.
    """
    def __init__(self, repository, run_id, providers, tools=None, *, context_builder=None,
                 budget_policy=None, verification=None, review_policy=None, structured_value=None,
                 propagation_policy=None):
        self.repo, self.run_id = repository, run_id
        self.providers, self.tools = dict(providers), dict(tools or {})
        self.context_builder = context_builder or ContextBuilder()
        self.budget_policy = budget_policy or BudgetPolicy()
        self.verification = verification or VerificationRegistry()
        self.review_policy = review_policy or ReviewPolicy()
        self.propagation_policy = propagation_policy or PropagationPolicy()
        self.structured_value = structured_value or structured_sum_value
        self.active = {}
        self.reservations = set()
        self.budget = None
        self._running = False
        self._cancelled = False
        self._storage_failed = False
        self._wake = asyncio.Event()
        self._serial = 0
        self._tool_results = {}
        self._recorded_gaps = None

    def snapshot(self):
        return self.repo.snapshot(self.run_id)

    def identity(self, kind):
        while True:
            self._serial += 1
            identity = f'{self.run_id}:{kind}:{self._serial:06}'
            if self.repo.get(self.run_id, identity) is None:
                return identity

    def event(self, kind, record=None, **detail):
        return EventDraft(type=kind, record_id=record.id if record else None,
            record_revision=record.revision if record else None,
            task_id=record.id if isinstance(record, Task) else getattr(record, 'task_id', None),
            agent_id=record.id if isinstance(record, Agent) else getattr(record, 'agent_id', None),
            assignment_id=record.id if isinstance(record, Assignment) else getattr(record, 'assignment_id', None),
            detail_json=json.dumps(detail, allow_nan=False))

    def commit(self, records=(), events=()):
        records, events = list(records), list(events)
        covered = {e.record_id for e in events}
        events += [self.event(EventType.RECORD_CHANGED, r) for r in records if r.id not in covered]
        self.repo.commit(self.run_id, records, events)

    def send_message(self, message):
        s = self.snapshot()
        if message.id in s:
            raise ValueError('message identity already exists')
        _, reason = route_message(message, s)
        if reason:
            self.commit(events=[self.event(EventType.MESSAGE_REJECTED, reason=reason,
                                           recipient=message.recipient)])
            return False
        self.commit([message], [self.event(EventType.MESSAGE_SENT, message)])
        self.deliver_messages()
        return True

    def deliver_messages(self):
        for message in sorted((r for r in self.snapshot().values()
                               if isinstance(r, Message) and r.status == MessageStatus.QUEUED), key=lambda m: (m.created_at, m.id)):
            delivered, reason = route_message(message, self.snapshot())
            record = delivered or transition(message, MessageStatus.REJECTED)
            self.commit([record], [self.event(EventType.MESSAGE_DELIVERED if delivered else EventType.MESSAGE_REJECTED,
                                             record, reason=reason, delivered_to=record.delivered_to)])

    def _settle(self, snapshot, records, events):
        """Extend one authoritative transaction with the knowledge state it implies.

        Conflict maintenance and the shared-state projection are committed together with
        the finding changes that caused them, so the repository can never hold a VALIDATED
        finding that SwarmState still classifies as a candidate, or the reverse.
        """
        records, events = list(records), list(events)
        merged = dict(snapshot)
        merged.update({r.id: r for r in records})
        conflicts, conflict_events, merged = knowledge.maintain_conflicts(
            merged, self.run_id, self.identity, self.structured_value)
        records += conflicts
        events += conflict_events
        state = next((r for r in merged.values() if isinstance(r, SwarmState)), None)
        if state is not None:
            updated = knowledge.project(merged, state)
            if updated is not None:
                records.append(updated)
        return records, events

    def _sync_state(self):
        s = self.snapshot()
        records, events = self._settle(s, [], [])
        if records or events:
            self.commit(records, events)

    def invalidate_finding(self, finding_id, reason='INVALIDATED'):
        """Invalidate a validated finding and every validated dependent, atomically with
        the knowledge removal. Returns the invalidated identities."""
        s = self.snapshot()
        records, events = knowledge.invalidate_closure(s, self.run_id, finding_id, reason)
        if not records:
            return ()
        records, events = self._settle(s, records, events)
        self.commit(records, events)
        self.retract(reason)
        self._wake.set()
        return tuple(r.id for r in records if isinstance(r, Finding))

    def cancel(self, reason='CANCELLED'):
        self._cancelled = True
        self._stop(reason)
        self._wake.set()
        for worker in self.active.values():
            worker.cancel()

    def _stop(self, reason):
        s = self.snapshot()
        records, events = [], []
        run = s[self.run_id]
        if not run.work_stop_reason:
            run = replace(run, work_stop_reason=reason, revision=run.revision + 1, updated_at=now())
            records.append(run)
            events.append(self.event(EventType.WORK_STOPPED, run, reason=reason))
        for r in s.values():
            if isinstance(r, Task) and r.status in (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING):
                changed = replace(transition(r, TaskStatus.CANCELLED), assignment_id=None, outcome=reason)
                records.append(changed)
                events.append(self.event(EventType.TASK_CANCELLED, changed, reason=reason))
            elif isinstance(r, Assignment) and r.status in (AssignmentStatus.CREATED, AssignmentStatus.RUNNING):
                changed = replace(transition(r, AssignmentStatus.CANCELLED), ended_at=now())
                records.append(changed)
            elif isinstance(r, Agent) and r.status == AgentStatus.RUNNING:
                changed = replace(transition(r, AgentStatus.IDLE), assignment_id=None)
                records.append(changed)
                events.append(self.event(EventType.AGENT_FAILED, changed, reason=reason))
        if records or events:
            self.commit(records, events)

    def _fail_pending(self, task, reason, cancel=False):
        changed = replace(transition(task, TaskStatus.CANCELLED if cancel else TaskStatus.FAILED), outcome=reason)
        self.commit([changed], [self.event(EventType.TASK_CANCELLED if cancel else EventType.TASK_FAILED,
                                          changed, reason=reason)])

    def _prepare(self, task, agent, role, s):
        new_id = self.identity('assignment')
        names = tuple(sorted(set(s[self.run_id].permissions) & set(agent.permissions) & set(role.allowed_tools) & self.tools.keys()))
        specs = tuple(self.tools[n].spec for n in names)
        context = self.context_builder.build(s, task, agent, role, specs, assignment_id=new_id)
        attempt = 1 + sum(isinstance(a, Assignment) and a.task_id == task.id for a in s.values())
        if attempt > s[self.run_id].assignment_attempt_limit:
            raise ContextError('ATTEMPT_LIMIT')
        # A final review is pinned to the exact result version it was dispatched against, so
        # a version that moves underneath it makes the returned review stale by the same rule.
        target = s.get(task.target_result_id) if task.target_result_id else None
        if task.target_result_id and not isinstance(target, Result):
            raise ContextError('REVIEW_TARGET_RESULT_MISSING')
        assignment = Assignment(id=new_id, run_id=self.run_id, task_id=task.id, agent_id=agent.id,
            role_id=role.id, role_version=role.version, provider_key=agent.provider_key,
            attempt=attempt, task_revision=task.revision + 1, group_id=task.group_id,
            input_finding_ids=context.finding_ids, input_finding_revisions=context.finding_revisions,
            dependency_task_ids=task.dependency_ids,
            dependency_task_revisions=tuple(s[i].revision for i in task.dependency_ids),
            message_ids=context.message_ids, message_revisions=context.message_revisions,
            propagation_ids=context.propagation_ids,
            propagation_revisions=context.propagation_revisions,
            criterion_ids=context.criterion_ids, criterion_hashes=context.criterion_hashes,
            tool_names=names, tool_hashes=tuple(digest(encode(t)) for t in specs),
            result_id=target.id if target is not None else None,
            result_revision=target.revision if target is not None else 0,
            state_id=context.state_id, state_revision=context.state_revision,
            context_json=context.json, context_hash=context.hash)
        records = [assignment]
        events = [self.event(EventType.CONTEXT_SELECTED, assignment,
                    selected_ids=context.selected_ids, omitted_ids=context.omitted_ids, reasons=context.reasons,
                    size=context.size, context_hash=context.hash)]
        if agent.role_id != role.id:
            agent = assign_role(agent, role)
            records.append(agent)
            events.append(self.event(EventType.ROLE_ASSIGNED, agent, role_id=role.id, role_version=role.version))
        self.commit(records, events)
        # Activation is a single authoritative lifecycle transaction after preparation.
        task = replace(transition(task, TaskStatus.RUNNING), assignment_id=assignment.id)
        agent = replace(transition(agent, AgentStatus.RUNNING), assignment_id=assignment.id)
        assignment = replace(transition(assignment, AssignmentStatus.RUNNING), started_at=now())
        activation = [self.event(EventType.TASK_ASSIGNED, task, agent_id=agent.id),
                      self.event(EventType.AGENT_STARTED, agent),
                      self.event(EventType.RECORD_CHANGED, assignment)]
        kind = review_kind(task)
        if target is not None:
            activation.append(final_review_started(task, target, assignment))
        elif kind:
            activation.append(self.event(EventType.REVIEW_STARTED, review_kind=str(kind), agent_id=agent.id,
                task_id=task.id, assignment_id=assignment.id, target_finding_id=task.target_finding_id,
                target_revision=dict(zip(assignment.input_finding_ids,
                                         assignment.input_finding_revisions)).get(task.target_finding_id)))
        elif task.kind == SYNTHESIS_KIND:
            activation.append(self.event(EventType.SYNTHESIS_STARTED, phase='DISPATCHED',
                agent_id=agent.id, task_id=task.id, assignment_id=assignment.id,
                support=list(assignment.input_finding_ids),
                attempt=s[self.run_id].synthesis_attempts))
        owed = [p.id for p, consumable in for_task(s, task)
                if consumable and p.id in assignment.propagation_ids]
        if owed:
            activation.append(self.event(EventType.RECONSIDERATION_STARTED, task_id=task.id,
                assignment_id=assignment.id, agent_id=agent.id, propagation_ids=owed))
        self.commit([task, agent, assignment], activation)
        self.reservations.add(assignment.id)
        return assignment

    def _audit(self, assignment, event):
        if self._storage_failed:
            raise StorageError('controller stopped after storage failure')
        if event.type in (EventType.PROVIDER_REQUESTED, EventType.TOOL_STARTED):
            s = self.snapshot()
            current = s.get(assignment.id)
            if current is None or current.status != AssignmentStatus.RUNNING or stopped(s[self.run_id]):
                raise ExecutionError('assignment no longer authorized')
            task = s[assignment.task_id]
            if remaining_seconds(s[self.run_id]) <= 0:
                raise ExecutionError('run deadline exceeded')
            if event.type == EventType.PROVIDER_REQUESTED:
                # Ignore this assignment's own first-request reservation; preserve others.
                count = len(self.reservations - {assignment.id})
                decision = self.budget_policy.admit(task, s, count)
                if not decision.allowed:
                    raise ExecutionError(decision.reason)
            elif s[self.run_id].tool_call_limit - s[self.run_id].tool_calls <= self.budget_policy.reserved_tools:
                raise ExecutionError('reserved tool budget')
        RepositoryAudit(self.repo, self.run_id)(event)
        if event.type == EventType.PROVIDER_REQUESTED:
            self.reservations.discard(assignment.id)
        elif event.type == EventType.TOOL_COMPLETED:
            data = json.loads(event.detail_json).get('result')
            if data:
                self._tool_results.setdefault(assignment.id, {})[data['id']] = data

    async def _execute(self, assignment):
        s = self.snapshot()
        task, agent, role = s[assignment.task_id], s[assignment.agent_id], s[assignment.role_id]
        context = ExecutionContext(run_id=self.run_id, assignment_id=assignment.id, agent_id=agent.id,
            task_id=task.id, objective=task.objective, relevant_context=assignment.context_json,
            run_tools=assignment.tool_names, agent_tools=assignment.tool_names)
        return await execute(context, role, self.providers[assignment.provider_key], self.tools,
            audit=lambda event: self._audit(assignment, event), budget=self.budget,
            timeout=min(s[self.run_id].execution_timeout, remaining_seconds(s[self.run_id])))

    def _finish(self, assignment, result=None, error=None):
        s = self.snapshot()
        current = s.get(assignment.id)
        if current is None or current.status != AssignmentStatus.RUNNING:
            self.commit(events=[self.event(EventType.OUTPUT_REJECTED, reason='ASSIGNMENT_NOT_RUNNING', assignment_id=assignment.id)])
            return
        task, agent, run = s[assignment.task_id], s[assignment.agent_id], s[self.run_id]
        records, events, reason = [], [], error
        if result is not None:
            records, events, reason = self._admit(assignment, result, s, task)
        success = reason is None and result is not None and result.status == 'SUCCEEDED'
        if success:
            task = replace(transition(task, TaskStatus.COMPLETED), assignment_id=None, outcome=result.summary)
            current = replace(transition(current, AssignmentStatus.COMPLETED), ended_at=now())
            kind = EventType.TASK_COMPLETED
            # Receipts follow consumed work, so a bounded retry keeps the same targeted messages.
            for identity in assignment.message_ids:
                m = s.get(identity)
                if isinstance(m, Message) and agent.id not in m.read_by:
                    records.append(replace(m, read_by=m.read_by + (agent.id,), revision=m.revision + 1))
        else:
            reason = reason or 'FAILED'
            retry = retry_allowed(assignment.attempt, run, reason) and run.provider_requests < run.provider_request_limit
            task = replace(transition(task, TaskStatus.READY if retry else TaskStatus.FAILED), assignment_id=None, outcome=reason)
            current = replace(transition(current, AssignmentStatus.FAILED), ended_at=now())
            kind = EventType.RETRY_SCHEDULED if retry else EventType.TASK_FAILED
        agent = replace(transition(agent, AgentStatus.IDLE), assignment_id=None)
        records += [task, current, agent]
        events += [self.event(kind, task, reason=reason), self.event(EventType.AGENT_COMPLETED if success else EventType.AGENT_FAILED, agent, reason=reason)]
        if not success and review_kind(task):
            events.append(self.event(EventType.REVIEW_REJECTED, reason=reason, task_id=task.id,
                                     assignment_id=assignment.id,
                                     target_finding_id=task.target_finding_id))
        records, events = self._settle(s, records, events)
        self.commit(records, events)

    def _admit(self, assignment, result, snapshot, task):
        """Re-validate a returned envelope against current state; return records, events, reason.

        Nothing is committed here: a rejected envelope leaves canonical state untouched.
        """
        decision = check_assignment_admissibility(assignment, result, snapshot,
                                                  tuple(t.spec for t in self.tools.values()))
        if not decision.allowed:
            return [], [self.event(EventType.OUTPUT_REJECTED, reason=decision.reason,
                                   assignment_id=assignment.id)], decision.reason
        if result.status != 'SUCCEEDED':
            return [], [], result.status + ': ' + result.summary
        audited = self._tool_results.get(assignment.id, {})
        if any(audited.get(t.id) != encode(t) for t in result.tool_results):
            return [], [], 'UNTRUSTED_TOOL_RESULTS'
        try:
            if task.kind == SYNTHESIS_KIND:
                records, events, _ = admit_result(assignment, result, snapshot, self.identity)
                return records, events, None
            if task.kind == FINAL_REVIEW_KIND:
                records, events, _ = admit_final_review(assignment, result, snapshot, self.identity)
                return records, events, None
            if review_kind(task):
                records, events, _ = admit_review(assignment, result, snapshot, self.identity,
                                                 self.verification)
                return records, events, None
            return (*admit_proposals(assignment, result, snapshot, self.identity), None)
        except ValueError as exc:
            return [], [], str(exc)

    def _schedule(self, original, run):
        """Decide one task's dispatch on a fresh snapshot; no await may occur here."""
        s = self.snapshot()
        task = s[original.id]
        decision = ready_decision(task, s)
        if not decision.allowed:
            if decision.permanent:
                self._fail_pending(task, decision.reason, cancel=True)
            return None
        role = role_for(task, s)
        if not (role and compatible_agents(task, role, s, self.tools.keys(), self.providers.keys(), False)):
            self._fail_pending(task, 'PERMISSION_OR_ROLE_INCOMPATIBLE')
            return None
        if review_kind(task) and not compatible_review_agents(task, role, s, self.tools.keys(),
                                                              self.providers.keys(), False):
            # Independence is decided before dispatch; no provider request is spent to
            # discover at commit time that the only candidate is the author.
            self._review_gap(task, 'NO_INDEPENDENT_REVIEWER')
            return None
        decision = self.budget_policy.admit(task, s, len(self.reservations))
        if not decision.allowed:
            # Nothing is in flight to free capacity later, so the shortfall is permanent.
            if not self.active:
                self._fail_pending(task, decision.reason, cancel=True)
            return None
        # Generation, criticism and validation each need a distinct identity, so the pool is
        # a resource: optional propagation-driven work never takes the agent a due review needs.
        reserved = reserved_for_review(task, s, self.tools.keys(), self.providers.keys())
        agents = [a for a in eligible_agents(task, role, s, self.tools.keys(), self.providers.keys())
                  if a.id not in reserved]
        if not agents:
            return None
        if task.status == TaskStatus.PENDING:
            task = transition(task, TaskStatus.READY)
            self.commit([task], [self.event(EventType.TASK_READY, task)])
            s[task.id] = task
        try:
            return self._prepare(task, agents[0], role, s)
        except ContextError as exc:
            self._fail_pending(task, str(exc))
            return None

    def _dispatch(self, run):
        """Fill free concurrency slots in deterministic priority order."""
        pending = [t for t in self.snapshot().values()
                   if isinstance(t, Task) and t.status in (TaskStatus.PENDING, TaskStatus.READY)]
        for original in select_tasks(pending):
            if len(self.active) >= run.concurrency_limit:
                return
            assignment = self._schedule(original, run)
            if assignment is not None:
                self.active[assignment.id] = asyncio.create_task(self._execute(assignment))

    def _collect(self, done):
        for identity in sorted([i for i, w in self.active.items() if w in done]):
            worker = self.active.pop(identity)
            self.reservations.discard(identity)
            # Consume the worker outcome before touching storage, so a failing repository
            # cannot leave an execution exception unretrieved.
            outcome, failure = None, None
            if worker.cancelled():
                failure = 'CANCELLED'
            else:
                error = worker.exception()
                if error is None:
                    outcome = worker.result()
                elif isinstance(error, StorageError):
                    raise error
                else:
                    failure = f'{type(error).__name__}: {error}'
            self._finish(self.repo.get(self.run_id, identity), result=outcome, error=failure)

    async def _await_progress(self):
        self._wake.clear()
        wake = asyncio.create_task(self._wake.wait())
        done, _ = await asyncio.wait([*self.active.values(), wake],
            timeout=max(0, remaining_seconds(self.snapshot()[self.run_id])),
            return_when=asyncio.FIRST_COMPLETED)
        wake.cancel()
        await asyncio.gather(wake, return_exceptions=True)
        return done

    def _open_run(self):
        s = self.snapshot()
        run = s[self.run_id]
        if any(isinstance(a, Assignment) and a.status in (AssignmentStatus.CREATED, AssignmentStatus.RUNNING)
               for a in s.values()):
            raise RuntimeError('unfinished assignments require explicit host handling; no automatic resume')
        if run.deadline_at is None:
            deadline = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            run = replace(run, deadline_at=deadline, revision=run.revision + 1)
            self.commit([run])
        if not any(isinstance(r, SwarmState) for r in s.values()):
            # One logical projection per run, created once and revised in place thereafter.
            self.commit([SwarmState(id=self.identity('state'), run_id=self.run_id)])
        current = self.snapshot()[self.run_id]
        if (not stopped(current) and open_cycle(self.snapshot(), self.run_id) is None
                and current.cycle < current.cycle_limit):
            # The initial exploration wave is cycle one; re-entering a settled run continues
            # the numbering, so every wave counts against the same bounded limit.
            cycle, event = open_records(self.identity, self.run_id, current.cycle + 1, ())
            advanced = replace(current, cycle=current.cycle + 1, revision=current.revision + 1,
                               updated_at=now())
            self.commit([cycle, advanced], [event, self.event(EventType.RECORD_CHANGED, advanced)])
        run = self.snapshot()[self.run_id]
        self.budget = Budget(run.provider_request_limit, run.tool_call_limit,
                             run.provider_requests, run.tool_calls)

    async def _drain(self):
        workers = list(self.active.values())
        for worker in workers:
            worker.cancel()
        if workers:
            done, pending = await asyncio.wait(workers, timeout=0.1)
            for worker in done:
                if not worker.cancelled():
                    worker.exception()
            for worker in pending:
                worker.add_done_callback(lambda w: None if w.cancelled() else w.exception())
        self.active.clear()
        self.reservations.clear()
        self._running = False

