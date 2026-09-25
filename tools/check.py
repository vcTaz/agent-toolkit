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
        for nested in sorted(p for p in directory.iterdir() if p.is_dir()):
            # Measured at 2.1.282 by an independent validator: an agent file in a
            # subdirectory of .claude/agents/ loads in the project under its bare name,
            # and nothing below looks inside a subdirectory.
            fail(nested, f'a directory among the {kind} adapters. Nothing here checks '
                         'inside it, and Claude Code loads agents from a subdirectory '
                         'of .claude/agents/.')
        for identity, (source, body, summary) in covered.items():
            path = resolve(identity)
            if not path.is_file():
                if sync and kind == 'claude':
                    scaffold_claude(path, identity, summary)
                else:
                    fail(path, f'canonical {identity!r} has no {kind} adapter'
                               + (' (run tools/check.py --sync)' if kind == 'claude' else ''))
                    continue
            if kind == 'claude':
                # Claude Code registers an agent under its frontmatter `name`, not its file
                # name. Measured at 2.1.282: validator.md declaring `name: critic` left the
                # installed plugin offering seven agents, with no error anywhere. The same
                # mismatch renames the agent in the project directory too.
                fields = flat_frontmatter(path)
                declared = fields.get('name')
                if declared != identity:
                    fail(path, f'frontmatter name {declared!r} is not {identity!r}. Claude '
                               'Code registers the agent under that name, so a mismatch '
                               'renames it and a clash drops one, in this repository and '
                               'in the plugin (.claude-plugin/) alike.')
                for key in sorted(set(fields) - AGENT_KEYS):
                    fail(path, f'frontmatter key {key!r} is not one the adapters carry. '
                               'Claude Code acts on several subagent keys, and the plugin '
                               '(.claude-plugin/) delivers every adapter; add the key to '
                               'AGENT_KEYS if it is meant.')
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


# --- plugin packaging ----------------------------------------------------------------

PLUGIN_KEYS = {'name', 'description', 'version', 'author', 'homepage', 'repository',
               'license', 'keywords', 'agents'}
"""Metadata, plus `agents`. Every other plugin.json key is a component or a runtime."""

ENTRY_KEYS = {'name', 'source', 'description', 'version', 'author', 'homepage',
              'repository', 'license', 'keywords', 'category', 'tags'}
"""A marketplace entry may carry components too; with the default `strict` it must not."""

PLUGIN_DEFAULT_LOCATIONS = ('commands', 'hooks', 'output-styles', 'themes', 'monitors',
                            'bin', 'settings.json', '.mcp.json', '.lsp.json', 'package.json')
"""What Claude Code loads or acts on at a plugin root with no manifest key asking for it.
`package.json` is here because, beside a lockfile, it makes every install run npm."""

SKILL_KEYS = {'name', 'description', 'license', 'compatibility', 'metadata'}
"""The Agent Skills fields, less `allowed-tools`. Claude Code honours more, and some of
them act: `hooks` registers hooks for the rest of the session, `allowed-tools` grants
tools without asking, and `context`, `agent`, `model` and `effort` change who runs."""

AGENT_KEYS = {'name', 'description', 'tools', 'model'}
"""The fields the Claude adapters carry. Claude Code honours more in a subagent's
frontmatter, and the plugin delivers every adapter, so adding one is a decision made by
editing this set rather than by editing an adapter."""

CLAUDE_FRONTMATTER_RE = re.compile(r'---[ \t\r]*\n([\s\S]*?)---')
"""Claude Code 2.1.282's delimiter, read from its binary as `^---\\s*\\n([\\s\\S]*?)---`:
the block ends at the first `---` anywhere, mid-line included. Its opening `\\s*` is
narrowed here, because Python's `\\s` and JavaScript's are different sets -- a `---`
followed by U+001C opens a block here and none there -- and a narrower opening means a
block found here is one Claude Code finds too. `match` anchors it, as its `^` does."""

FLAT_LINE_RE = re.compile(r'([A-Za-z][A-Za-z0-9_-]*): (?![|>])(\S.*)')
"""An unindented `key: value` whose value is on its own line and is not a block scalar."""

YAML_MEANING_RE = re.compile(r'^[-|>\'"\[\]{}&*!%@#,?:`]|: | #|:$')
"""What gives a one-line YAML value a meaning beyond its text: a leading indicator, a
`: ` or ` #` inside it, a trailing colon. The value must also be printable, which rules
out tabs, a CR and the separators some YAML treats as line breaks. A value free of these
is a plain scalar, and YAML reads it as the text this script reads, give or take
surrounding whitespace. One with them can read differently or fail to parse, and a
frontmatter that fails to parse is one Claude Code falls back on in ways this script
cannot see."""

SHELL_MARKS = ('!`', '`!')
"""Claude Code 2.1.282 runs two forms of shell in a SKILL.md, read from its binary: an
inline `(?<=^|\\s)!` span, and a fence opened with three backticks and `!`. Refusing any
`!` beside a backtick covers both, whatever counts as whitespace and wherever a fence
sits. Adapters are held to it as well: inline shell in a plugin agent's body did not run
in one probe at 2.1.282, and one probe is not a reason to leave a runtime unguarded."""


def flat_frontmatter(path):
    """Frontmatter as Claude Code delimits it, readable ONLY if flat. Returns {key: value}.

    Claude Code parses this block as YAML. This script has no YAML parser and must not
    grow one, so it does not try to agree with YAML; it requires a shape where there is
    nothing to disagree about. Every non-blank line must be an unindented `key: value`,
    with no block scalars, no nesting, no duplicate keys, no quoting of keys and no
    value that YAML would read as more than its text. In that shape both see the same
    keys, and a name this script accepts is the name YAML reads. A first version read
    the block line by line, and an independent validator defeated it three ways at
    2.1.282 -- a nested `name:`, a `name:` inside a block scalar, and a `---` ending the
    block mid-line -- each with Claude Code reading a different name from this script's.
    Anything outside the flat shape is now a failure, not a guess.
    """
    text = path.read_text(encoding='utf-8')
    match = CLAUDE_FRONTMATTER_RE.match(text)
    if match is None:
        fail(path, 'no frontmatter where this script looks for it: a --- line at the very '
                   'start. Claude Code finds frontmatter by a wider pattern, here and in the '
                   'plugin (.claude-plugin/), so this script must find the same block.')
        return {}
    fields = {}
    for number, line in enumerate(match.group(1).split('\n'), 2):
        if not line.strip(' \t\r'):
            continue
        flat = FLAT_LINE_RE.fullmatch(line)
        if flat is None:
            fail(f'{path}:{number}', f'frontmatter line {line!r} is not an unindented '
                                     '`key: value`. Claude Code reads this block as YAML, '
                                     'here and in every session that installs the plugin '
                                     '(.claude-plugin/); only the flat shape reads the same '
                                     'way in this script.')
        elif YAML_MEANING_RE.search(flat.group(2)) or not flat.group(2).isprintable():
            fail(f'{path}:{number}', f'frontmatter value for {flat.group(1)!r} carries a '
                                     'character YAML gives meaning to (a leading indicator, '
                                     '": ", " #", a trailing colon or anything '
                                     'unprintable). Claude Code reads this block as YAML, '
                                     'here and in every session that installs the plugin '
                                     '(.claude-plugin/); reword the value as plain text.')
        elif flat.group(1) in fields:
            fail(f'{path}:{number}', f'frontmatter key {flat.group(1)!r} appears twice')
        else:
            fields[flat.group(1)] = flat.group(2)
    return fields


def check_plugin():
    """The repository root is a Claude Code plugin, listed by a one-plugin marketplace.

    The marketplace entry's source is `./`, so the plugin root IS the repository root.
    Everything Claude Code loads from a plugin root by default is therefore read from
    this tree, which is why the check looks at the tree and not only at the manifests.

    SKILLS come from the default `skills/` scan, which is the canonical directory. A
    `skills` key is refused: for an entry whose source is the marketplace root, listing
    skill directories REPLACES that scan, so a key naming some skills would silently drop
    the rest.

    AGENTS are listed file by file. The key replaces the default `agents/` scan, which is
    wanted -- `agents/` holds canonical definitions, and the adapters a session should
    get are in `.claude/agents/`. It has to be files: `claude plugin validate` rejects a
    directory there (2.1.282). So a new adapter is not delivered until it is listed, and
    that is a failure here rather than something a plugin user notices first.

    NOTHING CLAUDE CODE RUNS BY ITSELF. Hooks, MCP and LSP servers, commands, workflow
    scripts, executables, a root `settings.json` and install-time package dependencies
    would put a runtime into every session that installs the plugin, and AGENTS.md
    forbids adding one without a concrete need. The key allowlists and the scan of
    default locations make adding one a decision rather than an accident. The root is
    compared without case, because a `Hooks/` passes a case-sensitive test and may not
    pass a case-insensitive filesystem. `workflows/` is also the default location for
    workflow scripts, and here it holds this toolkit's Markdown workflows, so it may hold
    Markdown only.

    The delivered SKILLS are in scope too, and the first version of this check missed
    them. A skill's frontmatter can carry `hooks`, and its body can carry inline shell
    that runs when the skill loads. Both were measured reaching an installed session at
    2.1.282 with this check passing. A canonical skill has no business with either --
    they are Claude Code mechanics, and skills/ is portable -- so the frontmatter is held
    to the Agent Skills fields and inline shell is refused outright. The delivered
    adapters get the same shell rule, and their keys are held to AGENT_KEYS in
    check_adapters, which reads their frontmatter already.

    What is COPIED is wider than what is loaded: a plugin install copies the whole
    repository, `local/` and `tools/` scripts included. They are never loaded or run by
    Claude Code, and this check is about what is.
    """
    import json
    base = ROOT / '.claude-plugin'
    manifests = {}
    for name in ('plugin.json', 'marketplace.json'):
        path = base / name
        if not path.is_file():
            fail(path, 'missing. The repository is packaged as a plugin and a marketplace, '
                       'and a clone without this file installs nothing.')
            continue
        try:
            manifests[name] = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            fail(path, f'not valid JSON: {exc}')
            continue
        if not isinstance(manifests[name], dict):
            fail(path, 'is not a JSON object')
            manifests[name] = None

    plugin, where = manifests.get('plugin.json'), base / 'plugin.json'
    if plugin:
        for key in sorted(set(plugin) - PLUGIN_KEYS):
            fail(where, f'unexpected key {key!r}. Only metadata and `agents` are allowed; '
                        'skills load from skills/ by default, and anything else is a '
                        'component this toolkit does not ship.')
        if not SKILL_NAME_RE.fullmatch(str(plugin.get('name', ''))):
            fail(where, f'name {plugin.get("name")!r} is not a kebab-case plugin name')
        adapters = sorted(f'./.claude/agents/{p.name}'
                          for p in (ROOT / '.claude' / 'agents').glob('*.md'))
        listed = plugin.get('agents')
        if not isinstance(listed, list) or not all(isinstance(a, str) for a in listed):
            fail(where, '`agents` must be a list of adapter files. A directory is '
                        'rejected by claude plugin validate.')
        else:
            for duplicate in sorted({a for a in listed if listed.count(a) > 1}):
                fail(where, f'`agents` lists {duplicate!r} more than once')
            for missing in sorted(set(adapters) - set(listed)):
                fail(where, f'`agents` does not list {missing!r}, so the plugin does not '
                            'deliver that adapter')
            for extra in sorted(set(listed) - set(adapters)):
                fail(where, f'`agents` lists {extra!r}, which is not an adapter in '
                            '.claude/agents/')

    market, where = manifests.get('marketplace.json'), base / 'marketplace.json'
    if market:
        entries = market.get('plugins')
        if not isinstance(entries, list) or len(entries) != 1 \
                or not isinstance(entries[0], dict):
            fail(where, '`plugins` must list exactly one plugin: this repository')
        else:
            entry = entries[0]
            for key in sorted(set(entry) - ENTRY_KEYS):
                fail(where, f'plugin entry has unexpected key {key!r}. Components are '
                            'declared in plugin.json or loaded by default, never here.')
            if entry.get('source') != './':
                fail(where, f'plugin entry source is {entry.get("source")!r}, expected '
                            "'./': the plugin is the repository root")
            if plugin and entry.get('name') != plugin.get('name'):
                fail(where, f'plugin entry name {entry.get("name")!r} does not match '
                            f'plugin.json name {plugin.get("name")!r}')

    refused = {location.lower() for location in PLUGIN_DEFAULT_LOCATIONS}
    for path in sorted(ROOT.iterdir()):
        if path.name.lower() in refused:
            fail(path, 'Claude Code loads or acts on this at a plugin root, and the '
                       'repository root is the plugin root (.claude-plugin/'
                       'marketplace.json). It would reach every session that installs '
                       'the plugin.')
    for path in sorted((ROOT / 'skills').glob('*/SKILL.md')):
        for key in sorted(set(flat_frontmatter(path)) - SKILL_KEYS):
            fail(path, f'frontmatter key {key!r} is not an Agent Skills field. Claude Code '
                       'acts on several such keys, and skills/ is delivered by the plugin '
                       '(.claude-plugin/) to every session that installs it.')
    delivered = sorted((ROOT / 'skills').glob('*/SKILL.md')) \
        + sorted((ROOT / '.claude' / 'agents').glob('*.md'))
    for path in delivered:
        text = path.read_text(encoding='utf-8')
        for mark in SHELL_MARKS:
            at = text.find(mark)
            if at >= 0:
                fail(f'{path}:{text.count(chr(10), 0, at) + 1}',
                     f'{mark!r}: Claude Code runs inline shell in a SKILL.md when the skill '
                     'loads, and the plugin (.claude-plugin/) delivers this file to every '
                     'session that installs it. Any `!` beside a backtick is refused, as a '
                     'superset of what it runs.')
    workflows = ROOT / 'workflows'
    if workflows.is_dir():
        for path in sorted(p for p in workflows.rglob('*') if not p.is_dir()):
            if path.suffix != '.md':
                fail(path, 'workflows/ is also where Claude Code looks for plugin workflow '
                           'scripts (.claude-plugin/), so it may hold Markdown only')


CANONICAL_TREES = ('roles', 'agents', 'skills', 'workflows')

HOST_DIR_RE = re.compile(
    r'(?<![\w.-])(local|cloud|manifest|packs|profile|vendor|\.claude-plugin)/')
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
    `cloud/`, `manifest/`, `packs/`, `profile/`, `vendor/`, `.claude-plugin/`, and the
    settings and install scripts. It is NOT `.claude/agents/` or `.codex/agents/`, which are the ADAPTER tier,
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
    check_skill_links()
    check_plugin()
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
