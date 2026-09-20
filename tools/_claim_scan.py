#!/usr/bin/env python3
"""Find any file claiming .claude/settings.json declares a plugin, or that one arrives in cloud.

Run from tools/test.sh. Stdlib only, no arguments, prints a report and exits 0 unless the
settings file itself cannot be read.

Why this exists rather than a `grep` for one sentence: the statement "the plugin is
declared in .claude/settings.json and installs in cloud" was corrected three separate
times -- in cloud/README.md, then twice in manifest/external-skills.json, then as a JSON
boolean in profile/plugins.json. Each fix addressed the wording the previous review had
named, and each time another phrasing of the same claim was still in the tree. A check
tied to a phrasing would have missed all three.

Two passes, because the claim appears in two shapes:

  STRUCTURAL   a field asserting this repository's settings enable a plugin must agree
               with what the settings file actually declares. It matches any key ending
               `InRepoSettings` and any truthy spelling of the value, so a rename or a
               stringified boolean does not evade it -- but it is a rule about a shape of
               key, not about meaning, and a genuinely different encoding would need a
               new rule here.
  TEXTUAL      a passage putting settings.json and a plugin together, or saying a plugin
               arrives in cloud, must carry a negation, a past tense or a condition. This
               one is a tripwire for a careless restatement, NOT a proof: a sentence
               containing a negation word anywhere satisfies it. See the note on SAFE.

It is deliberately NOT gated on what settings.json currently holds. The "installs in
cloud" half was falsified by a measurement, not by the declaration, so gating the whole
check on the declaration would re-admit the sentence the moment a plugin key came back.
"""

import json
import pathlib
import re
import sys

PAIR = re.compile(r'settings\.json', re.I)
PLUGIN = re.compile(r'plugin|marketplace', re.I)
CLOUD = re.compile(r'\bcloud\b', re.I)
ARRIVE = re.compile(r'install|load|deliver|arrive|available', re.I)

# The textual pass is a TRIPWIRE, not a proof, and the difference is worth stating because
# the temptation is to describe it as covering the class.
#
# A passage may put these words together when it negates the claim, scopes it to the past,
# or states a condition. Anything else is an assertion and has to answer for itself. That
# catches every restatement found in this tree so far, and a critic walked past it in one
# try with "No earlier sentence said so, but the ecc plugin is declared in
# .claude/settings.json and installs in cloud" -- a stray "No" anywhere in the sentence
# satisfies the list.
#
# Requiring CORROBORATION instead (a date, "measured", or a file holding the record) was
# tried and is worse: it flagged ten passages of correct, carefully scoped prose --
# including profile/README.md's own statement of the three claim tiers -- to catch that one
# crafted sentence. Ten false alarms train people to ignore the check.
#
# So the structural pass is the one that establishes anything. This pass is a net for the
# careless restatement, which is what has actually happened four times in this tree.
#
# It also false-alarms: a purely navigational sentence naming settings.json and a plugin
# file in the same breath trips it. That is recorded here rather than left for someone to
# discover, and it is the price of the net being loose enough to be worth having.
SAFE = re.compile(
    r"\bno\b|\bnone\b|\bnot\b|never|without|moved|\bwas\b|\bwere\b|until|false|zero"
    r"|used to|no longer|rather than|instead|\bif\b|declined|absent",
    re.I)
# `only` was in that list and had to come out. It let through
# ".claude/SETTINGS-NOTES.md: ... and only `enabledPlugins` and `extraKnownMarketplaces` in
# a multi-repository project thread" -- an assertion that those keys ARE honoured, where
# the exempting word was part of the assertion. A restriction is not a negation.

# Any key of this shape, not one exact spelling: `enabledInRepoSettings` renamed to
# `declaredInRepoSettings`, or its value written as the string "true", both walked past the
# first version of this pass.
REPO_SETTINGS_KEY = re.compile(r'InRepoSettings$', re.I)

SKIP_NAMES = {'test.sh', '_claim_scan.py'}

# Files that can carry prose about this. Not only .md and .json: the docstring used to say
# "any file" while reading two suffixes.
SUFFIXES = ('*.md', '*.json', '*.sh', '*.py', '*.toml')


def truthy(val) -> bool:
    """True, "true", "yes", 1 -- anything that asserts the thing, however it is spelled."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ('true', 'yes')
    return val == 1 and not isinstance(val, bool)


def units(path: pathlib.Path, lines: list) -> list:
    """The text spans a claim can occupy, each with the line it starts on.

    Prose wraps. A sentence whose subject is on one line and whose negation is on the next
    is one claim, and scanning line by line reported the first half as an unqualified
    assertion -- which it was not. So Markdown is scanned by paragraph: runs of non-blank
    lines, joined. JSON stays line by line, because a value there is one line and joining
    would let a neighbouring key's wording excuse this one.
    """
    if path.suffix != '.md':
        return [(n, line) for n, line in enumerate(lines, 1)]
    out, start, buf = [], None, []

    def flush():
        nonlocal start, buf
        if buf:
            out.append((start, ' '.join(buf)))
        start, buf = None, []

    for n, line in enumerate(lines, 1):
        # A TABLE ROW is its own claim and must not borrow a neighbour's exemption. The
        # table in cloud/README.md had a row saying plugins in settings.json are "loaded"
        # and another saying permission rules "do NOT apply"; joined as one paragraph, the
        # second row's negation excused the first, and the false row went unflagged.
        if line.lstrip().startswith('|'):
            flush()
            out.append((n, line))
            continue
        if line.strip():
            if start is None:
                start = n
            buf.append(line)
        else:
            flush()
    flush()
    return out


def main() -> int:
    root = pathlib.Path('.')
    problems = []

    try:
        keys = sorted(json.loads((root / '.claude/settings.json').read_text()))
    except Exception as exc:
        # A failed read must not print a green tick. It is a failure of the check itself.
        print(f'UNREADABLE .claude/settings.json: {exc}')
        return 1
    print('SETTINGS-KEYS ' + ','.join(keys))

    declares = any(k in keys for k in ('enabledPlugins', 'extraKnownMarketplaces'))
    if declares:
        problems.append('.claude/settings.json declares plugin keys; profile/README.md '
                        'records that they were moved out because declaring them there '
                        'asserted a capability the repository does not have')

    for path in sorted(root.rglob('*.json')):
        if '.git' in path.parts or path.name in SKIP_NAMES:
            continue
        try:
            blob = json.loads(path.read_text())
        except Exception:
            continue                       # malformed JSON is the hygiene group's finding
        stack = [blob]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, val in node.items():
                    if REPO_SETTINGS_KEY.search(key) and truthy(val) and not declares:
                        problems.append(f'{path}: {key} is {val!r} while settings.json '
                                        'declares no plugin keys')
                    stack.append(val)
            elif isinstance(node, list):
                stack.extend(node)

    scan = []
    for pattern in SUFFIXES:
        scan.extend(root.rglob(pattern))
    for path in sorted(set(scan)):
        if '.git' in path.parts or path.name in SKIP_NAMES:
            continue
        try:
            lines = path.read_text().splitlines()
        except Exception:
            continue
        for start, text in units(path, lines):
            if SAFE.search(text):
                continue
            if PAIR.search(text) and PLUGIN.search(text):
                problems.append(f'{path}:{start}: puts settings.json and a plugin together '
                                'with no negation, past tense or condition')
            elif PLUGIN.search(text) and CLOUD.search(text) and ARRIVE.search(text):
                problems.append(f'{path}:{start}: says a plugin arrives in cloud, unqualified')

    for problem in problems:
        print('CLAIM ' + problem)
    print('PROBLEMS ' + str(len(problems)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
