"""Host-controlled evidence verification.

Nothing here asks a model whether evidence "sounds supportive". A policy is explicit and
verifier-kind specific: it reads the authoritative, host-recorded tool result and decides
whether that result *entails the exact claim*. A successful tool call is not a verified
claim, and an unsupported claim form is INCONCLUSIVE rather than guessed.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Protocol
from .domain import Criterion, Evidence, Finding

PASS, FAIL, INCONCLUSIVE = 'PASS', 'FAIL', 'INCONCLUSIVE'

_SUM_CLAIM = re.compile(r'^sum\(\[(-?\d+(?:,-?\d+)*)?\]\)=(-?\d+)$')


def parse_sum_claim(claim: str):
    """Return ``(numbers, total)`` for the one supported arithmetic claim form.

    The supported syntax is ``sum([a, b, c]) = t``; whitespace is insignificant.
    Anything else returns ``None`` so the caller reports INCONCLUSIVE instead of guessing.
    """
    match = _SUM_CLAIM.match(''.join(str(claim).split()))
    if match is None:
        return None
    numbers = tuple(int(part) for part in match.group(1).split(',')) if match.group(1) else ()
    return numbers, int(match.group(2))


def structured_sum_value(finding: Finding):
    """Deterministic (property, value) pair used for conflict detection, or None."""
    parsed = parse_sum_claim(finding.claim)
    return (f'sum:{sorted(parsed[0])}', parsed[1]) if parsed else None


@dataclass(frozen=True)
class VerificationDecision:
    decision: str
    reason: str = ''
    evidence: tuple[Evidence, ...] = ()
    """Host-authored evidence. This is the only path by which ``verified=True`` exists."""


class VerificationPolicy(Protocol):
    verifier_kind: str

    def verify(self, finding: Finding, evidence: tuple[Evidence, ...], criterion: Criterion,
               tool_results: tuple[Evidence, ...], snapshot) -> VerificationDecision: ...


def _tool_evidence(entries, name):
    for item in entries:
        if item.kind != 'tool_result' or item.tool_name != name or not item.reference:
            continue
        try:
            yield item, json.loads(item.arguments_json), json.loads(item.value)
        except (ValueError, TypeError):
            continue


@dataclass(frozen=True)
class ArithmeticVerification:
    """Entailment for integer-sum claims backed by the trusted arithmetic tool.

    The recorded arguments must be the claim's own operands and asserted total, and the
    recorded output must state that they match. A result computed over other numbers
    proves nothing about this claim no matter how successfully it executed.
    """
    verifier_kind: str = 'arithmetic'
    tool_name: str = 'arithmetic'

    def verify(self, finding, evidence, criterion, tool_results, snapshot):
        parsed = parse_sum_claim(finding.claim)
        if parsed is None:
            return VerificationDecision(INCONCLUSIVE, 'UNSUPPORTED_CLAIM_FORM')
        numbers, total = parsed
        supporting, contradicting = [], False
        for item, arguments, value in _tool_evidence(tuple(evidence) + tuple(tool_results), self.tool_name):
            if not isinstance(arguments, dict) or not isinstance(value, dict):
                continue
            if sorted(arguments.get('numbers', ())) != sorted(numbers):
                continue  # a sum over other operands says nothing about this claim
            if value.get('actual') != arguments.get('expected'):
                contradicting = True
                continue
            if arguments.get('expected') != total or value.get('matches') is not True:
                contradicting = True
                continue
            supporting.append(item)
        if contradicting:
            return VerificationDecision(FAIL, 'TOOL_RESULT_CONTRADICTS_CLAIM')
        if not supporting:
            return VerificationDecision(INCONCLUSIVE, 'NO_ENTAILING_TOOL_RESULT')
        return VerificationDecision(PASS, 'TOOL_RESULT_ENTAILS_CLAIM', tuple(
            Evidence(kind='tool_result', value=item.value, reference=item.reference, verified=True,
                     tool_name=item.tool_name, arguments_json=item.arguments_json)
            for item in sorted(supporting, key=lambda e: e.reference)))


@dataclass(frozen=True)
class VerificationRegistry:
    """Dispatch by the criterion's declared verifier kind; unknown kinds fail closed."""
    policies: tuple[VerificationPolicy, ...] = field(default_factory=lambda: (ArithmeticVerification(),))

    def verify(self, finding, snapshot, tool_results=()):
        run = snapshot.get(finding.run_id)
        criteria = {c.id: c for c in run.acceptance_criteria} if run is not None else {}
        if not finding.criterion_ids:
            return VerificationDecision(INCONCLUSIVE, 'NO_CRITERION')
        if not set(finding.criterion_ids) <= criteria.keys():
            return VerificationDecision(INCONCLUSIVE, 'UNKNOWN_CRITERION')
        by_kind = {p.verifier_kind: p for p in self.policies}
        outcomes, evidence = [], []
        for identity in sorted(finding.criterion_ids):
            criterion = criteria[identity]
            policy = by_kind.get(criterion.verifier_kind)
            if policy is None:
                outcomes.append((INCONCLUSIVE, f'{identity}:UNSUPPORTED_VERIFIER_KIND'))
                continue
            decision = policy.verify(finding, finding.evidence, criterion, tuple(tool_results), snapshot)
            outcomes.append((decision.decision, f'{identity}:{decision.reason}'))
            evidence.extend(decision.evidence)
        reason = ' '.join(text for _, text in outcomes)
        if any(decision == FAIL for decision, _ in outcomes):
            return VerificationDecision(FAIL, reason)
        if any(decision != PASS for decision, _ in outcomes):
            return VerificationDecision(INCONCLUSIVE, reason)
        seen, unique = set(), []
        for item in evidence:
            if item.reference not in seen:
                seen.add(item.reference)
                unique.append(item)
        return VerificationDecision(PASS, reason, tuple(unique))
