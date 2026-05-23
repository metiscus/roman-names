"""Classifiers for separating actual persons from common false-positive patterns.

Used by:
- 05b_eval_from_corpus.py — to bucket FPs (deity / imperial / fragment) out of the
  "discoveries" list so the precision number reflects real candidate persons.
- 06_export_to_dataset.py — to add `is_deity` / `is_imperial` boolean columns
  to the production dataset so downstream consumers can filter.

Designed to be conservative: false-flag a real person as deity/imperial only when
the evidence is unambiguous (exact deity name, known emperor signature). Marginal
cases are left as "person" and surface in the discoveries list for manual review.
"""
import re

# Roman gods + common African deities + abstract personifications worshipped in inscriptions.
# Matched as exact tokens against name fields (case-insensitive).
DEITY_NAMES = {
    # Olympian / Capitoline core
    'iuppiter', 'iupiter', 'jupiter', 'iovi', 'iovis',
    'iuno', 'juno', 'iunoni',
    'minerva', 'minervae',
    'mars', 'marti', 'martis',
    'venus', 'veneri', 'veneris',
    'apollo', 'apollini',
    'diana', 'dianae',
    'vulcanus', 'volcanus', 'vulcano',
    'mercurius', 'mercurio',
    'neptunus', 'neptuno',
    'vesta', 'vestae',
    'ceres', 'cereri',
    'bacchus', 'bacchi', 'liber', 'libero',
    'pluto', 'plutoni',
    'saturnus', 'saturno',  # in Africa = Baal-Hammon
    'sol', 'soli', 'luna', 'lunae',
    'hercules', 'herculi',
    'aesculapius', 'aesculapio',
    # African and syncretic
    'caelestis', 'caelesti',  # Tanit
    'hammon', 'ammon',
    'tanit', 'baal',
    'tellus', 'telluri',
    'frugifer',
    'genius', 'genio',
    'numen', 'numini',
    # Personifications worshipped as goddesses
    'salus', 'saluti', 'salutaris',
    'concordia', 'concordiae', 'corcondia', 'corcondiae',  # incl. EDCS misspelling
    'fortuna', 'fortunae',
    'spes', 'spei',
    'pietas', 'pietati',
    'virtus', 'virtuti',
    'victoria', 'victoriae',
    'felicitas', 'felicitati',
    'iustitia', 'justitiae',
    'pax', 'paci', 'pacis',
    'roma', 'romae',
    'libertas', 'libertati',
    'fides', 'fidei',
    'honos', 'honori',
    'abundantia',
    'providentia',
    'aequitas',
    'clementia',
    'disciplina',
    # Collective
    'lares', 'laribus',
    'penates', 'penatibus',
    'manes', 'manibus',
    'dii', 'diis',
    # Imperial cult — "Augusta" alone is the deified empress
    'augusta', 'augustae',
}

# Emperors and immediate-family members typically attested in dedicatory inscriptions.
# Stored as lowercase signature substrings — we match if a person's combined-name
# string contains both anchor parts (e.g. 'septimius' AND 'geta').
EMPEROR_SIGNATURES = [
    # Julio-Claudians
    {'augustus'}, {'tiberius', 'caesar'}, {'caligula'}, {'claudius', 'caesar'},
    {'nero', 'caesar'},
    # Flavians
    {'vespasianus'}, {'titus', 'caesar'}, {'domitianus'},
    # Antonines and adoptive
    {'nerva', 'caesar'}, {'traianus'}, {'hadrianus'},
    {'antoninus', 'pius'}, {'marcus', 'aurelius'}, {'verus', 'lucius'},
    {'commodus'},
    # Severans
    {'septimius', 'severus'},
    {'septimius', 'geta'},
    {'caracalla'}, {'aurelius', 'antoninus'},  # Caracalla's formal name
    {'macrinus'}, {'elagabalus'}, {'heliogabalus'},
    {'severus', 'alexander'},
    # Third century
    {'maximinus', 'thrax'}, {'gordianus'}, {'philippus', 'arabs'},
    {'decius'}, {'valerianus'}, {'gallienus'}, {'aurelianus'},
    {'probus'}, {'carus'}, {'diocletianus'}, {'maximianus'},
    # Tetrarchy / Constantinian
    {'constantius', 'chlorus'}, {'galerius'}, {'constantinus'},
    {'licinius'}, {'maxentius'}, {'crispus'},
    # Later (often attested in late-antique African inscriptions)
    {'iulianus', 'apostata'}, {'valentinianus'}, {'valens'},
    {'theodosius'}, {'honorius'}, {'arcadius'},
    # Praetorian prefects with emperor-level damnatio memoriae
    {'fulvius', 'plautianus'},
]

# Bare imperial epithets — if cognomen is just this and no nomen/praenomen, it's an
# epithet fragment, not a person.
IMPERIAL_EPITHETS = {
    'pius', 'felix', 'invictus', 'maximus', 'aeternus', 'perpetuus',
    'augustus', 'augusta', 'caesar', 'imperator', 'dominus', 'noster',
    'pio', 'felici', 'invicto',  # dative forms common in dedications
}


def _name_tokens(person):
    """All lowercase word tokens from praenomen/nomen/cognomen + raw_name."""
    parts = []
    for field in ('praenomen', 'nomen', 'cognomen', 'raw_name'):
        val = person.get(field)
        if isinstance(val, str):
            parts.append(val.lower())
    text = ' '.join(parts)
    return set(re.findall(r'[a-z]+', text))


def is_deity(person):
    """Person record is actually a deity, deified abstraction, or personification."""
    tokens = _name_tokens(person)
    # Any explicit deity token in any name field
    if tokens & DEITY_NAMES:
        return True
    return False


def is_imperial_person(person):
    """Person matches a known emperor or imperial-family signature.

    Also catches `[[name]]` damnatio memoriae brackets in raw_name — those only
    appear on individuals whose memory was condemned by Senate, almost always
    emperors or their close circle.
    """
    raw = person.get('raw_name') or ''
    # Damnatio memoriae: [[...]] in the raw text is an imperial-grade signal
    if '[[' in raw and ']]' in raw:
        return True

    tokens = _name_tokens(person)
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
    # Strip bracket noise so 'p]io felic[i' compares as 'pio felici'
    cleaned = re.sub(r'[\[\]\(\)0-9]', '', cog).strip()
    words = cleaned.split()
    if not words:
        return False
    # All tokens must be in the epithet set
    return all(w in IMPERIAL_EPITHETS for w in words)


def classify_non_person_fp(person):
    """Return a category label if this 'person' is a recognised non-person FP.

    Returns one of: 'deity', 'imperial', 'epithet', or None.
    Used by the eval to bucket discoveries.
    """
    if is_deity(person):
        return 'deity'
    if is_imperial_person(person):
        return 'imperial'
    if is_bare_epithet(person):
        return 'epithet'
    return None
