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

### 2. One claim, not a bundle

"The discount is truncated as a float and the tax step truncates again" is two claims. They
usually have different evidence, different status and different answers, and bundled they
get one verdict — normally the verdict the strongest half deserves.

Split until each finding can be answered yes or no on its own. A finding that needs "partly"
is still a bundle.

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

## Two rules about the report, not about one finding

### 8. Report failed approaches and open paths where omission would mislead

Not everything you tried. The ones whose absence would leave the reader with a false picture:
an approach that looked obvious and does not work, a path that is still open and will look
unexplored for no reason, a check that was unavailable.

### 9. Do not certify your own evidence

*Verified*, *confirmed*, *proven*, *validated*, *root cause* and *ruled out* are the
vocabulary of an identity that is not you. You propose; something else establishes.

This is not modesty. A producer who marks its own work established removes the only signal
telling a reviewer where to look hardest.

## Check the conclusion against the evidence you cited

A recommendation is a claim, and it is the one most likely to escape the contract — it
arrives after the findings, in a different voice, and reads as a next step rather than an
assertion.

So before you state it, take the evidence you cited as the specification, apply your own
recommendation to it, and record the result. A recommendation that does not satisfy the
evidence the same report offered as the standard is the most expensive defect this skill
prevents, because everything around it looks careful.

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
| No identity | Objections and resolutions are prose, so nothing can be closed by name. |
| Region as locator | "In the retry path." The reader repeats the search you already did. |
| Evidence described | Your reading of the result, in place of the result. |
| Selective quotation | The failing line, without the passes that scope it. |
| Voice flattening | Measurement and inference in one paragraph, one confidence. |
| One case, general claim | A single measured instance, reported as the mechanism. |
| Unstated boundary | Three things examined; the reader assumes the rest was too. |
| Silent exclusion | "Ruled out", with nothing recorded that rules it out. |
| Self-certification | The producer calls its own finding verified, confirmed or the root cause. |
| Unchecked recommendation | The proposed fix does not satisfy the evidence the report cited. |

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
