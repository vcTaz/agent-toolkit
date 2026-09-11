"""Strict untrusted-output boundary. Drafts have no authoritative state fields."""
import json
import math
from dataclasses import dataclass
from .contracts import ToolResult


@dataclass(frozen=True)
class FindingDraft:
    claim: str
    reasoning_summary: str = ''
    evidence_ids: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True)
class MessageDraft:
    recipient: str
    summary: str
    kind: str = 'INSIGHT'
    reference_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskDraft:
    objective: str
    description: str = ''
    parent_task_id: str | None = None
    dependency_ids: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewDraft:
    """Adversarial examination or verification of one exact finding revision.

    A draft never carries a verification verdict: ``verified`` evidence is host-only.
    """
    target_id: str
    target_revision: int
    decision: str
    summary: str
    evidence_ids: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    nonblocking_issues: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    resolved_issues: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    """Criteria a final review says the result fails to cover. Locates the defect; the
    controller still decides from state whether knowledge or presentation must change."""
    unsupported_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconsiderationDraft:
    """A branch's answer to one delivered discovery. It names the delivery, never invents it,
    and cannot report the host-only ``UNREPORTED`` outcome."""
    propagation_id: str
    outcome: str
    reason: str


@dataclass(frozen=True)
class ResultClaimDraft:
    """One material claim and the validated findings the synthesizer says carry it."""
    claim: str
    finding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultDraft:
    """A proposed answer. It carries no version, no status and no completion authority."""
    answer: str
    finding_ids: tuple[str, ...] = ()
    criterion_ids: tuple[str, ...] = ()
    claims: tuple[ResultClaimDraft, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    summary: str
    findings: tuple[FindingDraft, ...] = ()
    messages: tuple[MessageDraft, ...] = ()
    task_requests: tuple[TaskDraft, ...] = ()
    reconsiderations: tuple[ReconsiderationDraft, ...] = ()
    review: ReviewDraft | None = None
    result: ResultDraft | None = None
    confidence: float | None = None
    assignment_id: str = ''
    tool_results: tuple[ToolResult, ...] = ()


OUTPUT_CONTRACT = json.dumps({
    'required': ['status', 'summary'],
    'status': ['SUCCEEDED', 'NEEDS_INPUT', 'FAILED'],
    'optional': {'findings': [{'claim': 'string', 'reasoning_summary': 'string?',
                              'evidence_ids': ['host tool result ID'], 'confidence': '0..1?'}],
                 'messages': [{'recipient': 'agent:id|group:id|orchestrator', 'summary': 'string'}],
                 'task_requests': [{'objective': 'string', 'description': 'string?'}],
                 'reconsiderations': [{'propagation_id': 'delivered propagation ID',
                                       'outcome': 'APPLIED|NO_CHANGE|FOLLOW_UP_REQUESTED',
                                       'reason': 'string'}],
                 'review': {'target_id': 'string', 'target_revision': 'positive integer',
                            'decision': 'criticism: PASS|CHALLENGE|INCONCLUSIVE; '
                                        'validation: PASS|FAIL|INCONCLUSIVE',
                            'summary': 'string', 'evidence_ids': ['host tool result ID'],
                            'blocking_issues': ['string'], 'nonblocking_issues': ['string'],
                            'checks': ['string'], 'resolved_issues': ['blocking issue key']},
                 'result': {'answer': 'string', 'finding_ids': ['finding ID']},
                 'confidence': '0..1?'},
    'additional_fields': False,
})


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite number')
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)


def obj(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('invalid object fields')
    return value


def text(value, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid bounded text')
    return value


def array(value, limit=16):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('invalid bounded array')
    return value


def confidence(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value <= 1 or (type(value) is float and not math.isfinite(value)):
        raise ValueError('confidence must be finite and within [0,1]')
    return float(value)


def parse_output(payload: str, role, tool_results: tuple[ToolResult, ...]) -> ExecutionResult:
    if not isinstance(payload, str) or len(payload) > 16000:
        raise ValueError('invalid output size/type')
    data = obj(strict_json(payload), {'status', 'summary', 'confidence', *role.output_fields},
               ('status', 'summary'))
    if data['status'] not in ('SUCCEEDED', 'NEEDS_INPUT', 'FAILED'):
        raise ValueError('invalid execution status')
    known = {r.id for r in tool_results if r.success}
    def evidence(value):
        ids = tuple(text(v, 128) for v in array(value))
        if not set(ids) <= known:
            raise ValueError('model cannot manufacture tool evidence')
        return ids
    findings = []
    for item in array(data.get('findings', [])):
        obj(item, ('claim', 'reasoning_summary', 'evidence_ids', 'confidence'), ('claim',))
        findings.append(FindingDraft(text(item['claim']),
                                     text(item['reasoning_summary']) if 'reasoning_summary' in item else '',
                                     evidence(item.get('evidence_ids', [])), confidence(item.get('confidence'))))
    messages = []
    for item in array(data.get('messages', [])):
        obj(item, ('recipient', 'summary', 'kind', 'reference_ids'), ('recipient', 'summary'))
        recipient = text(item['recipient'], 128)
        if recipient != 'orchestrator' and not any(recipient.startswith(p) and recipient[len(p):]
                                                   for p in ('agent:', 'group:')):
            raise ValueError('invalid targeted recipient')
        messages.append(MessageDraft(recipient, text(item['summary']), text(item.get('kind', 'INSIGHT'), 32),
                                     tuple(text(v, 128) for v in array(item.get('reference_ids', [])))))
    tasks = []
    for item in array(data.get('task_requests', []), 8):
        obj(item, ('objective', 'description', 'parent_task_id', 'dependency_ids', 'criterion_ids'), ('objective',))
        tasks.append(TaskDraft(text(item['objective']), text(item['description']) if 'description' in item else '',
                               text(item['parent_task_id'], 128) if item.get('parent_task_id') is not None else None,
                               tuple(text(v, 128) for v in array(item.get('dependency_ids', []))),
                               tuple(text(v, 128) for v in array(item.get('criterion_ids', [])))))
    reconsiderations = []
    for item in array(data.get('reconsiderations', []), 8):
        obj(item, ('propagation_id', 'outcome', 'reason'), ('propagation_id', 'outcome', 'reason'))
        if item['outcome'] not in ('APPLIED', 'NO_CHANGE', 'FOLLOW_UP_REQUESTED'):
            raise ValueError('invalid reconsideration outcome')
        reconsiderations.append(ReconsiderationDraft(text(item['propagation_id'], 128),
                                                     item['outcome'], text(item['reason'], 1000)))
    if len({r.propagation_id for r in reconsiderations}) != len(reconsiderations):
        raise ValueError('one reconsideration per propagation')
    review = None
    if data.get('review') is not None:
        item = obj(data['review'], ('target_id', 'target_revision', 'decision', 'summary', 'evidence_ids',
                                    'blocking_issues', 'nonblocking_issues', 'checks', 'resolved_issues',
                                    'criterion_ids', 'unsupported_claims'),
                   ('target_id', 'target_revision', 'decision', 'summary'))
        if type(item['target_revision']) is not int or item['target_revision'] < 1:
            raise ValueError('invalid review revision')
        if item['decision'] not in ('PASS', 'CHALLENGE', 'FAIL', 'INCONCLUSIVE', 'REVISE', 'REJECT'):
            raise ValueError('invalid review decision')
        issues = {name: tuple(text(v, 1000) for v in array(item.get(name, []), 12))
                  for name in ('blocking_issues', 'nonblocking_issues', 'checks', 'resolved_issues',
                               'unsupported_claims')}
        review = ReviewDraft(text(item['target_id'], 128), item['target_revision'], item['decision'],
                             text(item['summary']), evidence(item.get('evidence_ids', [])),
                             criterion_ids=tuple(text(v, 128) for v in array(item.get('criterion_ids', []), 12)),
                             **issues)
    result = None
    if data.get('result') is not None:
        item = obj(data['result'], ('answer', 'finding_ids', 'criterion_ids', 'claims', 'limitations'),
                   ('answer',))
        claims = []
        for entry in array(item.get('claims', []), 24):
            obj(entry, ('claim', 'finding_ids'), ('claim',))
            claims.append(ResultClaimDraft(text(entry['claim'], 1000),
                                           tuple(text(v, 128) for v in array(entry.get('finding_ids', [])))))
        result = ResultDraft(text(item['answer'], 8000),
                             tuple(text(v, 128) for v in array(item.get('finding_ids', []), 32)),
                             tuple(text(v, 128) for v in array(item.get('criterion_ids', []), 32)),
                             tuple(claims),
                             tuple(text(v, 1000) for v in array(item.get('limitations', []), 12)))
    return ExecutionResult(data['status'], text(data['summary']), tuple(findings), tuple(messages),
                           tuple(tasks), tuple(reconsiderations), review, result,
                           confidence(data.get('confidence')))
