"""The authoritative controller: the run workflow assembled over the work engine.

``WorkController`` is the composition of four layers that were one module until Stage 7:

```text
ControllerCore   scheduling, the execution seam, admission, transactions
Circulation      cross-pollination, retraction, consolidation, cycles, branch stopping
WorkEngine       the loop that drives admitted work to quiescence
WorkController   the run state machine, the synthesis gate, synthesis, final review,
                 the repair loop and the terminal outcome
```

The invariant chain is unchanged at every layer:

```text
model / executor proposes
controller decides
repository commits
```

A model never decides that a run is complete. The synthesis gate *computes* readiness from
validated knowledge; a synthesizer proposes one candidate answer; an independent final
reviewer proposes PASS, REVISE or REJECT; and the controller re-checks the gate and the
citations against current state before COMPLETED is written — in the same transaction that
accepts the result.
"""
from dataclasses import replace
from . import completion, finalreview, synthesis, workflow
from .contracts import Budget  # noqa: F401  (re-exported for hosts configuring a run)
from .engine import WorkEngine
from .domain import (GateStatus, Result, ResultStatus, ReviewDecision, ReviewKind, ReviewRecord,
                     RevisionKind, RunState, Task, now)
from .events import EventType
from .policies import FINAL_REVIEW_KIND, remaining_seconds

REPAIR_TRIGGER = 'FINAL_REVIEW_REPAIR'


class WorkController(WorkEngine):
    """Own a run end to end: its work, its knowledge circulation and its workflow."""

    # --- run state machine ------------------------------------------------------

    def _transition(self, target, *, guard=None, reason='', records=(), events=(), **fields):
        """Take one guarded run transition, committed with whatever it implies.

        Returns the refusal when the guard does not hold; nothing is committed then, so a
        refused transition leaves the run exactly where it was and says why.
        """
        s = self.snapshot()
        changed, outcome = workflow.advance(s, self.run_id, target, guard=guard, reason=reason,
                                            **fields)
        if changed is None:
            return outcome
        self.commit([*records, changed], [*events, outcome])
        return workflow.Guard(True)

    def _fail_run(self, reason):
        return self._terminate(RunState.FAILED, reason)

    def _terminate(self, state, reason, *, result_id=None, gaps=None, records=(), events=()):
        """Enter a terminal state and write the terminal report in the same transaction.

        The wave is settled first, so the report carries the branch stops and gaps as they
        finally stood rather than as they stood one step earlier.
        """
        self._final_settle()
        s = self.snapshot()
        run = s[self.run_id]
        if run.state in workflow.TERMINAL_RUN_STATES:
            return workflow.Guard(False, f'ALREADY_{run.state}')
        if gaps is None:
            gaps = completion.gap_records(s, self.run_id)
        report = workflow.terminal_report(s, self.run_id, self.identity, state, reason,
                                          gaps=gaps, result_id=result_id)
        outcome = self._transition(state, reason=reason, records=[*records, report],
                                   events=[*events, workflow.terminal_event(report, run)],
                                   stop_reason=reason, outcome_id=report.id,
                                   **({'result_id': result_id} if result_id else {}))
        if outcome.allowed:
            self._stop(reason)
        return outcome

    def _gate(self, reason=''):
        """Evaluate the synthesis gate and record the decision with its reasons."""
        decision = completion.evaluate_gate(self.snapshot(), self.run_id)
        self.commit(events=[self.event(EventType.SYNTHESIS_GATE_EVALUATED, trigger=reason,
                                       **decision.detail())])
        return decision

    # --- phases ------------------------------------------------------------------

    def _begin(self):
        """RECEIVED → DECOMPOSING → EXPLORING. An unusable configuration is FAILED."""
        run = self.snapshot()[self.run_id]
        if run.state != RunState.RECEIVED:
            return True
        outcome = self._transition(RunState.DECOMPOSING, reason='configuration validated')
        if not outcome.allowed:
            self._fail_run(f'INVALID_CONFIGURATION: {outcome.reason}')
            return False
        outcome = self._transition(RunState.EXPLORING, reason='task graph admitted')
        if not outcome.allowed:
            self._fail_run(f'NO_ADMITTED_WORK: {outcome.reason}')
            return False
        return True

    def _advance_workflow(self):
        """One phase step at the settle point. True means the loop should run again."""
        state = self.snapshot()[self.run_id].state
        step = {RunState.EXPLORING: self._step_exploring,
                RunState.EVALUATING: self._step_evaluating,
                RunState.CONSOLIDATING: self._step_consolidating,
                RunState.SYNTHESIZING: self._step_synthesizing,
                RunState.FINAL_REVIEW: self._step_final_review}.get(state)
        return bool(step and step())

    def _step_exploring(self):
        return self._transition(RunState.EVALUATING, reason='exploration wave settled').allowed

    def _step_evaluating(self):
        return self._transition(RunState.CONSOLIDATING, reason='candidates reviewed').allowed

    def _step_consolidating(self):
        """Consolidate, admit any bounded follow-up work, then apply the gate.

        Reconsideration comes first: a branch that received a discovery answers it before
        the answer is written, so the gate reads knowledge that has already absorbed what
        the run circulated. It stays bounded — the wave limit and the follow-up
        admissibility rules are unchanged — so this can add at most the waves Stage 6
        already allowed.
        """
        self.consolidate()
        if self._advance_cycle():
            return self._transition(RunState.EXPLORING, guard=workflow.Guard(True),
                                    reason='admitted follow-up work').allowed
        gate = self._gate('CONSOLIDATING')
        if gate.status == GateStatus.READY:
            return self._enter_synthesis(gate)
        if self._repair_from_gate(gate):
            return True
        self._terminate(RunState.EXHAUSTED, self._exhaustion_reason(gate), gaps=gate.gaps)
        return False

    def _exhaustion_reason(self, gate):
        for reason in gate.reasons:
            if reason.startswith('CRITERION_'):
                return f'REQUIRED_CRITERION_UNRESOLVED: {reason}'
        run = self.snapshot()[self.run_id]
        if run.cycle >= run.cycle_limit:
            return 'CYCLE_LIMIT'
        if run.repair_rounds >= run.repair_round_limit:
            return 'REPAIR_LIMIT'
        return gate.reasons[0] if gate.reasons else 'NO_ADMISSIBLE_WORK'

    # --- synthesis ---------------------------------------------------------------

    def _enter_synthesis(self, gate, *, source_review_id=None, source_result_id=None, feedback=()):
        """Create the synthesis task and enter SYNTHESIZING in one transaction."""
        s = self.snapshot()
        guard = workflow.synthesis_dispatchable(s, self.run_id, gate)
        if not guard.allowed:
            self._terminate(RunState.EXHAUSTED, guard.reason, gaps=gate.gaps)
            return False
        repeated = synthesis.repeated_attempt(s, self.run_id, gate.support, source_review_id)
        if repeated:
            # Re-running a synthesis over the same support after the same feedback would
            # fail the same way; the run says so instead of spending its attempts on it.
            self._terminate(RunState.EXHAUSTED, f'SYNTHESIS_REPEATED_FAILURE: {repeated}',
                            gaps=gate.gaps)
            return False
        run = s[self.run_id]
        task = synthesis.synthesis_task(self.identity, self.run_id, s, gate,
                                        source_review_id=source_review_id,
                                        source_result_id=source_result_id, feedback=feedback)
        attempts = run.synthesis_attempts + 1
        outcome = self._transition(RunState.SYNTHESIZING, guard=workflow.Guard(True),
                                   reason='synthesis gate READY', records=[task],
                                   events=[self.event(EventType.TASK_CREATED, task,
                                                      task_kind=task.kind, support=list(gate.support)),
                                           synthesis.started_event(task, gate, attempts)],
                                   synthesis_attempts=attempts, candidate_result_id=None)
        if not outcome.allowed:
            self._terminate(RunState.EXHAUSTED, f'SYNTHESIS_REFUSED: {outcome.reason}', gaps=gate.gaps)
            return False
        return True

    def _step_synthesizing(self):
        """A candidate result moves to final review; a failed synthesis re-enters the gate."""
        s = self.snapshot()
        candidate = completion.current_result(s, self.run_id)
        if candidate is not None:
            return self._enter_final_review(candidate)
        self.commit(events=[self.event(EventType.SYNTHESIS_STALE, reason='NO_ADMISSIBLE_CANDIDATE',
                                       attempts=s[self.run_id].synthesis_attempts)])
        return self._transition(RunState.CONSOLIDATING, guard=workflow.Guard(True),
                                reason='synthesis produced no admissible candidate').allowed

    # --- final review -------------------------------------------------------------

    def _enter_final_review(self, candidate):
        s = self.snapshot()
        task = finalreview.final_review_task(candidate, self.identity, self.run_id, s)
        outcome = self._transition(RunState.FINAL_REVIEW, reason='candidate result admitted',
                                   records=[task],
                                   events=[self.event(EventType.TASK_CREATED, task, task_kind=task.kind,
                                                      target_result_id=candidate.id),
                                           finalreview.started_event(task, candidate)],
                                   candidate_result_id=candidate.id)
        if not outcome.allowed:
            self._terminate(RunState.EXHAUSTED, f'FINAL_REVIEW_REFUSED: {outcome.reason}')
            return False
        return True

    def _final_review_of(self, snapshot, result):
        return next((r for r in sorted((x for x in snapshot.values() if isinstance(x, ReviewRecord)
                                        and x.run_id == self.run_id and x.kind == ReviewKind.FINAL
                                        and x.target_id == result.id), key=lambda r: r.id)), None)

    def _step_final_review(self):
        """PASS, REVISE or REJECT — none of which is authority on its own."""
        s = self.snapshot()
        candidate = completion.current_result(s, self.run_id)
        if candidate is None:
            self._terminate(RunState.EXHAUSTED, 'CANDIDATE_RESULT_LOST')
            return False
        review = self._final_review_of(s, candidate)
        if review is None:
            self._terminate(RunState.EXHAUSTED, self._missing_review_reason(s, candidate))
            return False
        gate = self._gate('FINAL_REVIEW')
        if review.decision == ReviewDecision.PASS:
            return self._settle_pass(candidate, review, gate)
        verdict = finalreview.classify(review, candidate, s, self.run_id, gate)
        self.commit(events=[self.event(EventType.RESULT_REVISION_REQUESTED, result_id=candidate.id,
                                       review_id=review.id, **verdict.detail())])
        if review.decision == ReviewDecision.REVISE and verdict.revision_kind == RevisionKind.PRESENTATION:
            return self._presentation_revision(candidate, review, gate, verdict)
        return self._evidence_repair(candidate, review, gate, verdict)

    @staticmethod
    def _missing_review_reason(snapshot, candidate):
        task = next((t for t in sorted((r for r in snapshot.values() if isinstance(r, Task)
                                        and r.kind == FINAL_REVIEW_KIND
                                        and r.target_result_id == candidate.id), key=lambda t: t.id)),
                    None)
        if task is not None and task.outcome == 'NO_INDEPENDENT_REVIEWER':
            return 'NO_INDEPENDENT_FINAL_REVIEWER'
        return f'FINAL_REVIEW_UNAVAILABLE: {task.outcome if task else "NO_REVIEW_TASK"}'

    def _settle_pass(self, candidate, review, gate):
        """PASS is necessary and never sufficient: the controller re-checks current state.

        Between dispatch and this point a supporting finding may have been invalidated, a
        conflict may have opened, or coverage may have moved. The gate and the citations are
        recomputed here, so a stale PASS cannot complete the run.
        """
        s = self.snapshot()
        stale = () if review.verification == 'CURRENT' else tuple(
            review.verification.removeprefix('STALE: ').split('; '))
        blockers = finalreview.pass_blockers(candidate, s, self.run_id, gate, stale)
        if not blockers:
            self._final_settle()
            s = self.snapshot()
        if not blockers:
            accepted = finalreview.judged(candidate, ResultStatus.ACCEPTED, review, RevisionKind.NONE)
            report = workflow.terminal_report(dict(s, **{accepted.id: accepted}), self.run_id,
                                              self.identity, RunState.COMPLETED, 'FINAL_REVIEW_PASS',
                                              gaps=completion.gap_records(s, self.run_id),
                                              result_id=accepted.id)
            outcome = self._transition(RunState.COMPLETED, guard=workflow.Guard(True),
                                       reason='final review PASS and current gate valid',
                                       records=[accepted, report],
                                       events=[self.event(EventType.RECORD_CHANGED, accepted,
                                                          decision=str(review.decision)),
                                               workflow.terminal_event(report, s[self.run_id])],
                                       result_id=accepted.id, candidate_result_id=accepted.id,
                                       outcome_id=report.id, stop_reason='COMPLETED')
            if outcome.allowed:
                self._stop('COMPLETED')
                return False
        self.commit(events=[self.event(EventType.RESULT_REJECTED, result_id=candidate.id,
                                       review_id=review.id, reason='STALE_PASS',
                                       blockers=list(blockers))])
        verdict = finalreview.Verdict(ReviewDecision.REVISE, RevisionKind.EVIDENCE,
                                      ('STALE_PASS',) + blockers, stale,
                                      tuple(g for g in gate.gaps if g.required))
        return self._evidence_repair(candidate, review, gate, verdict)

    def _stale_pass_reason(self, blockers):
        return 'STALE_PASS: ' + '; '.join(blockers)

    def _presentation_revision(self, candidate, review, gate, verdict):
        """Knowledge is fine; the answer is not. Resynthesize with bounded feedback."""
        run = self.snapshot()[self.run_id]
        if run.presentation_revisions >= run.presentation_revision_limit:
            self._terminate(RunState.EXHAUSTED, 'PRESENTATION_REVISION_LIMIT', gaps=gate.gaps)
            return False
        revised = finalreview.judged(candidate, ResultStatus.REVISED, review, RevisionKind.PRESENTATION)
        outcome = self._transition(RunState.SYNTHESIZING, guard=workflow.Guard(True),
                                   reason='presentation revision', records=[revised],
                                   events=[self.event(EventType.RECORD_CHANGED, revised,
                                                      revision_kind=str(RevisionKind.PRESENTATION))],
                                   presentation_revisions=run.presentation_revisions + 1)
        if not outcome.allowed:
            self._terminate(RunState.EXHAUSTED, f'REVISION_REFUSED: {outcome.reason}', gaps=gate.gaps)
            return False
        # SYNTHESIZING was entered by the revision itself; the new task is authored here so
        # the run never sits in SYNTHESIZING with nothing to dispatch.
        s = self.snapshot()
        feedback = tuple(f'FINAL REVIEW {review.id}: {issue}' for issue in
                         (review.blocking_issues + review.nonblocking_issues
                          + tuple(f'criterion {c} is supported and must be presented'
                                  for c in review.criterion_ids)))[:8]
        task = synthesis.synthesis_task(self.identity, self.run_id, s, gate,
                                        source_review_id=review.id, source_result_id=candidate.id,
                                        feedback=feedback)
        attempts = s[self.run_id].synthesis_attempts + 1
        advanced = replace(s[self.run_id], synthesis_attempts=attempts,
                           revision=s[self.run_id].revision + 1, updated_at=now())
        self.commit([task, advanced], [self.event(EventType.TASK_CREATED, task, task_kind=task.kind,
                                                  support=list(gate.support), feedback=list(feedback)),
                                       synthesis.started_event(task, gate, attempts),
                                       self.event(EventType.RECORD_CHANGED, advanced)])
        return True

    # --- repair -------------------------------------------------------------------

    def _repair_tasks(self, gaps, review, snapshot):
        tasks, refused = [], []
        working = dict(snapshot)
        round_number = snapshot[self.run_id].repair_rounds + 1
        for gap in gaps:
            decision = completion.repair_admissible(working, self.run_id, gap,
                                                    getattr(review, 'id', None))
            if not decision.admissible:
                refused.append((gap, decision))
                continue
            task = finalreview.repair_task(gap, review, self.identity, self.run_id, working,
                                           round_number=round_number)
            working[task.id] = task
            tasks.append(task)
        return tasks, refused

    def _authorize_repair(self, gaps, review, reason):
        """Controller-authored repair work, bounded and duplicate-suppressed.

        This is not generic worker ``TaskRequest`` adoption: nothing a model proposed reaches
        it. Every task names its triggering review and result, the criterion and gap it must
        close, its round number and a suppression key.
        """
        s = self.snapshot()
        tasks, refused = self._repair_tasks(gaps, review, s)
        for gap, decision in refused:
            self.commit(events=[self.event(EventType.REPAIR_WORK_CREATED, admitted=False,
                                           criterion_id=gap.criterion_id, gap=gap.reason,
                                           review_id=getattr(review, 'id', None), **decision.detail())])
        if not tasks:
            return False
        run = s[self.run_id]
        rounds = run.repair_rounds + 1
        created = [self.event(EventType.REPAIR_WORK_CREATED, admitted=True, task_id=task.id,
                              criterion_id=task.acceptance_criterion_ids[0], repair_key=task.outcome,
                              round=rounds, review_id=task.source_review_id,
                              result_id=task.source_result_id) for task in tasks]
        if not self.open_repair_cycle(tasks, REPAIR_TRIGGER, reason, created):
            return False
        current = self.snapshot()[self.run_id]
        advanced = replace(current, repair_rounds=rounds, revision=current.revision + 1,
                           updated_at=now())
        self.commit([advanced], [self.event(EventType.RECORD_CHANGED, advanced)])
        return True

    def _repair_from_gate(self, gate):
        """Repair authorized by the gate itself, before any result exists.

        Every required gap is offered, not only the admissible ones, so a refusal is
        recorded with its reason instead of being silently absent.
        """
        required = tuple(g for g in gate.gaps if g.required)
        if not required:
            return False
        if not self._authorize_repair(required, None,
                                      'gate gaps: ' + ', '.join(g.key for g in required)):
            return False
        return self._transition(RunState.EXPLORING, guard=workflow.Guard(True),
                                reason='repair work admitted from the synthesis gate').allowed

    def _evidence_repair(self, candidate, review, gate, verdict):
        """A REVISE or REJECT that needs knowledge, not prose. Bounded, or EXHAUSTED."""
        status = (ResultStatus.REJECTED if review.decision == ReviewDecision.REJECT
                  else ResultStatus.REVISED)
        judged = finalreview.judged(candidate, status, review, verdict.revision_kind)
        self.commit([judged], [self.event(EventType.RECORD_CHANGED, judged, review_id=review.id,
                                          **verdict.detail())])
        gaps = verdict.gaps or gate.repairable
        reason = f'final review {review.id} ({review.decision}): ' + '; '.join(verdict.reasons)
        if gaps and self._authorize_repair(gaps, review, reason):
            outcome = self._transition(RunState.EXPLORING, guard=workflow.Guard(True), reason=reason,
                                       candidate_result_id=None)
            if outcome.allowed:
                return True
        self._terminate(RunState.EXHAUSTED, self._repair_refusal(review, verdict), gaps=gate.gaps)
        return False

    def _repair_refusal(self, review, verdict):
        """Why no further repair is admissible, in the run's own terms."""
        run = self.snapshot()[self.run_id]
        decision = verdict.decision
        if 'STALE_PASS' in verdict.reasons:
            return 'STALE_PASS: ' + '; '.join(r for r in verdict.reasons if r != 'STALE_PASS')
        if run.repair_rounds >= run.repair_round_limit:
            return f'REPAIR_LIMIT after {decision}'
        if run.cycle >= run.cycle_limit:
            return f'CYCLE_LIMIT after {decision}'
        if verdict.revision_kind == RevisionKind.NONE:
            return f'UNREPAIRABLE_{decision}: NO_CONFIRMED_DEFECT'
        if not verdict.gaps:
            return f'UNREPAIRABLE_{decision}: ' + '; '.join(verdict.reasons)
        return f'NO_ADMISSIBLE_REPAIR after {decision}'

    # --- loop hooks ----------------------------------------------------------------

    def _terminal_now(self, run):
        """The terminal outcome a stopped or expired run has already earned.

        A deadline is EXHAUSTED, not FAILED: the system operated correctly and simply could
        not satisfy the objective within the resources it was given.
        """
        if self._cancelled:
            return RunState.CANCELLED, run.work_stop_reason or 'CANCELLED'
        if remaining_seconds(run) <= 0:
            return RunState.EXHAUSTED, 'DEADLINE'
        return RunState.EXHAUSTED, run.work_stop_reason or 'WORK_STOPPED'

    def _terminated(self, run):
        return run.state in workflow.TERMINAL_RUN_STATES

    def _halt(self, run):
        state, reason = self._terminal_now(run)
        self._stop(run.work_stop_reason or reason)
        self._terminate(state, reason)
        return True

    def _prologue(self):
        return self._begin() if self.snapshot()[self.run_id].state == RunState.RECEIVED else True

    def _settled(self):
        return self._advance_workflow()

    def _cancelled_externally(self):
        self.cancel('CANCELLED')
        self._terminate(RunState.CANCELLED, 'CANCELLED')

    def cancel(self, reason='CANCELLED'):
        super().cancel(reason)
        if not self._running:
            self._terminate(RunState.CANCELLED, reason)

    # --- inspection ---------------------------------------------------------------

    def gate(self):
        """The current synthesis-gate decision, computed without committing anything."""
        return completion.evaluate_gate(self.snapshot(), self.run_id)

    def result(self):
        """The accepted result version, or the live candidate, or None."""
        s = self.snapshot()
        run = s[self.run_id]
        identity = run.result_id or run.candidate_result_id
        record = s.get(identity) if identity else None
        return record if isinstance(record, Result) else completion.current_result(s, self.run_id)

    def outcome(self):
        run = self.snapshot()[self.run_id]
        return self.snapshot().get(run.outcome_id) if run.outcome_id else None
