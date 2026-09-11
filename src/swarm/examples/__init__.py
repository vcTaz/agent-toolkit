"""Packaged demonstration scenarios.

These ship inside the wheel so ``python -m swarm run --scenario arithmetic_success`` works
from an installed package with no repository checkout. ``swarm.examples.catalogue`` lists
them; ``swarm.examples.resolve`` turns a name, a bare file name or a path into a file.
"""
import json
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent


def catalogue():
    """Every packaged scenario, by name, in deterministic order."""
    entries = []
    for path in sorted(DIRECTORY.glob('*.json')):
        try:
            with path.open(encoding='utf-8') as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            payload = {}
        entries.append({'name': path.stem, 'path': str(path),
                        'description': payload.get('description', ''),
                        'objective': payload.get('objective', '')})
    return tuple(entries)


def resolve(reference):
    """A filesystem path if one exists, otherwise the packaged example of that name.

    Accepts ``arithmetic_success``, ``arithmetic_success.json`` and
    ``examples/arithmetic_success.json`` so one documented command works from a checkout
    and from an installed wheel alike. Returns ``None`` when nothing matches.
    """
    candidate = Path(reference)
    if candidate.is_file():
        return candidate
    packaged = DIRECTORY / f'{candidate.stem}.json'
    return packaged if packaged.is_file() else None
