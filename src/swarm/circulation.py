"""Circulation: cross-pollination, retraction, consolidation, cycles and branch stopping.

The controller methods that move *knowledge* rather than work. Every decision here is
deterministic and costs no provider request; the records and the reasons are written by the
Stage-6 services, and this layer only sequences them into authoritative transactions.

Split out of the controller at Stage 7 because the run-level workflow arrived above it and
these methods are cohesive on their own; nothing about their behaviour changed.
"""
from dataclasses import replace
from .domain import (AgentGroup, GroupStatus, Propagation, PropagationStatus, SwarmState, Task,
                     TaskStatus, now, transition)
from .events import EventType
from .policies import remaining_seconds, stopped
from .review import plan_reviews, review_task
from .propagation import (admissible_follow_up, current_cycle, deliver, deliverable, follow_up_task,
                          link_task, open_cycle, plan_propagations, propagation_records, retractions,
                          skip, terminal_target)
from .cycles import (active_groups, branch_stop_reason, close_records, coverage_gaps, cycle_triggers,
                     measure_branch, open_records, progress_records, stop_records)
from . import knowledge


class Circulation:
    """Mixin over ``ControllerCore``; it uses ``commit``/``snapshot``/``identity`` only."""

    # --- cross-pollination ------------------------------------------------------

    def propagate(self):
        """Route newly eligible validated knowledge to a bounded set of relevant tasks.

        Deterministic: no provider request is made. Idempotent: the delivery key already
        stored for a target at this knowledge revision makes a repeated pass a no-op, so it
        does not matter how often the loop reaches here.
        """
        s = self.snapshot()
        decisions = plan_propagations(s, self.run_id, self.propagation_policy)
        if decisions:
            state = next((r for r in s.values() if isinstance(r, SwarmState)), None)
            records, events = propagation_records(decisions, self.identity, self.run_id,
                                                  state.revision if state else 0,
                                                  current_cycle(s, self.run_id))
            self.commit(records, events)
        self._deliver_propagations()
        return decisions

    def retract(self, reason='KNOWLEDGE_INVALIDATED'):
        """Tell exactly the targets that received knowledge which has become ineligible.

        Nothing is broadcast: the recipients are the stored deliveries themselves, so a
        target that never received this revision is never told about it, and a newer valid
        revision delivered to the same target is untouched.
        """
        s = self.snapshot()
        records, events = retractions(s, self.run_id, self.identity,
                                      current_cycle(s, self.run_id), reason)
        if not records:
            return ()
        self.commit(records, events)
        self._deliver_propagations()
        return tuple(r.id for r in records if r.retracts_id)

    def _deliver_propagations(self):
        """Make selected deliveries readable, or close the ones nothing can consume.

        A running assignment's snapshot is never mutated: while its target runs, the
        decision stays SELECTED and becomes readable only for a later assignment.
        """
        s = self.snapshot()
        records, events = [], []
        for propagation in sorted((p for p in s.values() if isinstance(p, Propagation)
                                   and p.run_id == self.run_id
                                   and p.status in (PropagationStatus.SELECTED, PropagationStatus.DELIVERED)),
                                  key=lambda p: p.id):
            reason = terminal_target(propagation, s)
            if reason is not None:
                record, event = skip(propagation, reason)
            elif propagation.status == PropagationStatus.SELECTED and deliverable(propagation, s):
                record, event = deliver(propagation)
            else:
                continue
            records.append(record)
            events.append(event)
        if records:
            self.commit(records, events)

    def consolidate(self):
        """Deterministic duplicate detection and conflict refresh; no model is involved."""
        s = self.snapshot()
        report = knowledge.consolidate(s, self.run_id)
        records, events = self._settle(s, [], [])
        events.append(self.event(EventType.CONSOLIDATION_COMPLETED,
            groups=[{'claim': g.claim, 'signature': g.signature, 'canonical_id': g.canonical_id,
                     'member_ids': list(g.member_ids)} for g in report.groups],
            canonical_ids=list(report.canonical_ids), duplicate_ids=list(report.duplicate_ids),
            open_conflict_ids=list(report.conflict_ids)))
        self.commit(records, events)
        return report

    def coverage(self):
        return knowledge.criterion_coverage(self.snapshot(), self.run_id)

    def _plan_reviews(self):
        """Controller-owned review scheduling. A worker never requests its own promotion."""
        s = self.snapshot()
        for plan in plan_reviews(s, self.run_id, self.review_policy):
            task = review_task(plan, self.identity, self.run_id, s, self.review_policy)
            self.commit([task], [self.event(EventType.TASK_CREATED, task, task_kind=task.kind,
                                            review_kind=str(plan.kind), target_finding_id=plan.finding_id,
                                            target_revision=s[plan.finding_id].revision)])
            s = self.snapshot()

    def _review_gap(self, task, reason):
        """A bounded, durable review gap. Never a fallback to self-review."""
        changed = replace(transition(task, TaskStatus.FAILED), outcome=reason)
        self.commit([changed], [self.event(EventType.TASK_FAILED, changed, reason=reason),
                                self.event(EventType.REVIEW_REJECTED, reason=reason,
                                           task_id=task.id, task_kind=task.kind,
                                           target_finding_id=task.target_finding_id)])

    def close_group(self, group_id, reason='CLOSED'):
        group = self.repo.get(self.run_id, group_id)
        if not isinstance(group, AgentGroup):
            raise ValueError('unknown group')
        closed = replace(transition(group, GroupStatus.CLOSED), stop_reason=reason)
        self.commit([closed], [self.event(EventType.GROUP_CLOSED, closed, reason=reason)])
        self._wake.set()

    # --- cycles and branches ----------------------------------------------------
    # --- cycles and branches ----------------------------------------------------

    def _stop_branch(self, group, reason):
        """Close one branch, cancelling only its own schedulable work.

        Everything the branch established stays: findings keep their status, its knowledge
        stays in the projection, and no independent branch is touched.
        """
        s = self.snapshot()
        records, events = stop_records(s, self.run_id, group, reason)
        records, events = self._settle(s, records, events)
        self.commit(records, events)

    def _close_cycle(self, unresolved=(), cycle_exhausted=False):
        """Measure every open branch, stop the ones that qualify, then close the wave."""
        s = self.snapshot()
        cycle = open_cycle(s, self.run_id)
        number = cycle.number if cycle else s[self.run_id].cycle
        records, events = [], []
        for group in active_groups(s, self.run_id):
            updated, event, _ = progress_records(s, self.run_id, group, number)
            records.append(updated)
            events.append(event)
        if records:
            self.commit(records, events)
        blocked = [s[t.propagation_id] for t in unresolved if isinstance(s.get(t.propagation_id), Propagation)]
        for group in active_groups(self.snapshot(), self.run_id):
            current = self.snapshot()
            reason = branch_stop_reason(current, self.run_id, current[group.id],
                                        measure_branch(current, self.run_id, group),
                                        cycle_exhausted=cycle_exhausted, unresolved=blocked)
            if reason is not None:
                self._stop_branch(current[group.id], reason)
        s = self.snapshot()
        gaps = coverage_gaps(s, self.run_id)
        if cycle is not None:
            closed, event = close_records(s[cycle.id], [t.propagation_id for t in unresolved], gaps)
            self.commit([closed], [event])
        if gaps:
            self._recorded_gaps = gaps
            self.commit(events=[self.event(EventType.COVERAGE_GAP, cycle=number, gaps=gaps,
                                           cycle_exhausted=cycle_exhausted)])

    def _open_cycle(self, triggers):
        """Open the next wave, but only if it really admits executable work.

        A wave is charged against ``cycle_limit`` when it admitted investigation or repair
        work, not because propagation was considered. Bookkeeping that produces only
        NO_CHANGE answers and no task therefore costs no wave: the cycle record and the
        run's counter are written in the same transaction as the first admitted task, so a
        wave that admits nothing was never opened at all.
        """
        s = self.snapshot()
        run = s[self.run_id]
        number = run.cycle + 1
        cycle, event = open_records(self.identity, self.run_id, number, triggers)
        advanced = replace(run, cycle=number, revision=run.revision + 1, updated_at=now())
        opened, admitted = False, []
        for trigger in triggers:
            s = self.snapshot()
            propagation = s.get(trigger.propagation_id)
            if not isinstance(propagation, Propagation):
                continue
            reason = admissible_follow_up(propagation, trigger.task_kind, s, self.run_id)
            if reason is not None:
                self.commit(events=[self.event(EventType.PROPAGATION_SKIPPED, reason=reason,
                                               propagation_id=propagation.id,
                                               task_kind=trigger.task_kind)])
                continue
            records, events = [], []
            if not opened:
                records, events = [cycle, advanced], [event, self.event(EventType.RECORD_CHANGED, advanced)]
                opened = True
                s = dict(s, **{cycle.id: cycle, advanced.id: advanced})
            task = follow_up_task(propagation, trigger.task_kind, self.identity, self.run_id, s,
                                  self.propagation_policy)
            linked = link_task(propagation, task, trigger.task_kind)
            self.commit(records + [task, linked], events + [
                self.event(EventType.TASK_CREATED, task, task_kind=task.kind, cycle=number,
                           source_propagation_id=propagation.id, trigger=trigger.kind),
                self.event(EventType.RECONSIDERATION_STARTED, linked, task_id=task.id,
                           trigger=trigger.kind, cycle=number)])
            admitted.append(task.id)
        if admitted:
            current = self.snapshot()[cycle.id]
            recorded = replace(current, task_ids=current.task_ids + tuple(admitted),
                               revision=current.revision + 1)
            self.commit([recorded], [self.event(EventType.RECORD_CHANGED, recorded)])
        return bool(admitted)

    def open_repair_cycle(self, tasks, trigger, reason, extra_events=()):
        """Charge one wave for controller-authored repair work and commit it with the cycle.

        Repair is exploration under another name, so it opens a wave by the same rule: the
        counter moves because executable work was admitted, never because a review asked.
        """
        if not tasks:
            return False
        if open_cycle(self.snapshot(), self.run_id) is not None:
            # The wave that produced the reviewed result is over; measure and close it
            # before charging another, so a run never holds two open waves.
            self._close_cycle()
        s = self.snapshot()
        run = s[self.run_id]
        number = run.cycle + 1
        cycle = replace(open_records(self.identity, self.run_id, number, ())[0],
                        trigger=trigger, reason=reason, task_ids=tuple(t.id for t in tasks))
        advanced = replace(run, cycle=number, revision=run.revision + 1, updated_at=now())
        events = [self.event(EventType.CYCLE_STARTED, cycle, number=number, trigger=trigger,
                             reason=reason, task_ids=[t.id for t in tasks]),
                  self.event(EventType.RECORD_CHANGED, advanced)]
        events += [self.event(EventType.TASK_CREATED, t, task_kind=t.kind, cycle=number,
                              trigger=trigger) for t in tasks]
        self.commit([cycle, advanced, *tasks], events + list(extra_events))
        return True

    def _advance_cycle(self):
        """Close the settled wave; open another only when bounded work is actually admissible."""
        s = self.snapshot()
        run = s[self.run_id]
        if stopped(run) or remaining_seconds(run) <= 0:
            return False
        triggers = cycle_triggers(s, self.run_id)
        exhausted = run.cycle >= run.cycle_limit
        admissible = tuple(t for t in triggers if isinstance(s.get(t.propagation_id), Propagation)
                           and admissible_follow_up(s[t.propagation_id], t.task_kind, s, self.run_id) is None)
        if exhausted or not admissible:
            # Every trigger that will not become work says why, and the wave records them.
            for trigger in triggers:
                reason = 'CYCLE_LIMIT' if exhausted else admissible_follow_up(
                    s[trigger.propagation_id], trigger.task_kind, s, self.run_id)
                self.commit(events=[self.event(EventType.PROPAGATION_SKIPPED, reason=reason,
                                               propagation_id=trigger.propagation_id,
                                               task_kind=trigger.task_kind, cycle=run.cycle)])
            self._close_cycle(triggers, cycle_exhausted=exhausted and bool(triggers))
            return False
        self._close_cycle()
        return self._open_cycle(admissible)

    def _final_settle(self):
        """Leave no branch silently dormant and no unresolved gap unrecorded.

        A wave is measured exactly once: when the loop already closed it, this only records
        the gaps, so no branch is charged twice for the same idle cycle. Recording the same
        unchanged gaps again says nothing, so it is skipped and the audit stays readable.
        """
        s = self.snapshot()
        if open_cycle(s, self.run_id) is None:
            gaps = coverage_gaps(s, self.run_id)
            if gaps and gaps != self._recorded_gaps:
                self._recorded_gaps = gaps
                self.commit(events=[self.event(EventType.COVERAGE_GAP, cycle=s[self.run_id].cycle,
                                               gaps=gaps, cycle_exhausted=False)])
            return
        triggers = cycle_triggers(s, self.run_id)
        self._close_cycle(triggers, cycle_exhausted=bool(triggers))

