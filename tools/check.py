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

    `vendor/` is excluded. That content is third-party, materialised verbatim from a
    pinned upstream commit, and this repository has no authority to change it. Policing
    it would report defects that are upstream's and that a re-sync would restore --
    three such links exist in cloudflare/skills at the current pin. `.claude/skills/`
    is excluded for the same reason once resolved: its entries are symlinks into
    `skills/` and `vendor/`, both already covered.
    """
    skip = {'.git', 'docs/archive', 'vendor'}
    for path in sorted(ROOT.rglob('*.md')):
        if any(part in skip for part in path.parts):
            continue
        if path.is_symlink() or '.claude/skills' in str(path):
            continue
        for target in LINK_RE.findall(path.read_text(encoding='utf-8')):
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                fail(path, f'broken link: {target}')


def vendored_skills():
    """{name: path} for third-party skills committed under vendor/.

    Their content is not authored here; `tools/vendor-sync.py` materialises it from a
    pinned upstream commit and records provenance and licence beside it. They are
    committed rather than referenced because Claude Projects load skills from a cloned
    repository, and a manifest entry makes nothing available to a cloud session.
    """
    sources = ROOT / 'vendor' / 'sources.json'
    if not sources.is_file():
        return {}
    import json
    found = {}
    for source, spec in json.loads(sources.read_text())['sources'].items():
        for skill in spec['skills']:
            path = ROOT / 'vendor' / source / skill
            if not (path / 'SKILL.md').is_file():
                fail(path, 'declared in vendor/sources.json but has no SKILL.md; '
                           'run tools/vendor-sync.py --sync')
                continue
            found[skill] = path
    return found


def check_skill_links():
    """Every harness skill path must resolve to the one canonical skills/ directory.

    The two harnesses need different shapes, and the difference is deliberate.

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
    for name, path in vendored_skills().items():
        if name in canonical:
            fail(path, f'vendored skill {name!r} collides with a canonical skill of the '
                       'same name; one of them must be renamed')
        canonical[name] = path

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
        fail(entries / orphan, 'entry names no canonical or vendored skill')
    for name in [n for n in present if n in canonical]:
        link = entries / name
        if not link.is_symlink():
            fail(link, 'expected a symlink to the skill, not a copy')
        elif link.resolve() != canonical[name].resolve():
            fail(link, f'points at {link.resolve()}, expected {canonical[name]}')
        elif not (link / 'SKILL.md').is_file():
            fail(link, 'resolves, but the target has no SKILL.md')


# --- entry point ---------------------------------------------------------------------

def main():
    argv = sys.argv[1:]
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
    check_adapters(roles, agents, sync)
    check_skill_links()
    check_links()

    if problems:
        print(f'{len(problems)} problem(s):\n', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 1
    action = 'synced and checked' if sync else 'checked'
    print(f'ok: {len(roles)} roles, {len(agents)} agents, '
          f'{len(list((ROOT / "skills").glob("*/SKILL.md")))} skills '
          f'+ {len(vendored_skills())} vendored, '
          f'{len(roles) * 2 + len(agents)} adapters {action}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
