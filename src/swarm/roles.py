"""Data-driven role configuration. Roles are capabilities a run assigns, not job titles.

The output-field allowlist is a real boundary: a review envelope is only parseable for a
reviewing role, and an EXPLORER can therefore never return an authoritative ReviewRecord.
"""
from .domain import Role, RoleName

WORK_OUTPUT = ('findings', 'messages', 'task_requests', 'reconsiderations')
REVIEW_OUTPUT = ('review', 'messages')
"""A reviewer cannot report a reconsideration: review independence is about one claim, and
nothing a reviewer says may steer another branch's work."""
SYNTHESIS_OUTPUT = ('result', 'messages')
"""A synthesizer proposes exactly one answer. It cannot create findings, request work or
answer a delivery, so it can neither manufacture the support it cites nor extend the run."""

INSTRUCTIONS = {
    RoleName.EXPLORER: 'Investigate the objective. Use the permitted tools for any numeric claim. '
                       'State each claim as sum([a, b, c]) = t when it is an integer sum.',
    RoleName.SPECIALIST: 'Apply focused expertise to the objective and report tool-backed claims.',
    RoleName.COLLABORATOR: 'Combine the supplied evidence and report tool-backed claims. When the '
                           'context lists propagations, answer each one you are asked to consume '
                           'with APPLIED, NO_CHANGE or FOLLOW_UP_REQUESTED and a concrete reason. '
                           'A delivered discovery is a request to reconsider, not proof that your '
                           'branch is wrong.',
    RoleName.CRITIC: 'Adversarially examine the target claim at the exact revision given. Report '
                     'unsupported assumptions, contradictions, arithmetic or logical errors, missing '
                     'or misread evidence and unaddressed edge cases. You do not decide truth. '
                     'Decide PASS, CHALLENGE or INCONCLUSIVE.',
    RoleName.VALIDATOR: 'Independently verify the target claim at the exact revision given against its '
                        'evidence, the critique blocking issues and your own tool checks. Name each '
                        'blocking issue key you resolved. Decide PASS, FAIL or INCONCLUSIVE. Your '
                        'PASS is necessary but not sufficient: the host verifies the evidence itself.',
    RoleName.CONSOLIDATOR: 'Report duplicate and conflicting claims. Consolidation itself is deterministic.',
    RoleName.CROSS_POLLINATOR: 'Relevance routing is a deterministic host service; it schedules '
                               'no model call. Registered so the capability is explicit.',
    RoleName.SYNTHESIZER: 'Compose the final answer from the supplied validated findings only. '
                          'Cite the finding ids that support each criterion and each material '
                          'claim; state as a limitation anything the evidence does not settle. '
                          'You may not introduce a factual claim no supplied finding supports.',
    RoleName.FINAL_REVIEWER: 'Judge the supplied result version independently against the '
                             'acceptance criteria and the findings it cites. Check required '
                             'criterion coverage, unsupported claims, contradictions, citation '
                             'validity, unresolved conflicts, unacknowledged limitations and '
                             'internal consistency. Name the criteria and claims at fault. '
                             'Decide PASS, REVISE or REJECT. You do not change findings or the '
                             'run; your PASS is necessary and never sufficient.',
}

REVIEW_ROLES = (RoleName.CRITIC, RoleName.VALIDATOR, RoleName.FINAL_REVIEWER)
RUN_SCOPED_ROLES = REVIEW_ROLES + (RoleName.SYNTHESIZER,)


def role_id(name: RoleName) -> str:
    return f'role:{name}'


def _shape(name):
    if name in REVIEW_ROLES:
        return REVIEW_OUTPUT, 'review', 'review_record'
    if name == RoleName.SYNTHESIZER:
        return SYNTHESIS_OUTPUT, 'synthesis', 'result'
    return WORK_OUTPUT, 'task', 'execution_result'


def default_roles(*, allowed_tools=(), review_tools=None) -> tuple[Role, ...]:
    """Every role the architecture names; scheduling one is a separate decision."""
    review_tools = allowed_tools if review_tools is None else review_tools
    roles = []
    for name in RoleName:
        output_fields, input_kind, output_kind = _shape(name)
        roles.append(Role(id=role_id(name), name=name, instructions=INSTRUCTIONS[name],
                          allowed_tools=tuple(review_tools if name in REVIEW_ROLES else allowed_tools),
                          output_fields=output_fields, input_kind=input_kind, output_kind=output_kind,
                          communication_scope='run' if name in RUN_SCOPED_ROLES else 'group'))
    return tuple(roles)
