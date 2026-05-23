"""Classifiers for separating actual persons from common false-positive patterns.

Used by:
- 05b_eval_from_corpus.py — to bucket FPs (deity / imperial / epithet / place) out
  of the "discoveries" list so the precision number reflects real candidate persons.
- 06_export_to_dataset.py — to add `is_deity` / `is_imperial` / `is_bare_epithet`
  / `is_place` boolean columns to the production dataset so downstream consumers
  can filter.

Curated lists live in scripts/lookup/*.txt — plain text, one entry per line,
`#` comments ignored. Extend those files rather than editing this module when
new FP patterns are discovered in triage.

Designed to be conservative: false-flag a real person as non-person only when
the evidence is unambiguous (exact deity name, known emperor signature, place
in cognomen with no other name fields). Marginal cases are left as "person"
and surface in the discoveries list for manual review.
"""
import os
import re

_LOOKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lookup')


def _load_set(filename):
    """Load a text file of one-token-per-line into a lowercase set."""
    path = os.path.join(_LOOKUP_DIR, filename)
    result = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                result.add(line.lower())
    return result


def _load_signatures(filename):
    """Load a text file of comma-separated tuple signatures.

    Each non-comment line becomes a frozenset of lowercase tokens. The result
    is a list of frozensets — used for subset-match against a person's name tokens.
    """
    path = os.path.join(_LOOKUP_DIR, filename)
    result = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            tokens = frozenset(t.strip().lower() for t in line.split(',') if t.strip())
            if tokens:
                result.append(tokens)
    return result


DEITY_NAMES = _load_set('deities.txt')
EMPEROR_SIGNATURES = _load_signatures('emperor_signatures.txt')
IMPERIAL_EPITHETS = _load_set('imperial_epithets.txt')
PLACE_NAMES = _load_set('african_places.txt')


def _clean_tokens(person):
    """Extract lowercase alpha tokens from name fields after stripping
    epigraphic noise — brackets, parens, digits — so bracketed forms like
    `Ner[vae(?)]` still match against EMPEROR_SIGNATURES.
    """
    parts = []
    for field in ('praenomen', 'nomen', 'cognomen', 'raw_name'):
        val = person.get(field)
        if isinstance(val, str):
            parts.append(val.lower())
    text = ' '.join(parts)
    # Drop bracket/paren/digit/question-mark noise before tokenizing
    text = re.sub(r'[\[\]\(\)0-9\?\+\*]', '', text)
    return set(re.findall(r'[a-z]+', text))


def is_deity(person):
    """Person record is actually a deity, deified abstraction, or personification."""
    return bool(_clean_tokens(person) & DEITY_NAMES)


def is_imperial_person(person):
    """Person matches a known emperor or imperial-family signature.

    `[[name]]` damnatio memoriae brackets in raw_name are also an imperial-grade
    signal — those only appear on individuals whose memory was condemned by the
    Senate, almost always emperors or their close circle.
    """
    raw = person.get('raw_name') or ''
    if '[[' in raw and ']]' in raw:
        return True

    tokens = _clean_tokens(person)
    for sig in EMPEROR_SIGNATURES:
        if sig <= tokens:
            return True
    return False


def is_bare_epithet(person):
    """Single-name 'person' that's actually a bare imperial epithet (Pius, Felix...)."""
    if person.get('praenomen') or person.get('nomen'):
        return False
    cog = (person.get('cognomen') or '').strip().lower()
    if not cog:
        return False
    cleaned = re.sub(r'[\[\]\(\)0-9\?\+\*]', '', cog).strip()
    words = cleaned.split()
    if not words:
        return False
    return all(w in IMPERIAL_EPITHETS for w in words)


def is_place(person):
    """Cognomen-only 'person' that's actually a town name.

    Conservative: fires only when praenomen and nomen are both empty AND the
    cognomen (after bracket cleanup) is in the curated PLACE_NAMES set. Protects
    against false-flagging real persons whose name overlaps a town token.
    """
    if person.get('praenomen') or person.get('nomen'):
        return False
    cog = (person.get('cognomen') or '').strip().lower()
    if not cog:
        return False
    cleaned = re.sub(r'[\[\]\(\)0-9\?\+\*]', '', cog).strip()
    return cleaned in PLACE_NAMES


def classify_non_person_fp(person):
    """Return a category label if this 'person' is a recognised non-person FP.

    Returns one of: 'deity', 'imperial', 'place', 'epithet', or None.
    Used by the eval to bucket discoveries.
    """
    if is_deity(person):
        return 'deity'
    if is_imperial_person(person):
        return 'imperial'
    if is_place(person):
        return 'place'
    if is_bare_epithet(person):
        return 'epithet'
    return None
