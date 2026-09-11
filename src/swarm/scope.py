"""Disclosure boundaries: which records a group, task or delivery may legitimately see.

Membership permits selection; it never authorizes automatic injection of every record.
Classification fails closed: a record this module cannot place is never disclosable.
"""
from .domain import (Agent, AgentGroup, Assignment, Conflict, Cycle, Finding, Message, Propagation,
                     ReviewRecord, Role, Run, SwarmState, Task, TaskRequest)

UNRESOLVED = object()
"""A record whose owning scope cannot be established; never disclosable."""

RUN_SCOPED = (Run, Role, SwarmState, Message, Cycle)
"""Configuration and run-wide projections belong to no single branch.

Message disclosure is governed by its delivery snapshot instead, which callers check.
"""


def owning_group(record, snapshot):
    """Return the group that owns a record, None when run-scoped, UNRESOLVED when unknown."""
    if isinstance(record, AgentGroup):
        return record.id
    if isinstance(record, (Task, Agent, Assignment)):
        return record.group_id
    if isinstance(record, Finding):
        return _via(record.task_id, Task, snapshot)
    if isinstance(record, ReviewRecord):
        target = snapshot.get(record.target_id)
        # A review is exactly as private as the thing it reviews.
        return None if isinstance(target, Run) else (
            owning_group(target, snapshot) if isinstance(target, Finding) else UNRESOLVED)
    if isinstance(record, TaskRequest):
        return _via(record.parent_task_id, Task, snapshot)
    if isinstance(record, Propagation):
        # A delivery belongs to the branch it was routed *to*; that is the whole point of
        # cross-pollination, and it is why the payload is a bounded insight and not evidence.
        return _via(record.target_task_id, Task, snapshot)
    if isinstance(record, Conflict):
        # A conflict is as private as its participants; spanning two branches resolves to
        # neither, so it is undisclosable rather than quietly shared with one of them.
        groups = {owning_group(snapshot.get(i), snapshot) if isinstance(snapshot.get(i), Finding)
                  else UNRESOLVED for i in record.finding_ids}
        return groups.pop() if len(groups) == 1 else UNRESOLVED
    if isinstance(record, RUN_SCOPED):
        return None
    return UNRESOLVED


def _via(identity, expected, snapshot):
    owner = snapshot.get(identity)
    return owning_group(owner, snapshot) if isinstance(owner, expected) else UNRESOLVED


def visible_finding(finding, task, snapshot):
    """A finding is disclosable to a task when it comes from that task, a declared
    dependency task, or a task inside the same group branch."""
    source = snapshot.get(finding.task_id)
    if not isinstance(source, Task) or finding.run_id != task.run_id or source.run_id != task.run_id:
        return False
    return source.id == task.id or source.id in task.dependency_ids or source.group_id == task.group_id
