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
PLACE_NAMES = _load_set('place_names.txt')


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
    """Person record is actually a deity, deified abstraction, or personification.

    Conservative: fires only when praenomen and nomen are both empty. Protects
    real persons named after deities (e.g. Geminia Victoria, Sulpicius Silvanus).
    """
    if person.get('praenomen') or person.get('nomen'):
        return False
    return bool(_clean_tokens(person) & DEITY_NAMES)


def is_imperial_person(person):
    """Person matches a known emperor or imperial-family signature.

    `[[name]]` damnatio memoriae brackets are an imperial-grade signal — but
    ONLY for non-military persons. Damnatio brackets very often surround a
    legion's imperial epithet ([[Antoninianae]], [[leg(ionis) III Aug(ustae)]])
    rather than the person's own name, so an officer/soldier or imperial-cult
    priest (Augustalis) carrying such brackets is NOT an emperor. Military and
    priestly context therefore vetoes the bracket / status signals; only a
    name-token EMPEROR_SIGNATURE match can flag such a person.
    """
    tokens = _clean_tokens(person)

    # Name-token signatures are the only fully safe signal — check first, before
    # any veto, so a genuine emperor named alongside a legion is still caught.
    for sig in EMPEROR_SIGNATURES:
        if sig <= tokens:
            return True

    status = (person.get('status') or '').lower()
    raw = (person.get('raw_name') or '').lower()
    context = status + ' ' + raw

    # Military unit / imperial-cult priesthood: damnatio brackets and 'Augusta'
    # in this context belong to the unit's epithet, not the person. Veto the
    # remaining (non-signature) signals — protects real legates/centurions of
    # Legio III Augusta and seviri Augustales.
    if 'legio' in context or 'leg(' in context or 'augustalis' in context or 'augustali' in context:
        return False

    # Damnatio memoriae brackets around the name (non-military) → imperial.
    if '[[' in raw and ']]' in raw:
        return True

    # Clear imperial titles in status (word boundaries avoid 'augustalis' etc.).
    if re.search(r'\b(imperator|emperor|augustus|caesar)\b', status):
        return True
    if re.search(r'\baugusta\b', status):
        return True

    return False


# Single-word epithets that are ALSO extremely common personal cognomina.
# A bare one of these is far more often a real person (slave/freedman) than a
# stranded imperial fragment, so it is NOT flagged on its own — only when it
# appears in a multi-word epithet sequence ("Pio Felici") or beside a hard
# imperial-only word.
_COMMON_COGNOMEN_EPITHETS = {'felix', 'felici', 'maximus', 'pius', 'pio'}


def is_bare_epithet(person):
    """Single-name 'person' that's actually a bare imperial epithet (Pius, Felix...).

    Guard: a lone Felix / Maximus / Pius is overwhelmingly a real cognomen, so a
    single-word epithet from that common-cognomen set does not fire. Multi-word
    sequences ("Pio Felici", "Imperator Caesar") and hard imperial-only words
    (Invictus, Augustus...) still do.
    """
    if person.get('praenomen') or person.get('nomen'):
        return False
    cog = (person.get('cognomen') or '').strip().lower()
    if not cog:
        return False
    cleaned = re.sub(r'[\[\]\(\)0-9\?\+\*]', '', cog).strip()
    words = cleaned.split()
    if not words:
        return False
    if not all(w in IMPERIAL_EPITHETS for w in words):
        return False
    if len(words) == 1 and words[0] in _COMMON_COGNOMEN_EPITHETS:
        return False
    return True


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
    if is_imperial_person(person):
        return 'imperial'
    if is_deity(person):
        return 'deity'
    if is_place(person):
        return 'place'
    if is_bare_epithet(person):
        return 'epithet'
    return None
