---
name: checkable-findings
description: Produce findings another identity can check independently, instead of a report that has to be taken on trust. Use when reporting what an investigation found, writing up an exploration or a domain analysis, handing results to a reviewer or a validator, recording the evidence behind a claim, or before stating a cause, a diagnosis or a recommendation. Enforces one claim per finding, a locator, evidence as recorded rather than paraphrased, an observed/inferred/unresolved status, a stated investigation boundary, and no self-certification.
---

# Checkable findings

A finding is not a sentence about what you believe. It is **an object someone else can pick up
and check without you**, and without repeating your investigation.

This is the producing side of the evidence contract. Whether evidence entails a claim belongs
to [`evidence-verification`](../evidence-verification/SKILL.md); whether a claim holds belongs
to [`independent-validation`](../independent-validation/SKILL.md). Both are downstream of you,
and both are wasted on a report they cannot check.

> **If a reader cannot tell what would falsify it, where to look, or what you actually saw,
> you have written an opinion with citations.**

## The contract

Each finding carries all seven parts. One missing part makes the finding incomplete, not
merely terse.

| Part | Requirement |
|---|---|
| **Identity** | A stable label this finding can be referred to, disputed and resolved by. |
| **One claim** | Exactly one assertion, stated so that it could be false. |
| **Locator** | Where to look, precisely enough that another identity lands on the same thing. |
| **Evidence, recorded** | What was actually produced, reproduced — not your account of it. |
| **Status** | `observed`, `inferred` or `unresolved`. Never a fourth. |
| **What would settle it** | For anything not `observed`: the check or answer that would move it. |
| **Boundary** | What this finding covers, and what it does not. |

### 1. Give the finding an identity

A stable label — `F1`, `FINDING-3`, whatever the surrounding system uses — so the finding can
be referred to, disputed, tracked and closed **by name**. Prose findings get discharged by
prose: "all findings addressed" resolves nothing anyone can check.

The label costs one token and is what lets a reviewer's objection and a repairer's disposition
point at the same thing later.

**What triggers the requirement is the assertion, not the topic.** Anything you surface as a
substantive concern — something that could change what the reader does, or that someone has
to follow up — takes a finding's identity and status, wherever in the report it sits. Saying
you did not look at something does not: "the retry path was not examined" is a boundary line,
it costs nothing, and ordinary unexplored paths should stay that cheap. The requirement begins
the moment you assert something substantive about that path. A concern raised in narrative prose, or
tucked inside a not-investigated list, has no identity to dispute it by, no status to qualify
it and no evidence to attack — which is the one shape a reader cannot act on and cannot
close.

### 2. One claim, not a bundle

"The discount is truncated as a float and the tax step truncates again" is two claims. They
usually have different evidence, different status and different answers, and bundled they
get one verdict — normally the verdict the strongest half deserves.

Split until each finding can be answered yes or no on its own. A finding that needs "partly"
is still a bundle.

**The rule binds the whole finding, not the claim field.** A heading, a title or a summary
sentence that carries a second assertion has bundled the finding again, whatever the field
beneath it says. The heading is what a reader quotes, disputes and carries away, so it is
held to the same one-claim standard as the claim it heads.

**Mechanism, prevalence and consequence are three claims, not three clauses.** *How* something
goes wrong, *how often* or *on which inputs*, and *what it costs* are separately resolvable and
usually separately supported — the mechanism can be `observed` from one run while the
prevalence is `inferred` and the consequence `unresolved`. Split them wherever each could be
answered on its own. Fitting under one claim label is not evidence that it is one claim, and
compressing three claims into one sentence is not splitting them.

### 3. A locator, in the subject's own terms

A locator answers *where do I go to see this myself*. What counts depends on the subject, so
the form is not fixed — the precision is.

| Subject | Locator |
|---|---|
| An artifact | its location plus the line, section or element |
| A behaviour | the check that was run, and the result it returned |
| A source | the source, its version, and the date it was read |
| A state | the identifier, and the state it was in when read |
| An exchange | who said it, where, and when |

Naming a region is not a locator. "In the pricing code" and "somewhere in the retry path"
cost the reader the search you already did.

### 4. Record the evidence; do not describe it

- **Reproduce what was produced**, not your reading of it. "The check reports a mismatch" is
  a description. The line the check actually emitted is evidence.
- **Record the whole of the relevant result.** A run with three passes and one failure is
  four facts. Quoting only the failure hides the scope of what was exercised.
- **Name what produced it**, so it can be run again. Evidence with no origin cannot be
  re-checked, and therefore is not evidence.
- **Where you could not record it, say so.** Unrecorded evidence is a status, not a
  formatting problem.

### 5. Status, and never the one above it

| Status | Means |
|---|---|
| `observed` | You saw it. Recorded evidence supports exactly this claim. |
| `inferred` | You reasoned to it from something observed. Plausible; unchecked. |
| `unresolved` | You could not determine it. |

The characteristic failure is not invented evidence. It is an inference stated in the same
voice, in the same paragraph, as an observation — so the reader inherits the observation's
confidence and carries it to the inference.

**One observation does not establish the mechanism that would explain it.** A single measured
case supports a claim about that case. The general rule behind it is `inferred` until
something exercises the general rule.

### 6. Say what would settle it

Every `inferred` and every `unresolved` finding names the check, artifact, measurement or
answer that would move it. Without that, the next identity has to rediscover what you already
know is missing, and usually does not.

This is also how an `unresolved` finding stays useful. "I could not determine the intended
rounding behaviour; the specification or the owner would settle it" is worth more than
silence, and much more than a guess.

### 7. State the boundary of the investigation

**Silence reads as coverage.** A report that names three things it examined, and does not say
what it left alone, will be read as a report on the whole subject.

State what was in range and not examined, and why — budget, access, relevance. Where you
concluded something was *not* the cause, that is itself a finding and needs its own locator
and evidence; "ruled out" with nothing recorded is an assertion.

Each item here is therefore one of two things and never both: a path you genuinely left alone
— named, with the reason you left it, and nothing substantive claimed about it beyond that
reason — or a finding that has wandered out of place. "Out of scope for a pricing bug" is the
reason and stays cheap. "Out of scope, *and* probably where the duplicate charge comes from"
is a claim made under a heading that excuses it from carrying one.

## Two rules about the report, not about one finding

### 8. Report failed approaches and open paths where omission would mislead

Not everything you tried. The ones whose absence would leave the reader with a false picture:
an approach that looked obvious and does not work, a path that is still open and will look
unexplored for no reason, a check that was unavailable.

### 9. Certifying language is not a status

*Verified*, *confirmed*, *proven*, *validated*, *root cause* and *ruled out* name a judgement
that an identity other than you gets to make. They are not forbidden words. They are words
that cannot do a status's work, and the failure is using them where the status belongs.

**Never as a heading, never as a status, never in place of the evidence.** A heading is read
first, quoted most and travels furthest from its evidence, so "proves", "confirms" and "the
root cause is" certify the finding in the one line least likely to arrive with the evidence
attached. In a status field the word is a fourth value, and there are only three.

**In body prose they are fine where the sentence carries its own support.** Name the check or
evidence the statement rests on — something *outside the models*, named precisely enough to be
run again — and say what it establishes and what it does not. Another identity's agreement is
not such a check.

Where that sentence may sit follows from §7 above, not from this rule. Inside a finding whose
evidence records the check and what produced it, "ruled out for the discount path, and not
beyond it" is a scoped reading of evidence already on the page. Standing alone in a boundary
list or a summary it is the assertion the evidence was supposed to replace — and §7 has
already said that concluding something is *not* the cause is a finding, with its own locator
and evidence, rather than a line under a boundary.

Either way the finding still carries `observed`, `inferred` or `unresolved`. **No wording
upgrades it**, and a producer who marks its own work established removes the only signal
telling a reviewer where to look hardest.

## Check the conclusion against the evidence you cited

A recommendation is a claim, and it is the one most likely to escape the contract — it
arrives after the findings, in a different voice, and reads as a next step rather than an
assertion.

So before you state it, take the evidence you cited as the specification, apply your own
recommendation to it, and record the result. A recommendation that does not satisfy the
evidence the same report offered as the standard is the most expensive defect this skill
prevents, because everything around it looks careful.

**Each branch of an either/or remediation is a separate claim, and each is checked
separately.** "Floor it or round it" is two recommendations. Where the evidence you cited
admits one and contradicts the other, offering them as interchangeable throws away the work
that found the difference and hands the reader back the defect. Check each branch against the
cited evidence, state which one it supports, and say how the other fails it. Where the check
cannot separate them, that is a finding about the evidence, with a status of its own.

**Where the right remediation depends on something unresolved, stop at the decision point.**
If a specification, a rule or an owner's intent is what decides which fix is correct, name the
decision, name what would settle it, and stop there. A conditional recommendation carries an
unchecked implementation choice on the back of an honest uncertainty, and reads as covered
ground. The unresolved finding with its decision named is the deliverable.

## Shape

```text
FINDING <id>
  CLAIM       <one assertion>
  STATUS      observed | inferred | unresolved
  LOCATOR     <where another identity goes to see this>
  EVIDENCE    <what was actually produced, reproduced; and what produced it>
  SETTLES IT  <what would move an inferred or unresolved status>
  BOUNDARY    <what this covers and what it does not>

NOT INVESTIGATED
  <in range, not examined, and why>

TRIED AND FAILED · OPEN PATHS
  <what would mislead by its absence>
```

Adapt the shape to the medium. Do not drop a part because the medium is prose: a paragraph
can carry all seven, and usually stops carrying the last three first.

## Common failure modes

| Failure | What it looks like |
|---|---|
| Compound finding | One heading, two claims, one verdict — earned by the stronger half. |
| Mechanism fused to prevalence | How it breaks and how often it breaks, resolved as one claim with one status. |
| No identity | Objections and resolutions are prose, so nothing can be closed by name. |
| Region as locator | "In the retry path." The reader repeats the search you already did. |
| Evidence described | Your reading of the result, in place of the result. |
| Selective quotation | The failing line, without the passes that scope it. |
| Voice flattening | Measurement and inference in one paragraph, one confidence. |
| One case, general claim | A single measured instance, reported as the mechanism. |
| Unstated boundary | Three things examined; the reader assumes the rest was too. |
| Silent exclusion | "Ruled out", with nothing recorded that rules it out. |
| Self-certification | The producer's own verdict standing in for the evidence — as a heading, as a status, or alone in prose. |
| Unchecked recommendation | The proposed fix does not satisfy the evidence the report cited. |
| Interchangeable remediations | Two fixes offered as equivalent when the cited evidence admits one of them. |
| Smuggled conditional | An unresolved decision wrapped around an implementation choice nobody checked. |

## Related

- [`evidence-verification`](../evidence-verification/SKILL.md) — what your evidence is then
  tested against, and the strength ordering your status should not outrun.
- [`independent-validation`](../independent-validation/SKILL.md) — the identity that will
  check these findings, using your locators.
- [`bounded-context-handoff`](../bounded-context-handoff/SKILL.md) — what travels with a
  finding when it leaves you.
- Roles: [Explorer](../../roles/explorer.md), [Specialist](../../roles/specialist.md) and
  [Implementer](../../roles/implementer.md) are the producing roles this serves; each keeps
  its own output contract on top of this method.
