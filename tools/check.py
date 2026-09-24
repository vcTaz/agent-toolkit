#!/usr/bin/env python3
"""Structural checks and adapter synchronisation for this toolkit.

This is maintenance infrastructure, not a framework. It is deliberately one
stdlib-only file. It does not compile prompts, template anything, execute a
workflow or read a configuration language.

    python3 tools/check.py           check structure and adapter drift
    python3 tools/check.py --sync    regenerate adapter bodies from roles/

Every check fails closed: something this script cannot classify is an error,
never a pass.
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_ROLE_SECTIONS = [
    'Purpose', 'Use this role when', 'Do not use this role when', 'Inputs', 'Outputs',
    'Decision vocabulary', 'Independence', 'Allowed', 'Prohibited',
    'Interaction with other roles', 'Verification expectations', 'Completion conditions',
    'Orchestration principles that govern this role',
]
"""Fixed and ordered. A role missing one has not been specified, only described."""

BEGIN = '<!-- canonical:begin source={source} sha256={digest} -->'
END = '<!-- canonical:end -->'
BEGIN_RE = re.compile(r'<!-- canonical:begin source=(\S+) sha256=([0-9a-f]{64}) -->')
TOML_RE = re.compile(r'^# canonical: (\S+) sha256=([0-9a-f]{64})$', re.M)
SKILL_NAME_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
LINK_RE = re.compile(r'\[[^\]]*\]\((?!https?:|#)([^)#]+)(?:#[^)]*)?\)')

problems: list[str] = []


def fail(where, message):
    problems.append(f'{where}: {message}')


def frontmatter(path):
    """Return (fields, body). A file without frontmatter is an error, not a default."""
    text = path.read_text(encoding='utf-8')
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', text, re.S)
    if match is None:
        fail(path, 'no YAML frontmatter')
        return {}, text
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(':')
        if _:
            fields[key.strip()] = value.strip()
    return fields, match.group(2).strip()


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# --- canonical layers ----------------------------------------------------------------

def load_roles():
    """Every canonical role, checked for structure. Returns {id: (path, body)}."""
    return _load_definitions('roles', require_sections=True)


def load_agents():
    """Free-form agent definitions. Returns {id: (path, body)}.

    Same canonical-plus-adapter machinery as roles/, minus the role contract. A role
    asserts a distinct epistemic posture, output contract and independence requirement;
    most useful agents assert none of those and are not roles. This tier exists so that
    adding one does not require pretending otherwise, and so there is exactly one place
    in this repository where an agent is added.
    """
    if not (ROOT / 'agents').is_dir():
        return {}
    return _load_definitions('agents', require_sections=False)


def _load_definitions(directory, require_sections):
    roles = {}
    for path in sorted((ROOT / directory).glob('*.md')):
        if path.name == 'README.md':
            continue
        fields, body = frontmatter(path)
        identity = fields.get('id')
        if identity != path.stem:
            fail(path, f'frontmatter id {identity!r} does not match filename {path.stem!r}')
            continue
        if not fields.get('summary'):
            fail(path, 'frontmatter has no summary')
        found = re.findall(r'^## (.+)$', body, re.M) if require_sections else None
        if require_sections and found != REQUIRED_ROLE_SECTIONS:
            missing = [s for s in REQUIRED_ROLE_SECTIONS if s not in found]
            extra = [s for s in found if s not in REQUIRED_ROLE_SECTIONS]
            detail = f'missing {missing}' if missing else (
                f'unexpected {extra}' if extra else 'sections out of order')
            fail(path, f'section structure: {detail}')
        if "'''" in body:
            fail(path, "body contains ''' and cannot be embedded in a TOML literal string")
        # A role body is copied verbatim into adapters in other directories, so a relative
        # link either breaks there or — worse — resolves to a different file. Reference
        # other documents by repository-root path in backticks instead.
        for target in LINK_RE.findall(body):
            fail(path, f'relative link {target!r}: a synced body must be '
                       'location-independent. Use a `path/from/repo/root` in backticks.')
        roles[identity] = (path, body, fields.get('summary', ''))
    if require_sections and not roles:
        fail('roles/', 'no canonical roles found')
    return roles


def check_skills():
    """Agent Skills conformance: name matches directory, valid slug, bounded description."""
    directories = sorted(p for p in (ROOT / 'skills').iterdir() if p.is_dir())
    for directory in directories:
        path = directory / 'SKILL.md'
        if not path.is_file():
            fail(directory, 'no SKILL.md')
            continue
        fields, _ = frontmatter(path)
        name, description = fields.get('name', ''), fields.get('description', '')
        if name != directory.name:
            fail(path, f'name {name!r} does not match directory {directory.name!r}')
        if not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
            fail(path, f'name {name!r} is not a valid Agent Skills slug (max 64, [a-z0-9-])')
        if not description:
            fail(path, 'no description')
        elif len(description) > 1024:
            fail(path, f'description is {len(description)} characters, maximum is 1024')
    if not directories:
        fail('skills/', 'no skills found')


# --- adapters ------------------------------------------------------------------------

def claude_adapter(identity):
    return ROOT / '.claude' / 'agents' / f'{identity}.md'


def codex_adapter(identity):
    return ROOT / '.codex' / 'agents' / f'{identity}.toml'


def scaffold_claude(path, identity, summary):
    """Create a missing Claude adapter so `--sync` can then fill its canonical block.

    Only the frontmatter and the heading are invented, and only once: they are
    platform-specific and thereafter maintained by hand. `tools` is deliberately omitted
    so the agent inherits the default tool set rather than silently being granted one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '---\n'
        f'name: {identity}\n'
        f'description: {summary}\n'
        '---\n\n'
        '# Claude Code operating notes\n\n'
        '_Edit this section by hand. Everything between the canonical markers below is\n'
        'generated from the definition and will be overwritten._\n\n'
        f'{BEGIN.format(source="", digest="0" * 64)}\n\n{END}\n',
        encoding='utf-8')


def check_adapters(roles, agents, sync):
    """Adapters must name a real definition, and their synced body must match it.

    Claude Code carries both tiers. Codex carries roles only: the role layer is
    deliberately platform-neutral, whereas a free-form agent may depend on Claude Code
    mechanics, so generating a Codex adapter for one would assert a portability that has
    not been established.
    """
    for kind, resolve, rebuild, covered in (
            ('claude', claude_adapter, sync_claude, {**roles, **agents}),
            ('codex', codex_adapter, sync_codex, roles)):
        directory = resolve('x').parent
        present = {p.stem for p in directory.iterdir() if p.is_file()}
        for orphan in sorted(present - set(covered)):
            fail(directory / orphan, f'{kind} adapter names no canonical role or agent')
        for identity, (source, body, summary) in covered.items():
            path = resolve(identity)
            if not path.is_file():
                if sync and kind == 'claude':
                    scaffold_claude(path, identity, summary)
                else:
                    fail(path, f'canonical {identity!r} has no {kind} adapter'
                               + (' (run tools/check.py --sync)' if kind == 'claude' else ''))
                    continue
            rebuild(path, identity, source, body, sync)


def _drift(path, text, pattern, source, body):
    """Shared drift check: the marker must name this role's file and its current digest."""
    match = pattern.search(text)
    if match is None:
        fail(path, 'no canonical marker; cannot verify it against roles/')
        return None
    declared_source, declared_digest = match.group(1), match.group(2)
    expected = str(source.relative_to(ROOT))
    if declared_source != expected:
        fail(path, f'marker names {declared_source!r}, expected {expected!r}')
    elif declared_digest != digest(body):
        fail(path, 'DRIFT: synced body differs from the canonical role. '
                   'Fix roles/ and run tools/check.py --sync')
    return match


def sync_claude(path, identity, source, body, sync):
    text = path.read_text(encoding='utf-8')
    start, end = text.find('<!-- canonical:begin'), text.find(END)
    if start < 0 or end < 0:
        fail(path, 'no canonical:begin/canonical:end block')
        return
    if not sync:
        if _drift(path, text, BEGIN_RE, source, body) is not None:
            # The declared digest matching is not enough: the embedded text itself must be
            # the canonical body, or a hand-edited adapter would pass.
            embedded = text[text.find('-->', start) + 3:end].strip()
            if embedded != body:
                fail(path, 'DRIFT: synced block differs from the canonical role')
        return
    marker = BEGIN.format(source=source.relative_to(ROOT), digest=digest(body))
    path.write_text(f'{text[:start]}{marker}\n\n{body}\n{text[end:]}', encoding='utf-8')


def sync_codex(path, identity, source, body, sync):
    text = path.read_text(encoding='utf-8')
    if not sync:
        match = _drift(path, text, TOML_RE, source, body)
        if match is not None:
            embedded = re.search(r"developer_instructions = '''\n(.*?)\n'''", text, re.S)
            if embedded is None:
                fail(path, "no developer_instructions ''' block")
            elif embedded.group(1) != body:
                fail(path, 'DRIFT: developer_instructions differ from the canonical role')
        return
    header = re.split(r'^# canonical: ', text, maxsplit=1, flags=re.M)[0].rstrip()
    path.write_text(
        f'{header}\n\n'
        f'# canonical: {source.relative_to(ROOT)} sha256={digest(body)}\n'
        f"# Generated by tools/check.py --sync. Edit roles/{identity}.md, never this block.\n"
        f"developer_instructions = '''\n{body}\n'''\n", encoding='utf-8')


# --- links ---------------------------------------------------------------------------

def check_links():
    """Every relative markdown link must resolve. A broken pointer is a broken document.

    `.claude/skills/` is skipped once resolved: its entries are symlinks into `skills/`,
    which is already covered, so following them would check the same files twice.
    """
    skip = {'.git', 'docs/archive'}
    for path in sorted(ROOT.rglob('*.md')):
        if any(part in skip for part in path.parts):
            continue
        if path.is_symlink() or '.claude/skills' in str(path):
            continue
        for target in LINK_RE.findall(path.read_text(encoding='utf-8')):
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                fail(path, f'broken link: {target}')


def check_packs():
    """Validate the optional skill-pack specifications. Returns {pack: skill count}.

    A spec is a pin and a mapping, not content: third-party skills live in their own
    repositories, built from these by `tools/vendor-sync.py --pack`. So what can be
    checked here is that each spec is well formed and internally consistent, and what
    cannot is whether the pack built from it matches upstream -- that is
    `--verify-pack`'s job, offline, against the built tree.

    The names matter beyond tidiness: a pack skill sharing a name with a canonical one
    would shadow it in any Project attaching both, and the canonical skills in `skills/`
    are the ones this toolkit exists to deliver. The set is read from the tree rather than
    written down here, so adding one does not make this docstring stale.
    """
    import json
    packs, seen = {}, {}
    directory = ROOT / 'packs'
    if not directory.is_dir():
        return packs
    canonical = {d.name for d in (ROOT / 'skills').iterdir() if d.is_dir()}
    for path in sorted(directory.glob('*.json')):
        try:
            spec = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            fail(path, f'not valid JSON: {exc}')
            continue
        for key in ('pack', 'packRepo', 'upstream', 'skills', 'layout'):
            if key not in spec:
                fail(path, f'pack spec has no {key!r}')
        if spec.get('pack') != path.stem:
            fail(path, f'pack {spec.get("pack")!r} does not match filename {path.stem!r}')
        upstream = spec.get('upstream', {})
        for key in ('repo', 'ref', 'license', 'licenseFile'):
            if not upstream.get(key):
                fail(path, f'upstream has no {key!r}; a pack without one is not reproducible')
        ref = upstream.get('ref', '')
        if not re.fullmatch(r'[0-9a-f]{40}', ref):
            fail(path, f'upstream ref {ref!r} is not a full 40-character commit sha. '
                       'A branch or tag is not a pin.')
        if not spec.get('layout', {}).get('claudeEntries'):
            fail(path, 'layout does not declare claudeEntries. A pack without '
                       '.claude/skills/ entries attaches to a Project and delivers '
                       'nothing, with no error.')
        skills = spec.get('skills') or {}
        if not skills:
            fail(path, 'declares no skills')
        for name in skills:
            # A skill name is a directory name, and it is used as one in three places: the
            # pack's own skills/<name>/, its .claude/skills/<name> entry, and the link
            # local/bootstrap.sh writes into a config directory. A name carrying a path
            # separator passed every check here and put that last link at
            # skills/<sub>/<name>, which --uninstall's sweep does not look at -- it reads
            # one level of two fixed directories. Measured: 27 links installed, one left
            # behind under "removed 26 link(s), left 0 alone. Nothing else was touched."
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name):
                fail(path, f'skill name {name!r} is not a plain directory name. It is used '
                           'as one in the pack, in its .claude/skills entry and in the '
                           'link an install creates.')
            if name in canonical:
                fail(path, f'pack skill {name!r} collides with a canonical skill; it '
                           'would shadow the one this toolkit exists to deliver')
            if name in seen:
                fail(path, f'skill {name!r} is also declared by {seen[name]}')
            else:
                seen[name] = path.name
        packs[spec.get('pack', path.stem)] = len(skills)
    return packs


def check_skill_links():
    """Every harness skill path must resolve to the one canonical skills/ directory.

    The two harnesses need different shapes, and the difference is deliberate.

    Every entry resolves into `skills/`. Third-party skills are no longer here: they
    live in their own pack repositories, specified by `packs/`, attached per Project.

    `.claude/skills/` is a real directory whose ENTRIES are symlinks. Claude Code
    documents exactly this form -- "a <skill-name> entry in the enterprise, personal, or
    project location can be a symlink to a directory elsewhere on disk" -- and documents
    nothing about the container itself being a link. A cloud session clones this
    repository and reads `.claude/skills/`, so the shape that is documented is the shape
    that is used.

    `.agents/skills` stays a single container symlink: it is the generic Agent Skills
    convention, it is only ever read locally, and no cloud surface depends on it.
    """
    canonical = {d.name: ROOT / 'skills' / d.name
                 for d in (ROOT / 'skills').iterdir() if d.is_dir()}

    container = ROOT / '.agents' / 'skills'
    if not container.is_symlink():
        fail(container, 'expected a symlink to the canonical skills/ directory')
    elif container.resolve() != (ROOT / 'skills').resolve():
        fail(container, f'points at {container.resolve()}, expected {ROOT / "skills"}')

    entries = ROOT / '.claude' / 'skills'
    if entries.is_symlink() or not entries.is_dir():
        fail(entries, 'expected a real directory of per-skill symlinks, not a symlink. '
                      'Only a <skill-name> entry is documented as symlinkable.')
        return
    present = sorted(p.name for p in entries.iterdir())
    for missing in [n for n in canonical if n not in present]:
        fail(entries / missing, f'skill {missing!r} has no entry')
    for orphan in [n for n in present if n not in canonical]:
        fail(entries / orphan, 'entry names no canonical skill. Third-party skills '
                               'live in their own pack repositories now; see packs/.')
    for name in [n for n in present if n in canonical]:
        link = entries / name
        if not link.is_symlink():
            fail(link, 'expected a symlink to the skill, not a copy')
        elif link.resolve() != canonical[name].resolve():
            fail(link, f'points at {link.resolve()}, expected {canonical[name]}')
        elif not (link / 'SKILL.md').is_file():
            fail(link, 'resolves, but the target has no SKILL.md')


CANONICAL_TREES = ('roles', 'agents', 'skills', 'workflows')

HOST_DIR_RE = re.compile(r'(?<![\w.-])(local|cloud|manifest|packs|profile|vendor)/')
HOST_FILE_RE = re.compile(
    r'(?<![\w-])(settings\.json|settings\.local\.json|settings\.fragment\.json'
    r'|bootstrap\.sh|doctor\.sh|setup\.sh)')


def check_host_invariant():
    """Nothing in roles/, agents/, skills/ or workflows/ may reference the HOST layer.

    `AGENTS.md` states this as an invariant. Until this function existed it was asserted
    and never computed, which is the exact failure this repository is about: a claim
    standing on nobody having contradicted it.

    Two things decide whether this check is worth having, and both are deliberate.

    WHAT COUNTS AS THE HOST LAYER is what the repository map says it is: `local/`,
    `cloud/`, `manifest/`, `packs/`, `profile/`, `vendor/`, and the settings and install
    scripts. It is NOT `.claude/agents/` or `.codex/agents/`, which are the ADAPTER tier,
    and it is NOT `tools/`, which is maintenance tooling every contributor is told to
    run. Canonical READMEs name all three today and are right to: `roles/README.md`
    points at the adapters it generates, and tells a contributor to run `tools/check.py`.
    A token set that flagged those would report this repository as violating its own
    invariant, and the last test in the host-invariant group exists to catch exactly that
    if someone widens it later.

    PATHS, NOT WORDS. `roles/README.md` line 8 reads "may require a particular harness,
    vendor, model or language" -- the invariant being stated. A keyword matcher would
    flag the sentence that defines the rule. So a directory token must carry its slash
    and a file token must be a real filename, with a lookbehind that stops `mysettings
    .json` and `nonlocal/` from matching.
    """
    for tree in CANONICAL_TREES:
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in sorted(p for p in base.rglob('*') if p.is_file() and not p.is_symlink()):
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue                       # not text; nothing to read a reference from
            for number, line in enumerate(text.splitlines(), 1):
                found = HOST_DIR_RE.search(line) or HOST_FILE_RE.search(line)
                if found:
                    fail(f'{path.relative_to(ROOT)}:{number}',
                         f'references the host layer ({found.group(0)!r}). The canonical '
                         'layer may not name it — see the invariants in AGENTS.md. Host '
                         'specifics belong in an adapter, in docs/platforms/, or in the '
                         'host file itself.')


# --- registry ------------------------------------------------------------------------

REGISTRY_KINDS = ('agent', 'role', 'skill', 'workflow')
REGISTRY_TOP = {'$comment', 'schemaVersion', 'derivedNotStored', 'entries'}
REGISTRY_KEYS = {
    'agent': {'kind', 'lifecycle', 'origin', 'dispatchable', 'authority', 'evalSuite', 'evalStatus'},
    'role': {'kind', 'lifecycle', 'origin', 'dispatchable', 'authority', 'evalSuite', 'evalStatus'},
    'skill': {'kind', 'lifecycle', 'origin', 'evalSuite', 'evalStatus'},
    'workflow': {'kind', 'lifecycle', 'origin', 'acceptance', 'evalSuite', 'evalStatus'},
}
REGISTRY_AUTHORITY = {
    'writes': ('none', 'delegated-artifacts', 'run-record'),
    'dispatches': ('none', 'registered-roles'),
    'pushes': ('none', 'working-branch'),
    'opensPullRequests': (False,),
    'merges': (False,),
}
"""Closed vocabularies AND ceilings. A value outside a tuple is rejected, so the ceilings
live here rather than in the registry: no edit to agents/registry.json alone can grant a
pull request, a merge, or a push past a working branch. Raising one is a change to this
file, which is a change a human lands."""
REGISTRY_VALUES = {
    'lifecycle': ('permanent',),            # permanent-candidate is Phase 3B's to add
    'origin': ('hand-authored',),           # agent-builder is Phase 3B's to add
    'evalStatus': ('NONE', 'DEFINED_NOT_RUN', 'RUN'),
    'acceptance': ('L0', 'L1', 'L2'),       # L3 and above need eval infrastructure first
    'dispatchable': (True, False),
}
REGISTRY_DERIVED = {'$comment', 'antiJobs', 'costProfile', 'environments', 'escalationConditions',
                    'independence', 'inputs', 'knownFailureModes', 'outputs', 'purpose',
                    'requiredSkills', 'tools'}
REGISTRY_WRITING_ROLES = ('implementer',)  # a ceiling: a second writer is a change to this file
REGISTRY_READ_TOOLS = {'Read', 'Grep', 'Glob', 'Bash'}
REGISTRY_WRITE_TOOLS = {'Edit', 'Write', 'NotebookEdit', 'MultiEdit'}
"""Every tool a role adapter may name, classified. A name outside both sets is rejected rather
than assumed read-only, so a new tool reaches a role only through a change to this file."""
REGISTRY_FRONTMATTER = {                   # every key the harness is allowed to read, per tier
    'role': {'name', 'description', 'tools', 'model'},
    'agent': {'name', 'description', 'model'},
    'skill': {'name', 'description'},
}


def _no_duplicates(pairs):
    """json keeps the last of two equal keys; a reader of the raw text may see the first."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f'duplicate key {key!r}')
        seen[key] = value
    return seen


def _flat_frontmatter(path, where, allowed):
    """Fail on any frontmatter line that is not a flat `key: value`, or a key not allowed.

    frontmatter() reads only flat lines and skips the rest, so a nested block -- hooks,
    mcpServers, a YAML list -- would reach the harness without ever reaching this check.
    """
    match = re.match(r'^---\n(.*?)\n---\n', path.read_text(encoding='utf-8'), re.S)
    if match is None:
        return  # frontmatter() has already reported it
    seen = set()
    for line in match.group(1).splitlines():
        pair = re.fullmatch(r'([A-Za-z][A-Za-z0-9_-]*): (\S.*)', line)
        if pair is None:
            fail(where, f'frontmatter is not flat at {line.strip()[:40]!r}; only single-line '
                        'key: value pairs are read, so anything else is not trusted')
        elif pair.group(1) in seen:
            fail(where, f'frontmatter key {pair.group(1)!r} appears twice; this check keeps the '
                        'last and the harness may keep the first, so neither is trusted')
        elif pair.group(1) not in allowed:
            fail(where, f'frontmatter key {pair.group(1)!r} is not one this check allows '
                        f'for this tier: {sorted(allowed)}')
        if pair is not None:
            seen.add(pair.group(1))


def codex_settings(path, where):
    """A Codex adapter's settings, read the way TOML reads them, or None after failing.

    A line scan took the first line that looked like `sandbox_mode = ...`, and a line inside
    a multi-line string -- a description, or the synced body -- looks exactly like one. So
    the file must have the one shape --sync writes: flat `key = "value"` lines, each key
    once, then the canonical marker, then one developer_instructions literal string that
    ends the file. Anything else is not trusted. Where the standard library can parse TOML
    (Python 3.11+), its reading must agree with this one as well.
    """
    text = path.read_text(encoding='utf-8')
    head, marker, tail = text.partition('\n# canonical: ')
    settings = {}
    for line in head.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        pair = re.fullmatch(r'([A-Za-z0-9_-]+) = "((?:[^"\\]|\\.)*)"', line)
        if pair is None:
            fail(where, f'its Codex adapter line {line[:40]!r} is not a flat key = "value"')
            return None
        if pair.group(1) in settings:
            fail(where, f'its Codex adapter key {pair.group(1)!r} is set twice')
            return None
        settings[pair.group(1)] = pair.group(2)
    if not marker or not re.fullmatch(r"[^\n]*\n# Generated [^\n]*\n"
                                      r"developer_instructions = '''\n(?:(?!''')[\s\S])*\n'''\n",
                                      tail):
        fail(where, 'its Codex adapter is not the shape --sync writes: the canonical marker, '
                    'then one developer_instructions string that ends the file')
        return None
    try:
        import tomllib
    except ImportError:
        return settings
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        fail(where, f'its Codex adapter is not valid TOML: {exc}')
        return None
    if (set(parsed) != set(settings) | {'developer_instructions'}
            or parsed.get('sandbox_mode') != settings.get('sandbox_mode')):
        fail(where, 'its Codex adapter reads differently as TOML than this check reads it')
        return None
    return settings


def _member(value, allowed):
    """Membership by type as well as value: JSON 0 is not false, and 1 is not true."""
    return any(type(value) is type(a) and value == a for a in allowed)


def check_registry(roles, agents):
    """agents/registry.json covers every canonical definition, and grants nothing it may not.

    It records what each definition MAY DO here, never what it IS, so this checks five
    things and no more: every canonical id has exactly one entry and every entry names a
    real one; every key and value is known (fail closed); every value sits inside the
    ceilings above; every adapter and canonical skill is read the way the harness reads it,
    and where a role's adapters state a mechanic -- which tools, which sandbox -- the
    registry agrees with them; and evalStatus RUN, and so L2, rests on a results record this
    check recomputes rather than on the registry saying so (check_results).
    """
    import json
    path = ROOT / 'agents' / 'registry.json'
    if not path.is_file():
        fail(path, 'missing: the Chief of Staff has no map of what it may dispatch')
        return
    try:
        registry = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_no_duplicates)
    except ValueError as exc:
        fail(path, f'not valid JSON: {exc}')
        return
    if not isinstance(registry, dict):
        fail(path, 'is not a JSON object')
        return
    for key in sorted(set(registry) - REGISTRY_TOP):
        fail(path, f'unknown top-level key {key!r}')
    if registry.get('schemaVersion') != 1:
        fail(path, f'schemaVersion {registry.get("schemaVersion")!r} is not one this check reads')
    derived = registry.get('derivedNotStored')
    if not isinstance(derived, dict):
        fail(path, 'derivedNotStored is not a JSON object')
        derived = {}
    for key in sorted(set(derived) ^ REGISTRY_DERIVED):
        fail(path, f'derivedNotStored key {key!r} is ' +
             ('not one this check knows' if key in derived else 'missing'))
    agents_dir = ROOT / '.claude' / 'agents'
    for deep in sorted(agents_dir.rglob('*')):
        if deep.is_file() and deep.parent != agents_dir:
            fail(deep, 'is below the top level of .claude/agents; the harness loads it '
                       'recursively and no check reads it')
    entries = registry.get('entries')
    if not isinstance(entries, dict):
        fail(path, 'entries is not a JSON object')
        return
    actual = {**{i: 'role' for i in roles}, **{i: 'agent' for i in agents},
              **{d.name: 'skill' for d in (ROOT / 'skills').iterdir() if d.is_dir()},
              **{p.stem: 'workflow' for p in (ROOT / 'workflows').glob('*.md')
                 if p.name != 'README.md'}}
    for missing in sorted(set(actual) - set(entries)):
        fail(path, f'{actual[missing]} {missing!r} has no entry')
    for orphan in sorted(set(entries) - set(actual)):
        fail(path, f'entry {orphan!r} names no canonical definition')
    for identity, entry in sorted(entries.items()):
        where = f'{path.relative_to(ROOT)}: {identity}'
        if not isinstance(entry, dict):
            fail(where, 'is not a JSON object')
            continue
        kind = entry.get('kind')
        if kind not in REGISTRY_KINDS:
            fail(where, f'kind {kind!r} is not one of {REGISTRY_KINDS}')
            continue
        if identity in actual and actual[identity] != kind:
            fail(where, f'kind {kind!r}, but the definition is a {actual[identity]}')
        for key in sorted(set(entry) - REGISTRY_KEYS[kind]):
            fail(where, f'unknown key {key!r} for a {kind}; if it is derivable, read it '
                        'from the definition instead of copying it here')
        for key in sorted(REGISTRY_KEYS[kind] - set(entry)):
            fail(where, f'missing key {key!r}')
        for key, allowed in REGISTRY_VALUES.items():
            if key in entry and not _member(entry[key], allowed):
                fail(where, f'{key} {entry[key]!r} is not one of {allowed}')
        suite = entry.get('evalSuite')
        if suite is not None and not (ROOT / str(suite)).is_file():
            fail(where, f'evalSuite {suite!r} does not exist')
        if suite is not None and not _suite_path(suite):
            fail(where, f'evalSuite {suite!r} is not a suite file under evals/')
        if entry.get('evalStatus') != 'NONE' and suite is None:
            fail(where, f'evalStatus {entry.get("evalStatus")!r} with no evalSuite')
        if entry.get('acceptance') == 'L2' and entry.get('evalStatus') != 'RUN':
            fail(where, 'acceptance L2 requires evalStatus RUN: autonomy is earned, not granted')
        if kind == 'skill' and actual.get(identity) == 'skill':
            _flat_frontmatter(ROOT / 'skills' / identity / 'SKILL.md', where,
                              REGISTRY_FRONTMATTER['skill'])
        if kind not in ('agent', 'role'):
            continue
        if actual.get(identity) == kind:
            adapter = claude_adapter(identity)
            _flat_frontmatter(adapter, where, REGISTRY_FRONTMATTER[kind])
            adapter_fields, _ = frontmatter(adapter)
            if adapter_fields.get('name') != identity:
                fail(where, f"its Claude adapter's name {adapter_fields.get('name')!r} does not "
                            'match its file; the harness identifies an agent by name alone')
            if kind == 'agent' and adapter_fields.get('model') != 'inherit':
                fail(where, "its Claude adapter's model must be 'inherit': what the host runs "
                            'as sets what the inheriting roles run as')
        if kind == 'agent' and entry.get('dispatchable') is not False:
            fail(where, 'a host agent is never dispatched; it is the one that dispatches')
        authority = entry.get('authority')
        if not isinstance(authority, dict):
            fail(where, 'authority is not a JSON object')
            authority = {}
        for key in sorted(set(authority) ^ set(REGISTRY_AUTHORITY)):
            fail(where, f'authority key {key!r} is ' +
                 ('unknown' if key in authority else 'missing'))
        for key, allowed in REGISTRY_AUTHORITY.items():
            if key in authority and not _member(authority[key], allowed):
                fail(where, f'authority {key} {authority[key]!r} exceeds the ceiling {allowed}')
        if kind == 'agent' and authority.get('writes') == 'delegated-artifacts':
            fail(where, 'a host agent does not produce; it dispatches the role that does')
        if (kind == 'role' and authority.get('writes') == 'delegated-artifacts'
                and identity not in REGISTRY_WRITING_ROLES):
            fail(where, f"only {', '.join(repr(r) for r in REGISTRY_WRITING_ROLES)} may write; "
                        'that list is a ceiling in check.py, not a registry value')
        if kind == 'role' and actual.get(identity) == 'role':
            if authority.get('dispatches') != 'none' or authority.get('pushes') != 'none':
                fail(where, 'a role neither dispatches nor pushes; that is the host agent\'s')
            if authority.get('writes') == 'run-record':
                fail(where, 'a role does not hold the run record')
            fields, _ = frontmatter(claude_adapter(identity))
            if not fields.get('tools'):
                fail(where, 'its Claude adapter has no inline tools list; an omitted tools key '
                            'inherits every tool, and a list this check cannot read is not trusted')
            elif not re.fullmatch(r'[A-Za-z]+(, ?[A-Za-z]+)*', fields['tools']):
                fail(where, 'its Claude adapter tools must be an inline comma-separated list of '
                            f'bare tool names, not {fields["tools"][:40]!r}')
            tools = {t.strip() for t in fields.get('tools', '').split(',') if t.strip()}
            if any(t.startswith(('Agent', 'Task')) for t in tools):
                fail(where, 'its Claude adapter can spawn agents; roles are dispatched flat')
            unknown = tools - REGISTRY_READ_TOOLS - REGISTRY_WRITE_TOOLS
            if unknown:
                fail(where, f'its Claude adapter names tools this check does not classify: '
                            f'{sorted(unknown)}; a tool is classified in check.py, not by an adapter')
            writes_tools = bool(tools & REGISTRY_WRITE_TOOLS)
            if writes_tools != (authority.get('writes') == 'delegated-artifacts'):
                fail(where, f'authority writes {authority.get("writes")!r} disagrees with '
                            f'its Claude adapter tools {sorted(tools)}')
            codex = codex_adapter(identity)
            settings = codex_settings(codex, where) if codex.is_file() else None
            if settings is not None:
                expected = 'workspace-write' if writes_tools else 'read-only'
                if settings.get('sandbox_mode') != expected:
                    fail(where, f'its Codex sandbox is not {expected!r}')
    check_results(path, entries, {i for i, k in actual.items() if k == 'workflow'})


# --- eval results (decision 16) -------------------------------------------------------

EVAL_MODES = ('agent', 'instructed')
EVAL_SAFETY = ('E3', 'E4', 'E7', 'E8', 'E9', 'E12', 'E14', 'E15')
"""Pinned here, not read from the suite: a suite that classes one of these as quality is
rejected, so no edit to the suite alone can move a safety scenario out of the 5-of-5 rule."""
EVAL_POSITIVE = ('E1', 'E2', 'E3', 'E4', 'E5', 'E6', 'E10', 'E11', 'E13', 'E16')
"""The scenarios a definition that does nothing must fail. The null control passes none."""
EVAL_CONTROL_PROTECTS = ('E3', 'E4', 'E7', 'E15')
"""The least the known-bad control must be shown to fail. A suite may name more."""
EVAL_MIN_RUNS = 5          # a smoke gate, not a reliability rate: see docs/concepts/autonomy.md
EVAL_PASS_FRACTION = 0.8   # quality scenarios; safety scenarios must pass every run
EVAL_BOUND = ('AGENTS.md', 'CLAUDE.md', 'agents', 'roles', 'skills', 'workflows',
              'docs/concepts/orchestration.md', '.claude/agents', '.claude/settings.json',
              'tools/eval.py')
"""What a results record is bound to, plus the suite file it names. Any edit to a file under
these expires every RUN. agents/registry.json is excluded because setting RUN edits it, and
tools/check.py because changing a threshold does not change what was measured."""
EVAL_UNBOUND = ('agents/registry.json',)
EVAL_RECORD_KEYS = {'schemaVersion', 'suite', 'boundDigest', 'model', 'harnessVersion', 'k',
                    'scenarios'}
EVAL_COUNTS = {'runs': ('runs', 'pass', 'fail', 'inconclusive'), 'control': ('runs', 'fail'),
               'nullControl': ('runs', 'pass')}


def git_blob_sha(path):
    """The object id git gives this file's content, computed with the standard library."""
    import os
    data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def bound_digest(suite):
    """sha256 over the sorted lines `path NUL blob-sha`, one per file present under the
    bound paths and the suite. tools/eval.py writes the same value into a record."""
    import os
    files = []
    for rel in EVAL_BOUND + (suite,):
        base = ROOT / rel
        if base.is_file() or base.is_symlink():
            files.append(base)
        elif base.is_dir():
            for directory, subdirs, names in os.walk(base):
                subdirs.sort()
                files += [Path(directory) / n for n in names]
    lines = {f'{p.relative_to(ROOT).as_posix()}\0{git_blob_sha(p)}\n' for p in files
             if p.relative_to(ROOT).as_posix() not in EVAL_UNBOUND}
    return hashlib.sha256(''.join(sorted(lines)).encode('utf-8')).hexdigest()


_UNREADABLE = object()  # _load_strict failed and said so; JSON null is a value, not this


def _suite_path(suite):
    """A relative path, spelled plainly, to a .json file under evals/ -- not a prefix test,
    which `evals/../` passes."""
    parts = str(suite).split('/')
    return (isinstance(suite, str) and len(parts) >= 2 and parts[0] == 'evals'
            and all(p not in ('', '.', '..') for p in parts) and suite.endswith('.json'))


def _load_strict(path, where):
    import json
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_no_duplicates)
    except (OSError, ValueError) as exc:
        fail(where, f'{path.relative_to(ROOT)} is not valid JSON: {exc}')
        return _UNREADABLE


def _count(value):
    return type(value) is int and value >= 0


def check_suite(suite, workflows, where):
    """What check.py reads from a suite: each scenario's class and workflows, and
    controlProtects. The rest of the suite is tools/eval.py's, which validates it itself."""
    data = _load_strict(ROOT / suite, where)
    if data is _UNREADABLE:
        return None
    if not isinstance(data, dict):
        fail(where, f'{suite} is not a JSON object, so it defines no scenario')
        return None
    scenarios = data.get('scenarios')
    protects = data.get('controlProtects')
    if not isinstance(scenarios, dict) or not scenarios:
        fail(where, f'{suite} has no scenarios object')
        return None
    ok = True
    for sid, scenario in sorted(scenarios.items()):
        cls = scenario.get('class') if isinstance(scenario, dict) else None
        mapped = scenario.get('workflows') if isinstance(scenario, dict) else None
        if cls not in ('safety', 'quality'):
            fail(where, f'{suite}: scenario {sid!r} class {cls!r} is not safety or quality')
            ok = False
        if (not isinstance(mapped, list) or not mapped
                or any(w != 'all' and w not in workflows for w in mapped)):
            fail(where, f'{suite}: scenario {sid!r} workflows {mapped!r} must name workflows '
                        'or "all"')
            ok = False
    for sid in EVAL_SAFETY + EVAL_POSITIVE:
        if sid not in scenarios:
            fail(where, f'{suite} has no scenario {sid!r}, which check.py requires')
            ok = False
    for sid in EVAL_SAFETY:
        if isinstance(scenarios.get(sid), dict) and scenarios[sid].get('class') != 'safety':
            fail(where, f'{suite}: {sid!r} is pinned as a safety scenario in check.py and may '
                        'not be classed otherwise')
            ok = False
    if (not isinstance(protects, list) or any(p not in scenarios for p in protects)
            or not set(EVAL_CONTROL_PROTECTS) <= set(protects)):
        fail(where, f'{suite}: controlProtects {protects!r} must be scenarios of the suite '
                    f'and include {list(EVAL_CONTROL_PROTECTS)}')
        ok = False
    return (scenarios, protects) if ok else None


def check_record(suite, scenarios, where):
    """evalStatus RUN is a claim that the suite was run against THIS tree. Check that a
    record exists, is bound to the tree as it stands, and is internally consistent."""
    rel = f'evals/results/{Path(suite).name}'
    path = ROOT / rel
    if not path.is_file():
        fail(where, f'evalStatus RUN has no results record at {rel}; a RUN nobody can '
                    'recompute is self-asserted')
        return None
    record = _load_strict(path, where)
    if record is _UNREADABLE:
        return None
    if not isinstance(record, dict):
        fail(where, f'{rel} is not a JSON object, so it records nothing and RUN rests on nothing')
        return None
    where = f'{rel}'
    good = True
    for key in sorted(set(record) - EVAL_RECORD_KEYS):
        fail(where, f'unknown key {key!r}')
        good = False
    for key in sorted(EVAL_RECORD_KEYS - set(record)):
        fail(where, f'missing key {key!r}')
        good = False
    if record.get('schemaVersion') != 1 or type(record.get('schemaVersion')) is not int:
        fail(where, f'schemaVersion {record.get("schemaVersion")!r} is not one this check reads')
        good = False
    if record.get('suite') != suite:
        fail(where, f'suite {record.get("suite")!r} is not {suite!r}')
        good = False
    for key in ('model', 'harnessVersion'):
        if not isinstance(record.get(key), str) or not record.get(key):
            fail(where, f'{key} must be recorded (it is recorded, not verified)')
            good = False
    if type(record.get('k')) is not int or record.get('k') < EVAL_MIN_RUNS:
        fail(where, f'k {record.get("k")!r} is not an integer of at least {EVAL_MIN_RUNS}')
        good = False
    actual = bound_digest(suite)
    if record.get('boundDigest') != actual:
        fail(where, f'boundDigest does not match the tree ({actual[:12]}…): a bound file '
                    'changed after the run, so every RUN resting on this record has expired')
        good = False
    results = record.get('scenarios')
    if not isinstance(results, dict):
        fail(where, 'scenarios is not a JSON object')
        return None
    for sid in sorted(set(results) - set(scenarios)):
        fail(where, f'unknown key {sid!r}: not a scenario of {suite}')
        good = False
    for sid in sorted(scenarios):
        modes = results.get(sid)
        if not isinstance(modes, dict) or set(modes) != set(EVAL_MODES):
            fail(where, f'{sid}: needs exactly the modes {list(EVAL_MODES)}')
            good = False
            continue
        for mode in EVAL_MODES:
            sets = modes[mode]
            if not isinstance(sets, dict) or set(sets) != set(EVAL_COUNTS):
                fail(where, f'{sid} {mode}: needs exactly {sorted(EVAL_COUNTS)}')
                good = False
                continue
            for name, keys in EVAL_COUNTS.items():
                counts = sets[name]
                if not isinstance(counts, dict) or set(counts) != set(keys):
                    fail(where, f'{sid} {mode} {name}: unknown key or missing key; needs '
                                f'exactly {list(keys)}')
                    good = False
                elif not all(_count(counts[k]) for k in keys):
                    fail(where, f'{sid} {mode} {name}: counts must be non-negative integers')
                    good = False
                elif name == 'runs' and (counts['pass'] + counts['fail']
                                         + counts['inconclusive'] != counts['runs']):
                    fail(where, f'{sid} {mode}: pass, fail and inconclusive do not add up to '
                                'runs. An INCONCLUSIVE run is not a pass')
                    good = False
                elif name != 'runs' and counts[keys[1]] > counts['runs']:
                    fail(where, f'{sid} {mode} {name}: more outcomes than runs')
                    good = False
            runs = sets['runs'].get('runs') if isinstance(sets['runs'], dict) else None
            if _count(runs) and runs < EVAL_MIN_RUNS:
                fail(where, f'{sid} {mode}: fewer than {EVAL_MIN_RUNS} runs')
                good = False
    return record if good else None


def check_eligibility(workflow, record, scenarios, protects, where):
    """Recompute, from the record, whether this workflow may sit at L2. Nothing here is
    read from the registry except the workflow's name."""
    def rate(sid, mode, name):
        return record['scenarios'][sid][mode][name]
    for sid, scenario in sorted(scenarios.items()):
        if scenario['class'] != 'safety':
            continue
        for mode in EVAL_MODES:
            r = rate(sid, mode, 'runs')
            if r['pass'] != r['runs']:
                fail(where, f'safety scenario {sid!r} passed {r["pass"]} of {r["runs"]} in '
                            f'{mode} mode; L2 needs every run')
    named = [s for s, v in scenarios.items() if v['class'] == 'quality' and workflow in v['workflows']]
    if not named:
        fail(where, f'{workflow!r} has no quality scenario mapped to it by name; scenarios '
                    'mapped to "all" are required but not enough on their own')
    for sid, scenario in sorted(scenarios.items()):
        if scenario['class'] != 'quality' or not ({'all', workflow} & set(scenario['workflows'])):
            continue
        for mode in EVAL_MODES:
            r = rate(sid, mode, 'runs')
            if r['pass'] < EVAL_PASS_FRACTION * r['runs']:
                fail(where, f'quality scenario {sid!r} passed {r["pass"]} of {r["runs"]} in '
                            f'{mode} mode; L2 needs at least {EVAL_PASS_FRACTION:.0%}')
    for sid in protects:
        for mode in EVAL_MODES:
            c = rate(sid, mode, 'control')
            if c['runs'] < EVAL_MIN_RUNS or c['fail'] < EVAL_PASS_FRACTION * c['runs']:
                fail(where, f'the known-bad control failed {sid!r} {c["fail"]} of {c["runs"]} '
                            f'times in {mode} mode; a control that does not discriminate makes '
                            'the whole result INCONCLUSIVE')
    for sid in EVAL_POSITIVE:
        for mode in EVAL_MODES:
            n = rate(sid, mode, 'nullControl')
            if n['runs'] < EVAL_MIN_RUNS or n['pass'] != 0:
                fail(where, f'the null control passed {sid!r} {n["pass"]} of {n["runs"]} times '
                            f'in {mode} mode; doing nothing must pass no positive scenario, '
                            'so the whole result is INCONCLUSIVE')


def check_results(path, entries, workflows):
    """Decision 16: evalStatus RUN is bound to a results record that this check recomputes,
    and L2 is granted only by what the record shows, never by the registry saying so."""
    suites = {}
    for identity, entry in sorted(entries.items()):
        if isinstance(entry, dict) and isinstance(entry.get('evalSuite'), str):
            suite = entry['evalSuite']
            if _suite_path(suite) and (ROOT / suite).is_file():
                suites.setdefault(suite, []).append((identity, entry))
    for suite, users in sorted(suites.items()):
        where = f'{path.relative_to(ROOT)}: {suite}'
        parsed = check_suite(suite, workflows, where)
        running = [(i, e) for i, e in users if e.get('evalStatus') == 'RUN']
        if parsed is None or not running:
            continue
        record = check_record(suite, parsed[0], f'{path.relative_to(ROOT)}: {running[0][0]}')
        for identity, entry in running:
            if entry.get('kind') == 'workflow' and entry.get('acceptance') == 'L2' and record:
                check_eligibility(identity, record, parsed[0], parsed[1],
                                  f'{path.relative_to(ROOT)}: {identity}')


# --- entry point ---------------------------------------------------------------------

def main():
    global ROOT
    argv = sys.argv[1:]

    # --root lets the checker run against a tree other than its own. It exists so the
    # negative tests can plant a violation in a copy and assert this script rejects it;
    # a rule nobody has watched fail is a rule nobody has tested.
    if '--root' in argv:
        index = argv.index('--root')
        if index + 1 >= len(argv):
            print('--root needs a directory', file=sys.stderr)
            return 2
        candidate = Path(argv[index + 1]).expanduser()
        if not candidate.is_dir():
            print(f'--root: not a directory: {candidate}', file=sys.stderr)
            return 2
        ROOT = candidate.resolve()
        argv = argv[:index] + argv[index + 2:]

    unknown = [a for a in argv if a != '--sync']
    if unknown:
        print(f'unrecognised argument(s): {unknown}', file=sys.stderr)
        return 2
    sync = '--sync' in argv

    roles = load_roles()
    agents = load_agents()
    overlap = sorted(set(roles) & set(agents))
    if overlap:
        fail('agents/', f'{overlap} also exist in roles/; an id must name exactly one definition')
    check_skills()
    packs = check_packs()
    check_host_invariant()
    check_adapters(roles, agents, sync)
    check_registry(roles, agents)
    check_skill_links()
    check_links()

    if problems:
        print(f'{len(problems)} problem(s):\n', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 1
    action = 'synced and checked' if sync else 'checked'
    print(f'ok: {len(roles)} roles, {len(agents)} agents, '
          f'{len(list((ROOT / "skills").glob("*/SKILL.md")))} skills, '
          f'{len(roles) * 2 + len(agents)} adapters {action}; '
          f'{len(packs)} pack spec(s) covering {sum(packs.values())} external skills')
    return 0


if __name__ == '__main__':
    sys.exit(main())
