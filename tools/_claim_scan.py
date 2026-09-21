#!/usr/bin/env python3
"""Find claims about this repository that the repository itself contradicts.

Two families so far, both of which survived four or five rounds of being fixed one
named location at a time:

  PLUGIN   .claude/settings.json declares a plugin, or a plugin arrives in cloud.
  UNDO     `--uninstall` touches only what is inside this repository.

Run from tools/test.sh. Stdlib only, no arguments, prints a report and exits 0 unless the
settings file itself cannot be read.

Why this exists rather than a `grep` for one sentence: the statement "the plugin is
declared in .claude/settings.json and installs in cloud" was corrected three separate
times -- in cloud/README.md, then twice in manifest/external-skills.json, then as a JSON
boolean in profile/plugins.json. Each fix addressed the wording the previous review had
named, and each time another phrasing of the same claim was still in the tree. A check
tied to a phrasing would have missed all three.

Three passes. The first two RESOLVE A NAMED KEY AGAINST PARSED DATA -- one right answer,
no judgement -- and they are the hard gate. The third matches free-form prose and is
advisory only; the difference is stated on each, and `tools/test.sh` enforces it.


  STRUCTURAL   HARD. A field asserting this repository's settings enable a plugin must
               agree with what the settings file actually declares. It matches any key
               ending `InRepoSettings` and any truthy spelling of the value, so a rename
               or a stringified boolean does not evade it -- but it is a rule about a
               shape of key, not about meaning, and a genuinely different encoding would
               need a new rule here.
  HEADING-     HARD. Every key named in the first column of `.claude/SETTINGS-NOTES.md`'s
  SCOPED       "What is here, and why" table must actually be in the settings file, whole
               dotted path resolved. It fails closed on a missing heading or an empty
               table. It exists because the assertion can be carried by the HEADING rather
               than by the row: see the long note in main().
  TEXTUAL      a passage putting settings.json and a plugin together, or saying a plugin
               arrives in cloud, must carry a negation, a past tense or a condition. The
               same pass also looks for the `--uninstall` reversibility claim. **ADVISORY
               ONLY, and non-authoritative.** It prints `ADVISORY` lines, it is not
               counted in `PROBLEMS`, and `tools/test.sh` does not fail on it. It is a
               tripwire for a careless restatement, nothing more: a sentence containing a
               negation word anywhere satisfies it. See the note on SAFE.

               MEASURED 2026-09-21, and that measurement is why it was demoted from a
               hard gate. It is worse in both directions than "one known evasion" said.
               Seven restatements of the false claim appended to
               cloud/README.md: ONE caught, SIX missed -- "If you open a cloud session,
               the plugin declared in .claude/settings.json installs automatically" walks
               past on `if`, "Without any extra work..." on `without`, "Rather than
               installing by hand..." on `rather than`, and "extension" for "plugin"
               evades the vocabulary entirely. Four correct, scoped sentences appended
               the same way: FOUR flagged, including "The plugin composition lives in
               profile/plugins.json; .claude/settings.json holds permissions", which is
               the true statement this whole check exists to protect. tools/test.sh gates
               on PROBLEMS 0, so writing a correct sentence on this subject fails the
               suite. Tightening it has been tried and reverted once already (requiring
               corroboration flagged ten correct passages to catch one crafted sentence).
               What establishes anything here is STRUCTURAL and HEADING-SCOPED. Read this
               pass as a smoke alarm with a known false-alarm rate, and do not let its
               green mean the claim is absent. Its hits are worth reading before a claim
               about this subject lands; they are not worth blocking a change over, and
               since 2026-09-21 they do not.

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

# Skipped by RELATIVE PATH, never by basename. `--exclude=test.sh` in the shell version of
# the undo guard was a basename glob, so a second file named test.sh anywhere in the tree
# was silently unscanned.
SKIP_PATHS = {'tools/test.sh', 'tools/_claim_scan.py'}
SKIP_DIRS = {'.git'}

# Every text file, not a suffix list: the claim was found once in a .toml adapter and once
# in an extensionless file, both of which a suffix list walks past. A file that is not
# UTF-8 is not prose and is skipped.
MAX_BYTES = 2_000_000


def text_files(root: pathlib.Path):
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if set(rel.parts) & SKIP_DIRS or str(rel) in SKIP_PATHS:
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            yield path, path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeDecodeError):
            continue


# The undo claim. Subject deliberately wide -- "the undo removes only links..." names no
# command and is the same false sentence -- and no [^.] window, because a full stop inside
# it was enough to walk past.
UNDO = re.compile(
    r'(uninstall|the undo|undoing)'
    r'[\s\S]{0,160}?'
    r'\b(only|never)\b'
    r'[\s\S]{0,160}?'
    r'\b(inside|within|outside)\b'
    r'[\s\S]{0,60}?'
    r'\b(repository|repo|toolkit|checkout)\b',
    re.I)
# A correction says it WAS said and was wrong. Kept tight on purpose: the shell version
# retired a hit on the word "said" appearing anywhere, including in the file path.
UNDO_CORRECTION = re.compile(
    r'until \d{4}|was false|were false|no longer (says|said)|used to say|said until'
    r'|this bullet said|may not|must not|never promise', re.I)


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
    # TWO lists, and the split is the point. `problems` are the checks that resolve a
    # named key against parsed data -- they answer a question with one right answer, and
    # they are what tools/test.sh fails on. `advisories` are the free-form prose
    # heuristic, which is NOT authoritative: measured 2026-09-21 it caught 1 of 7
    # restatements of the false claim and flagged 4 of 4 correct, scoped sentences. It was
    # a hard gate until then, which meant writing a true sentence on this subject failed
    # the suite while six false ones passed. It reports; it does not decide.
    problems = []
    advisories = []

    try:
        blob_settings = json.loads((root / '.claude/settings.json').read_text())
        keys = sorted(blob_settings)
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
        rel = path.relative_to(root)
        if set(rel.parts) & SKIP_DIRS or str(rel) in SKIP_PATHS:
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

    # A THIRD shape, and the reason it needs its own rule: the assertion can be carried
    # by the section HEADING rather than by the row under it. `.claude/SETTINGS-NOTES.md`
    # kept a row describing `extraKnownMarketplaces` under "What is here, and why" --
    # twenty lines below another row recording that the key had been removed. The row's
    # own words named no file, so the textual pass could not see it, and it was a string
    # in Markdown, so the structural pass could not either. A reader saw the heading and
    # the key and believed the file declares it.
    #
    # So: every key named in the first column of that table must actually be in the
    # settings file. Scoped to this one document because this is the one document whose
    # job is to say what that file contains.
    notes = root / '.claude/SETTINGS-NOTES.md'
    if notes.exists():
        note_lines = notes.read_text().splitlines()
        heads = [n for n, l in enumerate(note_lines, 1)
                 if l.strip().lower().startswith('## what is here')]
        # Fail closed if the rule cannot find its subject, or finds it empty. The heading
        # is matched literally, so renaming it would silently retire this pass; and
        # keeping the heading while moving the table under a new one defeated it just as
        # quietly. Both are now failures of the check itself.
        if not heads:
            problems.append(f'{notes}: no "## What is here" heading — the rule that every '
                            'key listed there must be in settings.json cannot locate its '
                            'table. Restore the heading or update this check.')
        else:
            in_table, rows = False, 0
            for n, line in enumerate(note_lines, 1):
                if line.startswith('#'):
                    in_table = line.strip().lower().startswith('## what is here')
                    continue
                if not in_table or not line.lstrip().startswith('|'):
                    continue
                cell = line.strip().strip('|').split('|')[0].strip()
                if not cell or set(cell) <= set('-: '):
                    continue          # the header rule
                rows += 1
                # Backticked OR bare. A row naming the key with no backticks read as
                # prose and was skipped, although it asserted exactly the same thing.
                named = re.findall(r'`([^`]+)`', cell) or re.findall(r'[A-Za-z][\w.]*', cell)
                for key in named:
                    key = key.strip()
                    if not key or key.startswith('$') or key.lower() in ('key', 'omitted'):
                        continue
                    # Resolve the WHOLE dotted path, not just its first component.
                    # `permissions.allow` passed because `permissions` is declared, while
                    # the same file records twenty lines below that `allow` is not there.
                    node, ok_here = blob_settings, True
                    for part in key.split('.'):
                        if isinstance(node, dict) and part in node:
                            node = node[part]
                        else:
                            ok_here = False
                            break
                    if not ok_here:
                        problems.append(f'{notes}:{n}: "What is here, and why" lists '
                                        f'{key!r}, which .claude/settings.json does not '
                                        'declare')
            if rows == 0:
                problems.append(f'{notes}: the "What is here, and why" section holds no '
                                'table rows. The rule that every key listed there must be '
                                'in settings.json has nothing to check, which is how it '
                                'was defeated once: heading kept, table moved elsewhere.')

    # --- ADVISORY from here down. Regex over prose, both families. Neither fails a suite.
    for path, lines in text_files(root):
        for start, text in units(path, lines):
            if UNDO.search(text) and not UNDO_CORRECTION.search(text):
                advisories.append(f'{path}:{start}: claims --uninstall touches only what '
                                  'is inside this repository. A pack link resolves outside '
                                  'it by definition and is removed.')
            if SAFE.search(text):
                continue
            if PAIR.search(text) and PLUGIN.search(text):
                advisories.append(f'{path}:{start}: puts settings.json and a plugin '
                                  'together with no negation, past tense or condition')
            elif PLUGIN.search(text) and CLOUD.search(text) and ARRIVE.search(text):
                advisories.append(f'{path}:{start}: says a plugin arrives in cloud, '
                                  'unqualified')

    for problem in problems:
        print('CLAIM ' + problem)
    for advisory in advisories:
        print('ADVISORY ' + advisory)
    print('PROBLEMS ' + str(len(problems)))
    print('ADVISORIES ' + str(len(advisories)))
    if advisories:
        print('NOTE the ADVISORY lines are a prose heuristic, not authoritative: it has '
              'missed 6 of 7 restatements of the claim it looks for and flagged 4 of 4 '
              'correct, scoped sentences. Read them; do not treat them as findings.')
    # The exit status agrees with PROBLEMS. It used to be 0 either way, which made an
    # rc-based probe of this script read every plant, true and false, as a pass.
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
