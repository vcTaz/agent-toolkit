"""Targeted messages and immutable group delivery snapshots; no broadcast/history fan-out."""
from dataclasses import replace
from .domain import Agent, Message, Role, AgentGroup, GroupStatus, MessageStatus, RunRecord, transition
from .scope import UNRESOLVED, owning_group

KINDS = frozenset(('INSIGHT', 'QUESTION', 'STATUS', 'SYSTEM'))


def route_message(message, snapshot):
    """Return a delivered successor or an explicit rejection reason. Does not commit."""
    run = snapshot.get(message.run_id)
    if run is None or message.status != MessageStatus.QUEUED:
        return None, 'INVALID_RUN_OR_MESSAGE_STATE'
    if message.kind not in KINDS or not message.summary.strip() or len(message.summary) > 4000:
        return None, 'INVALID_MESSAGE_PAYLOAD'
    sender = None
    if message.sender not in ('system', 'orchestrator'):
        prefix, _, identity = message.sender.partition(':')
        sender = snapshot.get(identity)
        if prefix != 'agent' or not isinstance(sender, Agent) or sender.run_id != message.run_id:
            return None, 'INVALID_SENDER'
        if message.kind == 'SYSTEM':
            return None, 'SYSTEM_KIND_FORBIDDEN'
    references = []
    for identity in message.reference_ids:
        record = snapshot.get(identity)
        if not isinstance(record, RunRecord) or record.run_id != message.run_id:
            return None, 'INVALID_MESSAGE_REFERENCE'
        references.append(record)
    if message.recipient == 'orchestrator':
        targets = ('orchestrator',)
        target_group = None
    else:
        prefix, _, identity = message.recipient.partition(':')
        recipient = snapshot.get(identity)
        if prefix == 'agent' and isinstance(recipient, Agent) and recipient.run_id == message.run_id:
            targets, target_group = (recipient.id,), recipient.group_id
        elif prefix == 'group' and isinstance(recipient, AgentGroup) and recipient.run_id == message.run_id:
            targets, target_group = tuple(sorted(recipient.agent_ids)), recipient.id
        else:
            return None, 'UNKNOWN_RECIPIENT'
        if target_group:
            group = snapshot.get(target_group)
            if not isinstance(group, AgentGroup) or (group.status == GroupStatus.CLOSED and message.kind != 'SYSTEM'):
                return None, 'GROUP_CLOSED'
    if sender is not None and message.recipient != 'orchestrator':
        role = snapshot.get(sender.role_id)
        if not isinstance(role, Role) or role.communication_scope not in ('group', 'run'):
            return None, 'COMMUNICATION_FORBIDDEN'
        if role.communication_scope == 'group' and (sender.group_id is None or sender.group_id != target_group):
            return None, 'OUTSIDE_GROUP'
        membership = snapshot.get(sender.group_id) if sender.group_id else None
        if sender.group_id and (not isinstance(membership, AgentGroup) or sender.id not in membership.agent_ids):
            return None, 'SENDER_NOT_MEMBER'
    if any(identity != 'orchestrator' and (not isinstance(snapshot.get(identity), Agent)
           or snapshot[identity].run_id != message.run_id) for identity in targets):
        return None, 'INVALID_MEMBERSHIP'
    # The orchestrator already owns every record; agents and groups do not.
    if message.recipient != 'orchestrator':
        for record in references:
            group = owning_group(record, snapshot)
            if group is UNRESOLVED or (group is not None and group != target_group):
                return None, 'REFERENCE_OUT_OF_SCOPE'
            if isinstance(record, Message) and not set(targets) <= set(record.delivered_to):
                return None, 'REFERENCE_NOT_DELIVERED'
    delivered = transition(message, MessageStatus.DELIVERED)
    return replace(delivered, delivered_to=targets, delivery_revision=delivered.revision), None


def unread_messages(snapshot, agent_id):
    return tuple(sorted((m for m in snapshot.values() if hasattr(m, 'delivered_to')
                         and m.status == MessageStatus.DELIVERED and agent_id in m.delivered_to
                         and agent_id not in m.read_by), key=lambda m: (m.created_at, m.id)))
