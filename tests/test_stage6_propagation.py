"""Deterministic relevance, eligibility, idempotency and the no-broadcast guarantee.

These exercise the propagation services directly against complete snapshots, so a routing
decision is tested as the pure function it is: same input, same targets, no provider.
"""
import unittest
from dataclasses import replace
from stage6_support import Fixture, standard
from swarm.domain import (Agent, AgentGroup, Assignment, Conflict, ConflictKind, ConflictStatus,
                          Evidence, Finding, FindingStatus, GroupStatus, Propagation,
                          PropagationKind, PropagationStatus, Role, RoleName, Run, SwarmState,
                          Task, TaskStatus, validate_records)
from swarm.knowledge import project
from swarm.propagation import (MAX_INSIGHT, PropagationPolicy, delivery_key, knowledge_units,
                               plan_propagations, propagation_records, relevance, select_targets)
from swarm.roles import default_roles


class RelevanceTests(unittest.TestCase):
    def units(self, fixture):
        return knowledge_units(fixture.project(), 'r')

    def test_an_explicit_task_dependency_scores_highest(self):
        f = standard()
        f.records['tb'] = replace(f.records['tb'], dependency_ids=('ta',), revision=2)
        unit = self.units(f)[0]
        score, features = relevance(unit, f.records['tb'])
        self.assertEqual(score, 7)  # dependency 4, shared criterion 2, one shared tag 1
        self.assertIn('DEPENDENCY:ta', features)

    def test_an_explicitly_pinned_finding_also_counts_as_a_dependency(self):
        f = standard()
        f.records['tb'] = replace(f.records['tb'], candidate_finding_ids=('fa',), revision=2)
        score, features = relevance(self.units(f)[0], f.records['tb'])
        self.assertIn('DEPENDENCY:fa', features)
        self.assertEqual(score, 7)

    def test_a_shared_acceptance_criterion_alone_qualifies(self):
        f = standard()
        f.records['tb'] = replace(f.records['tb'], tags=(), revision=2)
        score, features = relevance(self.units(f)[0], f.records['tb'])
        self.assertEqual((score, features), (2, ('CRITERION:c1',)))
        self.assertTrue(select_targets(self.units(f)[0], f.project(), 'r'))

    def test_one_shared_tag_is_below_the_threshold_and_two_reach_it(self):
        f = standard()
        f.records['tb'] = replace(f.records['tb'], acceptance_criterion_ids=(), tags=('sums',), revision=2)
        unit = self.units(f)[0]
        self.assertEqual(relevance(unit, f.records['tb'])[0], 1)
        self.assertEqual(select_targets(unit, f.project(), 'r'), ())
        f.records['fa'] = replace(f.records['fa'], tags=('sums', 'integers'), revision=2)
        f.records['tb'] = replace(f.records['tb'], tags=('sums', 'integers'), revision=3)
        self.assertEqual(relevance(self.units(f)[0], f.records['tb'])[0], 2)
        self.assertTrue(select_targets(self.units(f)[0], f.project(), 'r'))

    def test_tag_score_is_capped_so_tags_cannot_outweigh_a_dependency(self):
        f = standard()
        many = ('t1', 't2', 't3', 't4', 't5')
        f.records['fa'] = replace(f.records['fa'], tags=many, revision=2)
        f.records['tb'] = replace(f.records['tb'], acceptance_criterion_ids=(), tags=many, revision=2)
        score, features = relevance(self.units(f)[0], f.records['tb'])
        self.assertEqual(score, 2)
        self.assertEqual(features, ('TAG:t1,t2',))

    def test_an_unrelated_target_is_excluded(self):
        f = standard()
        f.records['tb'] = replace(f.records['tb'], acceptance_criterion_ids=(), tags=('unrelated',),
                                  revision=2)
        self.assertEqual(select_targets(self.units(f)[0], f.project(), 'r'), ())

    def test_a_closed_branch_and_a_terminal_task_are_never_targets(self):
        f = standard()
        f.records['gb'] = replace(f.records['gb'], status=GroupStatus.CLOSED,
                                  stop_reason='NO_PROGRESS', revision=2)
        self.assertEqual(select_targets(self.units(f)[0], f.project(), 'r'), ())
        f.records['gb'] = replace(f.records['gb'], status=GroupStatus.ACTIVE, stop_reason=None, revision=3)
        f.records['tb'] = replace(f.records['tb'], status=TaskStatus.CANCELLED, revision=2)
        self.assertEqual(select_targets(self.units(f)[0], f.project(), 'r'), ())

    def test_a_same_branch_target_needs_an_explicit_dependency(self):
        """Cross-pollination crosses branches; local routing needs a declared link."""
        f = standard()
        f.task('ta2', group_id='ga', tags=('sums',))
        f.records['tb'] = replace(f.records['tb'], acceptance_criterion_ids=(), tags=(), revision=2)
        self.assertEqual(select_targets(self.units(f)[0], f.project(), 'r'), ())
        f.records['ta2'] = replace(f.records['ta2'], dependency_ids=('ta',), revision=2)
        targets = select_targets(self.units(f)[0], f.project(), 'r')
        self.assertEqual([d.target_task_id for d in targets], ['ta2'])

    def test_a_review_task_is_never_a_propagation_target(self):
        f = standard()
        f.task('review', kind='criticism', target_finding_id='fa', tags=('sums',))
        targets = select_targets(self.units(f)[0], f.project(), 'r')
        self.assertNotIn('review', [d.target_task_id for d in targets])


class TargetSelectionTests(unittest.TestCase):
    def wide(self):
        """Five equally relevant open tasks in their own branches."""
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fa', 'ta', 'sum([1, 2]) = 3')
        for index in range(5):
            f.group(f'g{index}', f'w{index}')
            f.task(f't{index}', group_id=f'g{index}', priority=index)
        return f

    def test_the_target_cap_bounds_fanout(self):
        f = self.wide()
        targets = select_targets(knowledge_units(f.project(), 'r')[0], f.project(), 'r')
        self.assertEqual(len(targets), 3)

    def test_sorting_is_score_then_priority_then_stable_id(self):
        f = self.wide()
        targets = select_targets(knowledge_units(f.project(), 'r')[0], f.project(), 'r')
        # All score 2, so the highest priority wins and ties break on the task id.
        self.assertEqual([d.target_task_id for d in targets], ['t4', 't3', 't2'])
        f.records['t0'] = replace(f.records['t0'], dependency_ids=('ta',), revision=2)
        again = select_targets(knowledge_units(f.project(), 'r')[0], f.project(), 'r')
        self.assertEqual(again[0].target_task_id, 't0')
        self.assertEqual(again[0].score, 6)

    def test_selection_is_deterministic_across_insertion_orders(self):
        first = select_targets(knowledge_units(self.wide().project(), 'r')[0],
                               self.wide().project(), 'r')
        shuffled = self.wide()
        shuffled.records = dict(reversed(list(shuffled.records.items())))
        second = select_targets(knowledge_units(shuffled.project(), 'r')[0], shuffled.project(), 'r')
        self.assertEqual([d.target_task_id for d in first], [d.target_task_id for d in second])
        self.assertEqual([d.delivery_key for d in first], [d.delivery_key for d in second])

    def test_a_policy_change_replaces_routing_without_touching_the_record(self):
        f = self.wide()
        policy = PropagationPolicy(max_targets=1, min_score=3)
        self.assertEqual(select_targets(knowledge_units(f.project(), 'r')[0], f.project(), 'r', policy), ())
        f.records['t0'] = replace(f.records['t0'], dependency_ids=('ta',), revision=2)
        targets = select_targets(knowledge_units(f.project(), 'r')[0], f.project(), 'r', policy)
        self.assertEqual([d.target_task_id for d in targets], ['t0'])


class EligibilityTests(unittest.TestCase):
    def test_only_validated_projected_knowledge_is_eligible(self):
        for status in (FindingStatus.PROPOSED, FindingStatus.CRITIQUED, FindingStatus.REJECTED,
                       FindingStatus.INVALIDATED):
            f = standard()
            f.records['fa'] = replace(f.records['fa'], status=status, revision=2)
            self.assertEqual(knowledge_units(f.project(), 'r'), (), f'{status} must not propagate')

    def test_a_validated_claim_resting_on_unvalidated_support_is_not_eligible(self):
        f = standard()
        f.task('tdep', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fdep', 'tdep', 'sum([9]) = 9', status=FindingStatus.CRITIQUED)
        f.records['fa'] = replace(f.records['fa'], dependency_finding_ids=('fdep',), revision=2)
        self.assertEqual(knowledge_units(f.project(), 'r'), ())

    def test_a_duplicate_group_offers_exactly_one_unit_carrying_every_source(self):
        f = standard()
        f.task('tc', group_id='gb', status=TaskStatus.COMPLETED)
        f.finding('fc', 'tc', 'SUM([1, 2])  =  3')  # same claim, same evidence, other branch
        units = knowledge_units(f.project(), 'r')
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].member_ids, ('fa', 'fc'))
        self.assertEqual(units[0].canonical_id, 'fa')

    def test_the_insight_is_bounded_and_carries_no_evidence(self):
        f = standard()
        f.records['fa'] = replace(f.records['fa'], claim='sum([1, 2]) = 3 ' + 'x' * 2000, revision=2)
        unit = knowledge_units(f.project(), 'r')[0]
        self.assertLessEqual(len(unit.insight), MAX_INSIGHT)
        self.assertNotIn('tool_result', unit.insight)
        self.assertNotIn('ref-', unit.insight)


class ConflictPropagationTests(unittest.TestCase):
    def contested(self):
        f = Fixture()
        f.group('ga', 'a')
        f.group('gb', 'b')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.task('tb', group_id='gb', status=TaskStatus.COMPLETED)
        f.task('tc', group_id='gb')
        f.finding('left', 'ta', 'sum([7, 1]) = 8', numbers=(7, 1), total=8)
        f.finding('right', 'tb', 'sum([6, 2]) = 8', numbers=(6, 2), total=8)
        f.add(Conflict(id='k1', run_id='r', finding_ids=('left', 'right'), finding_revisions=(1, 1),
                       kind=ConflictKind.DECLARED_CONTRADICTION, signature='sig-1',
                       reason='left declares a contradiction with right', criterion_ids=('c1',)))
        return f

    def test_a_contested_claim_never_propagates_as_uncontested_knowledge(self):
        units = knowledge_units(self.contested().project(), 'r')
        self.assertEqual([u.kind for u in units], [PropagationKind.CONFLICT])
        self.assertEqual(units[0].member_ids, ('left', 'right'))

    def test_the_conflict_propagation_names_both_sides_and_the_contradiction(self):
        unit = knowledge_units(self.contested().project(), 'r')[0]
        self.assertIn('OPEN CONFLICT k1', unit.insight)
        self.assertIn('sum([7, 1]) = 8', unit.insight)
        self.assertIn('sum([6, 2]) = 8', unit.insight)
        self.assertEqual(unit.conflict_id, 'k1')

    def test_resolving_the_conflict_returns_both_sides_to_ordinary_propagation(self):
        f = self.contested()
        f.records['k1'] = replace(f.records['k1'], status=ConflictStatus.RESOLVED,
                                  resolution='FIXTURE', resolved_at='2026-09-09T00:00:00+00:00',
                                  revision=2)
        units = knowledge_units(f.project(), 'r')
        self.assertEqual({u.kind for u in units}, {PropagationKind.INSIGHT})
        self.assertEqual(sorted(u.canonical_id for u in units), ['left', 'right'])


class IdempotencyTests(unittest.TestCase):
    def planned(self, fixture):
        return plan_propagations(fixture.project(), 'r')

    def test_the_same_knowledge_revision_is_planned_once_per_target(self):
        f = standard()
        plans = self.planned(f)
        self.assertEqual([(d.target_task_id, d.score) for d in plans], [('tb', 3)])
        records, _ = propagation_records(plans, lambda kind: 'p1', 'r', 1, 1)
        for record in records:
            f.records[record.id] = record
        self.assertEqual(self.planned(f), ())

    def test_a_new_knowledge_revision_may_propagate_to_the_same_target_again(self):
        f = standard()
        records, _ = propagation_records(self.planned(f), lambda kind: 'p1', 'r', 1, 1)
        f.records['p1'] = records[0]
        f.records['fa'] = replace(f.records['fa'], revision=2)
        plans = self.planned(f)
        self.assertEqual(len(plans), 1)
        self.assertNotEqual(plans[0].delivery_key, records[0].delivery_key)

    def test_duplicate_findings_do_not_cause_a_second_delivery(self):
        f = standard()
        f.task('tc', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fc', 'tc', 'sum([1, 2]) = 3')
        plans = self.planned(f)
        self.assertEqual(len(plans), 1)
        # Which member is canonical does not change the fact's identity or its delivery key.
        rotated = standard()
        rotated.task('tc', group_id='ga', status=TaskStatus.COMPLETED)
        rotated.finding('aaa', 'tc', 'sum([1, 2]) = 3')
        self.assertEqual(self.planned(rotated)[0].delivery_key, plans[0].delivery_key)

    def test_the_delivery_key_is_content_addressed_over_the_decision(self):
        base = delivery_key(PropagationKind.INSIGHT, 'k', 3, 'tb')
        self.assertEqual(base, delivery_key(PropagationKind.INSIGHT, 'k', 3, 'tb'))
        for other in (delivery_key(PropagationKind.RETRACTION, 'k', 3, 'tb'),
                      delivery_key(PropagationKind.INSIGHT, 'k2', 3, 'tb'),
                      delivery_key(PropagationKind.INSIGHT, 'k', 4, 'tb'),
                      delivery_key(PropagationKind.INSIGHT, 'k', 3, 'tc')):
            self.assertNotEqual(base, other)

    def test_a_duplicate_delivery_key_cannot_be_stored_at_all(self):
        """Idempotency is a snapshot invariant, not a best-effort query."""
        f = standard()
        records, _ = propagation_records(self.planned(f), lambda kind: 'p1', 'r', 1, 1)
        twin = replace(records[0], id='p2')
        f.records['p1'], f.records['p2'] = records[0], twin
        with self.assertRaises(Exception) as caught:
            validate_records(f.project().values())
        self.assertIn('duplicate propagation delivery key', str(caught.exception))


class NoBroadcastTests(unittest.TestCase):
    def test_a_plan_names_finite_targets_and_never_a_broadcast_address(self):
        f = Fixture()
        f.group('ga', 'a')
        f.task('ta', group_id='ga', status=TaskStatus.COMPLETED)
        f.finding('fa', 'ta', 'sum([1, 2]) = 3')
        for index in range(8):
            f.group(f'g{index}', f'w{index}')
            f.task(f't{index}', group_id=f'g{index}')
        plans = plan_propagations(f.project(), 'r')
        self.assertEqual(len(plans), 3)
        self.assertTrue(all(isinstance(d.target_task_id, str) and d.target_task_id in f.records
                            for d in plans))
        records, events = propagation_records(plans, lambda kind: f'p{len(f.records)}', 'r', 1, 1)
        self.assertTrue(all(isinstance(r, Propagation) and r.status == PropagationStatus.SELECTED
                            for r in records))

    def test_a_stopped_run_plans_nothing(self):
        f = standard()
        f.records['r'] = replace(f.records['r'], work_stop_reason='CANCELLED', revision=2)
        self.assertEqual(plan_propagations(f.project(), 'r'), ())


if __name__ == '__main__':
    unittest.main()
