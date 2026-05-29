import os

_LOOKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lookup')

def _load_lookup(filename):
    """Load a one-token-per-line text file, preserving original case."""
    path = os.path.join(_LOOKUP_DIR, filename)
    result = set()
    if not os.path.exists(path):
        return result
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#', 1)[0].strip()
            if line:
                result.add(line)
    return result

PRAENOMINA = _load_lookup('praenomina_prompt.txt')
TRIBUS = _load_lookup('tribus.txt')

def get_system_prompt(province):
    # Province-specific few-shots
    if province.lower() == 'britannia':
        extra_examples = """
**Input:** "Deo Marti Belatucadro L(ucius) Iulius Victor v(otum) s(olvit) l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "B1", "persons": [
    {"praenomen": "Lucius", "nomen": "Iulius", "cognomen": "Victor", "gender": "male", "status": null, "raw_name": "L. Iulius Victor"}
  ]}]
}

**Input:** "D(is) M(anibus) / P(ublio) Rustio / Fabia Felici / q(uondam) mil(iti) leg(ionis) II / Aug(ustae) vix(it) ann(is) / XXXVIII"
**Output:**
{
  "results": [{"id": "B2", "persons": [
    {"praenomen": "Publius", "nomen": "Rustius", "cognomen": "Felix", "gender": "male", "status": "tribus: Fabia, miles legionis II Augustae", "raw_name": "P. Rustio Fabia Felici"}
  ]}]
}

**Input:** "Deo Marti Belatucadro / v(otum) s(olvit) l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "B3", "persons": []}]
}"""
    elif province.lower() == 'africa proconsularis':
        extra_examples = """
**Input:** "Libero Patri sacrum Boncarth Muthumbalis filius Sydby IIII vir macelli"
**Output:**
{
  "results": [{"id": "A1", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Boncarth", "gender": "male", "status": "IIII vir macelli", "raw_name": "Boncarth"},
    {"praenomen": null, "nomen": null, "cognomen": "Muthumbal", "gender": "male", "status": "filius", "raw_name": "Muthumbalis"},
    {"praenomen": null, "nomen": null, "cognomen": "Sydbyus", "gender": "male", "status": null, "raw_name": "Sydby"}
  ]}]
}

**Input:** "Dis Manibus sacrum Aemilia Victoria Fipiorina pia vixit annos XXXV"
**Output:**
{
  "results": [{"id": "A2", "persons": [
    {"praenomen": null, "nomen": "Aemilia", "cognomen": "Victoria Fipiorina", "gender": "female", "status": "pia", "raw_name": "Aemilia Victoria Fipiorina"}
  ]}]
}"""
    elif province.lower() in ('lusitania', 'baetica', 'hispania citerior'):
        extra_examples = """
**Input:** "Sailgius / Tangini f(ilius) / h(ic) s(itus) e(st) s(it) t(ibi) t(erra) l(evis) / Meiduenus / Andami f(ilius) / d(e) s(uo) f(aciendum) c(uravit)"
**Output:**
{
  "results": [{"id": "L1", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Sailgius", "gender": "male", "status": null, "raw_name": "Sailgius"},
    {"praenomen": null, "nomen": null, "cognomen": "Tanginus", "gender": "male", "status": "pater", "raw_name": "Tangini f(ilius)"},
    {"praenomen": null, "nomen": null, "cognomen": "Meiduenus", "gender": "male", "status": null, "raw_name": "Meiduenus"},
    {"praenomen": null, "nomen": null, "cognomen": "Andamis", "gender": "male", "status": "pater", "raw_name": "Andami f(ilius)"}
  ]}]
}

**Input:** "Bandi Vorteaecio / v(otum) s(olvit) l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "L2", "persons": []}]
}

**Input:** "Ataecinae / Turibrig(ensi) sac(rum) / Severa Cantabri / f(ilia) ex voto"
**Output:**
{
  "results": [{"id": "L3", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Severa", "gender": "female", "status": "filia Cantabri", "raw_name": "Severa Cantabri f."}
  ]}]
}

**Input:** "Endovellico / sacrum / Rufus / Rufini fil(ius) / v(otum) s(olvit)"
**Output:**
{
  "results": [{"id": "L4", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Rufus", "gender": "male", "status": "filius Rufini", "raw_name": "Rufus Rufini fil."}
  ]}]
}

**Input:** "Avitus Ton/gi f(ilius) an(norum) LX / h(ic) s(itus) e(st) / s(it) t(ibi) t(erra) l(evis)"
**Output:**
{
  "results": [{"id": "L5", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Avitus", "gender": "male", "status": null, "raw_name": "Avitus"},
    {"praenomen": null, "nomen": null, "cognomen": "Tongus", "gender": "male", "status": "pater", "raw_name": "Ton/gi f(ilius)"}
  ]}]
}

**Input:** "P(ublius) Norba/nus Ser(gia) / Flaccinus / aed(ilis) an(norum) / XXX h(ic) s(itus) e(st)"
**Output:**
{
  "results": [{"id": "L6", "persons": [
    {"praenomen": "Publius", "nomen": "Norbanus", "cognomen": "Flaccinus", "gender": "male", "status": "tribus: Sergia, aedilis", "raw_name": "P. Norbanus Ser. Flaccinus"}
  ]}]
}"""

    elif province.lower() == 'aegyptus':
        extra_examples = """
**AEGYPTUS-SPECIFIC RULES:**
1. BILINGUAL CORPUS: Aegyptus contains Latin, Greek, and mixed inscriptions. Apply standard NER rules to both scripts: extract personal names, decline to nominative, assign gender.
2. HEALING DEITY DEDICATIONS: Inscriptions dedicated to Ἀσκληπιός/Asclepius, Ὑγίεια/Hygeia, Apollo/Apollon, and their children (Machaon, Podalirios, Iaso, Akeso, Aigle, Panakeia) are votive offerings to gods. Return persons: [] for these deity names unless a human dedicant is explicitly named.
3. SALUTATION WORDS ARE NOT NAMES: Words like "karissime", "dulcissime", "vivas", "feliciter", "salutem", "vale" are epistolary formulas, not personal names. Do NOT extract them as persons.
4. LEGAL/STATUS TERMS ARE NOT NAMES: Terms like "manumissus" (freed slave), "heredem" (heir), "tutorem" (guardian) are roles, not personal names. They may appear as status in a named person's entry, but not as the name itself.
5. EGYPTIAN GEOGRAPHIC NAMES: City and nome names like Coptos, Ceramices, Diospolis, Berenice, Ophieon, Boreseos, Triacontaschoenus are places — do not extract them as persons even when they appear in military conquest lists.

**Input:** "C(aius) Antonius Maximus armorum cus(tos) / L(uci) Farsulei / M(arcus) Arrius Antoninus / turma Rufi / Gaius Barga mil(es) L(uci) Farsulei / C(aius) Iulius Marcellus cornicul(arius)"
**Output:**
{
  "results": [{"id": "E1", "persons": [
    {"praenomen": "Gaius", "nomen": "Antonius", "cognomen": "Maximus", "gender": "male", "status": "armorum custos", "raw_name": "C. Antonius Maximus"},
    {"praenomen": null, "nomen": "Farsulius", "cognomen": null, "gender": "male", "status": null, "raw_name": "L(uci) Farsulei"},
    {"praenomen": "Marcus", "nomen": "Arrius", "cognomen": "Antoninus", "gender": "male", "status": null, "raw_name": "M. Arrius Antoninus"},
    {"praenomen": null, "nomen": "Rufus", "cognomen": null, "gender": "male", "status": "turma", "raw_name": "turma Rufi"},
    {"praenomen": "Gaius", "nomen": null, "cognomen": "Barga", "gender": "male", "status": "miles", "raw_name": "Gaius Barga"},
    {"praenomen": "Gaius", "nomen": "Iulius", "cognomen": "Marcellus", "gender": "male", "status": "cornicularius", "raw_name": "C. Iulius Marcellus"}
  ]}]
}

**Input:** "Exemplar / hordei missi per Chae/remonam Anubionis / gubernatorem ex no/mo Memphite"
**Output:**
{
  "results": [{"id": "E2", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Chaeremon", "gender": "male", "status": "gubernator", "raw_name": "Chaeremonam Anubionis"},
    {"praenomen": null, "nomen": null, "cognomen": "Anubion", "gender": "male", "status": "pater", "raw_name": "Anubionis"}
  ]}]
}

**Input:** "T(itus) Flavius Titianus praef(ectus) Aeg(ypti) postulante / Publio Diodoro quo ne ab iusto tutore / (H)erennia(e) Antonia(e) fil(iae) Lu/ci (H)erenni Valentis M(arcum) Numisium / Longum legitimum tutorem / dedit"
**Output:**
{
  "results": [{"id": "E3", "persons": [
    {"praenomen": "Titus", "nomen": "Flavius", "cognomen": "Titianus", "gender": "male", "status": "praefectus Aegypti", "raw_name": "T. Flavius Titianus"},
    {"praenomen": null, "nomen": null, "cognomen": "Diodorus", "gender": "male", "status": null, "raw_name": "Publio Diodoro"},
    {"praenomen": null, "nomen": "Herennia", "cognomen": "Antonia", "gender": "female", "status": "filia", "raw_name": "Herenniae Antoniae fil."},
    {"praenomen": "Lucius", "nomen": "Herennius", "cognomen": "Valens", "gender": "male", "status": "pater", "raw_name": "Luci Herenni Valentis"},
    {"praenomen": "Marcus", "nomen": "Numisius", "cognomen": "Longus", "gender": "male", "status": "tutor", "raw_name": "M. Numisium Longum"}
  ]}]
}

**Input:** "Ζηνοδώρα θυγάτηρ Ἡρακλάμμωνος γυνὴ Ἡλίου ὀρδιναρίου λεγιῶνος πέμπτης Μακεδονικῆς"
**Output:**
{
  "results": [{"id": "E4", "persons": []}]
}

**Input:** "Leg(io) III Cyr(enaica) / |(centuria) Minuci / Claudiani / C(aius) Anthistius / Valens nomo / Arsenoite"
**Output:**
{
  "results": [{"id": "E5", "persons": [
    {"praenomen": null, "nomen": "Minucius", "cognomen": "Claudianus", "gender": "male", "status": "centurio legionis III Cyrenaicae", "raw_name": "|(centuria) Minuci Claudiani"},
    {"praenomen": "Gaius", "nomen": "Anthistius", "cognomen": "Valens", "gender": "male", "status": "domo nomo Arsenoite", "raw_name": "C. Anthistius Valens"}
  ]}]
}

**Input:** "ὑπὲρ Αὐτοκράτορος Καίσαρος Νέρουα Τραιανοῦ Σεβαστοῦ Γερμανικοῦ / Ἀσκληπιῶι καὶ Ὑγιείαι τὸν ναὸν καὶ τὸ τέμενος ἐπεσκεύασεν / ἡ πόλις / ἐπὶ Πομπηΐου Πλάντα ἡγεμόνος"
**Output:**
{
  "results": [{"id": "E6", "persons": [
    {"praenomen": null, "nomen": "Pompeius", "cognomen": "Planta", "gender": "male", "status": "hegemon", "raw_name": "Πομπηΐου Πλάντα ἡγεμόνος"}
  ]}]
}

**Input:** "Antistius Flaccus Calinio suo salutem / a Raima te frater saluto / karissime uale"
**Output:**
{
  "results": [{"id": "E7", "persons": [
    {"praenomen": null, "nomen": "Antistius", "cognomen": "Flaccus", "gender": "male", "status": null, "raw_name": "Antistius Flaccus"},
    {"praenomen": null, "nomen": null, "cognomen": "Raimas", "gender": "male", "status": "frater", "raw_name": "Raima"},
    {"praenomen": null, "nomen": null, "cognomen": "Calinius", "gender": "male", "status": null, "raw_name": "Calinio suo"}
  ]}]
}"""

    elif province.lower() == 'sardinia':
        extra_examples = """
**SARDINIA-SPECIFIC RULES:**
1. SURGICAL raw_name: The raw_name field MUST NOT contain formulaic words like "qui", "vixit", "annis", "plus", "minus", "requievit", "in pace", "fecit", "posuit", or dates. It should ONLY contain the name tokens and necessary filiation (e.g., "L. f.").
2. NO FALSE FRAGMENTS: Do not extract "names" from fragmentary formulas like "]EMB[" or "a]nnis". If the only recognizable word is a common formula or date, return persons: [].

**Input:** "Augusti Caesaris germanicum // L(ucius) Val(erius) Ruf(us)"
**Output:**
{
  "results": [{"id": "S1", "persons": [
    {"praenomen": "Lucius", "nomen": "Valerius", "cognomen": "Rufus", "gender": "male", "status": null, "raw_name": "L. Val. Ruf."}
  ]}]
}

**Input:** "Hic iacet / bon(a)e memo/ri(a)e Iannar/ius qui <v=B>ixit / plus minus / annos LXV re/quie<v=B>it / in pace"
**Output:**
{
  "results": [{"id": "S2", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Iannarius", "gender": "male", "status": "bonae memoriae", "raw_name": "Iannar/ius"}
  ]}]
}

**Input:** "D(is) M(anibus) / Crescenti filio / bene merenti / qui vixit annis / XXXII ... pater eius / et mater fec(erunt)"
**Output:**
{
  "results": [{"id": "S4", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Crescens", "gender": "male", "status": "filius bene merenti", "raw_name": "Crescenti"}
  ]}]
}

**Input:** "[Bon(a)e] m<e=I>mori(a)e Felix qui / [vixit] plus minus annos / [3 D]ecembres reque<v=B>it"
**Output:**
{
  "results": [{"id": "S5", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Felix", "gender": "male", "status": "bonae memoriae", "raw_name": "Felix"}
  ]}]
}"""

    elif province.lower() == 'corsica':
        extra_examples = """
**Input:** "C(aio) Caesari / Augusti f(ilio)"
**Output:**
{
  "results": [{"id": "C1", "persons": [
    {"praenomen": "Gaius", "nomen": null, "cognomen": "Caesar", "gender": "male", "status": "Augusti filius", "raw_name": "C. Caesari"}
  ]}]
}

**Input:** "Imp(erator) Caesar Vespasianus Augustus / magistratibus et senatoribus / Vanacinorum salutem dicit / Otacilium Sagittam amicum et procu/ratorem meum..."
**Output:**
{
  "results": [{"id": "C2", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Vespasianus", "gender": "male", "status": "Imperator Caesar Augustus", "raw_name": "Imp. Caesar Vespasianus Augustus"},
    {"praenomen": null, "nomen": "Otacilius", "cognomen": "Sagitta", "gender": "male", "status": "amicus et procurator", "raw_name": "Otacilium Sagittam"}
  ]}]
}

**Input:** "[F]av[or] Cn(aei) Domiti s(ervus) f(ecit)"
**Output:**
{
  "results": [{"id": "C3", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Favor", "gender": "male", "status": "servus Gnaei Domitii", "raw_name": "[F]av[or]"},
    {"praenomen": "Gnaeus", "nomen": "Domitius", "cognomen": null, "gender": "male", "status": "dominus", "raw_name": "Cn(aei) Domiti"}
  ]}]
}

**Input:** "A(ulo) Petr[3] VIviro] / August[ali 3] / Scutaria [3] / Scutari [3] / viro suo"
**Output:**
{
  "results": [{"id": "C4", "persons": [
    {"praenomen": "Aulus", "nomen": "Petronius", "cognomen": null, "gender": "male", "status": "VIvir Augustalis", "raw_name": "A(ulo) Petr[3]", "fragmentary": true},
    {"praenomen": null, "nomen": null, "cognomen": "Scutaria", "gender": "female", "status": null, "raw_name": "Scutaria", "fragmentary": true},
    {"praenomen": null, "nomen": null, "cognomen": "Scutarius", "gender": "male", "status": "vir", "raw_name": "Scutari", "fragmentary": true}
  ]}]
}

**Input:** "] prin[cipali] / col(oniae) Aler[ia] / XV civitates / Sibroar[iae(?)] / patrono"
**Output:**
{
  "results": [{"id": "C5", "persons": []}]
}"""

    elif province.lower() == 'sicilia':
        extra_examples = """
**SICILIA-SPECIFIC RULES:**
1. Sicilia has a large Greek-language corpus. Apply the same NER rules to Greek inscriptions: extract personal names, decline to nominative, assign gender.
2. DEITY DEDICATIONS: Greek votive formulas like "νίκη Διός" (victory of Zeus), "τᾶι Ἀθαναίαι" (to Athena), "Ἡρακλέ(ο)ς" (of Heracles), "Διὸς Σωτῆρος" (of Zeus Soter) are dedications to gods — return persons: []. νίκη in a dedication context means "victory" (a concept or deity), NOT a personal name.
3. MAGICAL / GNOSTIC TEXTS: Texts containing sequences like "αβρασαξ", "ιαω", "Σολομῶνος" (Seal of Solomon), "Adonai", "Sadanael", angel/demon names, or long strings of vowels/consonants without word breaks are magical amulets or curse tablets — return persons: []. A text mixing Hebrew divine names (Adonai, Sion) with Greek or mixed-script tokens is ALWAYS a magical amulet.
4. ETHNIC ADJECTIVES: Words like "Τύριος" (Tyrian), "Συρακόσιον" (Syracusan), "Γελόιον" (of Gela) describe origin, not a separate person. Record in the status field of the preceding person, do NOT create a separate person entry.
5. MONTH NAMES are not persons: Πανάμου (Panamos), Ἀγριανίου (Agrianios), Ἀπελλαίου (Apellaios), Καρνείου (Karneios) etc. are Sicilian-Doric month names.
6. COMMON GREEK WORDS are not names: σκύλα (spoils), νήπιος/νήπια (infant), ψωλός/ψωλαί (obscene term), ὕδωρ (water), ξαδριον, πιστά (faithful), ὀγκία (ounce — a weight unit), δαμοσία (public — an adjective, not a name).
7. Two-name sequences: "L(ucius) Gabinio(s)" = praenomen Lucius + nomen Gabinius, NO cognomen. Do not duplicate the nomen as cognomen.

**Input:** "νίκη / Διός"
**Output:**
{
  "results": [{"id": "SI1", "persons": []}]
}

**Input:** "τᾶι Ἀθαναίαι σκύλα ἀπὸ τῶν πολεμίων"
**Output:**
{
  "results": [{"id": "SI2", "persons": []}]
}

**Input:** "Σφραγίς Σολομῶνος // Επηνα / συμαηα / ο σαλαμ/αξα"
**Output:**
{
  "results": [{"id": "SI3", "persons": []}]
}

**Input:** "Ἀπολλοφάν/ης / Τύριος"
**Output:**
{
  "results": [{"id": "SI4", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Apollophanes", "gender": "male", "status": "Tyrios", "raw_name": "Ἀπολλοφάν/ης Τύριος"}
  ]}]
}

**Input:** "ἐπὶ Παυ/σανία / Πανάμου"
**Output:**
{
  "results": [{"id": "SI5", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Pausanias", "gender": "male", "status": null, "raw_name": "Παυ/σανία"}
  ]}]
}

**Input:** "D(is) M(anibus) s(acrum) / Cassia Galene / vixit ann(os) XXXX / C(aius) Iulius Macedo / uxori piissimae / fecit"
**Output:**
{
  "results": [{"id": "SI6", "persons": [
    {"praenomen": null, "nomen": "Cassia", "cognomen": "Galene", "gender": "female", "status": "uxor piissima", "raw_name": "Cassia Galene"},
    {"praenomen": "Gaius", "nomen": "Iulius", "cognomen": "Macedo", "gender": "male", "status": null, "raw_name": "C. Iulius Macedo"}
  ]}]
}

**Input:** "L(ucius) Gabinio(s)"
**Output:**
{
  "results": [{"id": "SI7", "persons": [
    {"praenomen": "Lucius", "nomen": "Gabinius", "cognomen": null, "gender": "male", "status": null, "raw_name": "L. Gabinio(s)"}
  ]}]
}

**Input:** "Ν<ή=Ι>πι{ι}α // C"
**Output:**
{
  "results": [{"id": "SI8", "persons": []}]
}

**Input:** "A Adonai Ω / Sadanael / Sion / Bonoi T(h)eon / Cαρνω"
**Output:**
{
  "results": [{"id": "SI9", "persons": []}]
}

**Input:** "Δ(αμοσία) ὀ//γκία"
**Output:**
{
  "results": [{"id": "SI10", "persons": []}]
}

**Input:** "νίκη / Ἀθηνίωνος"
**Output:**
{
  "results": [{"id": "SI11", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Athenion", "gender": "male", "status": null, "raw_name": "Ἀθηνίωνος"}
  ]}]
}"""

    elif province.lower() in ('etruria / regio vii', 'etruria'):
        extra_examples = """
**ETRURIA / REGIO VII RULES:**
1. AMPHORAE & VESSEL STAMPS: Many Etrurian inscriptions are single-word or single-name stamps on amphorae or vessels (e.g. "Ses(tius)", "Sest(ius)", "Ciclops", "Aloni"). Extract the stamp owner's name normally (usually cognomen only or nomen only).
2. VESSEL VOCABULARY: Common Latin words for containers are NOT personal names. "poco(lom)" / "poculom" / "poculum" = cup/vessel — return persons: [] for inscriptions containing only this word.
3. MINIMUM FRAGMENT THRESHOLD: Do NOT extract a person when the entire visible text (after removing brackets and lacuna markers) yields **no single contiguous token of 5+ letters** that could be a personal name. Specifically: "]rdo" → skip (3 letters); "]us Pri[" → skip (each token ≤3 letters); "[3]mus" → skip (3 letters after lacuna). If you see only tokens of ≤4 letters and none of them is a known standalone name, return persons: []. A complete visible name like "Dion" (4 letters but a known Greek name) may still be extracted if you are confident it is a personal name.
4. GNATUS / NATUS = ORIGIN, NOT COGNOMEN: "gnatus" / "natus" followed by an ablative noun or name indicates birth origin — "Vibia gnatus" means "born of Vibia" (his mother). Do NOT treat the ablative noun as a cognomen. Record the main person without a cognomen derived from "gnatus": e.g. "A(ulus) Herennius L(uci) f(ilius) Vibia gnatus" → praenomen=Aulus, nomen=Herennius, cognomen=null, status="filius Luci".
5. "ORDO" IS NOT A NAME: "ordo" in Latin means council or rank. Do not extract it as a personal name.

**Input:** "[3] poco(lom)"
**Output:**
{
  "results": [{"id": "ET1", "persons": []}]
}

**Input:** "A(ulus) Herennius L(uci) f(ilius) Vibia / gnatus"
**Output:**
{
  "results": [{"id": "ET2", "persons": [
    {"praenomen": "Aulus", "nomen": "Herennius", "cognomen": null, "gender": "male", "status": "filius Luci", "raw_name": "A. Herennius L. f. Vibia gnatus", "fragmentary": false}
  ]}]
}

**Input:** "[3]mus et [3]ste / [3]ia / Postumiae L. l(ibertae) Lesbiae"
**Output:**
{
  "results": [{"id": "ET3", "persons": [
    {"praenomen": null, "nomen": "Postumia", "cognomen": "Lesbia", "gender": "female", "status": "liberta Luci", "raw_name": "Postumiae L. l(ibertae) Lesbiae", "fragmentary": false}
  ]}]
}

**Input:** "Ex offic(ina) C(ai) Iuli / Hymenis"
**Output:**
{
  "results": [{"id": "ET4", "persons": [
    {"praenomen": "Gaius", "nomen": "Iulius", "cognomen": "Hymen", "gender": "male", "status": "ex officina", "raw_name": "C. Iuli Hymenis", "fragmentary": false}
  ]}]
}

**Input:** "Pacia C(ai) f(ilia) Galla"
**Output:**
{
  "results": [{"id": "ET5", "persons": [
    {"praenomen": null, "nomen": "Pacia", "cognomen": "Galla", "gender": "female", "status": "filia Cai", "raw_name": "Pacia C. f. Galla", "fragmentary": false}
  ]}]
}"""

    elif province.lower() in ('gallia narbonensis', 'belgica', 'aquitani(c)a',
                              'germania superior', 'germania inferior'):
        extra_examples = """
**GAUL/GERMANIA RULES:**
1. CELTIC SINGLE NAMES: Many Gallic and Germanic peregrini bear a single personal name with no praenomen or nomen. Treat these as **cognomen only** (praenomen=null, nomen=null).
2. CELTIC FILIATION: "Atto Camuli f(ilius)" — Atto is the main person (cognomen only), Camulus is the father (status "pater", cognomen only). Do NOT put Camulus in Atto's nomen field.
3. POST-CITIZENSHIP NAMING: After 212 AD many Gauls adopted Roman nomina (Iulius, Aurelius, Claudius most common) while keeping a Celtic cognomen. "Iulius Masuetus" = nomen Iulius, cognomen Masuetus.
4. GALLIC/GERMANIC DEITIES: Epona, Nantosuelta, Rosmerta, Sequana, Sucellus, Maponos, Taranis, Lenus, Intarabus, Ritona, Nehalennia, Matres/Matronae, Vagdavercustis, Hludana, Hercules Magusanus and similar indigenous divine names are deities, NOT persons.
5. MILITARY UNITS: Rhine legions (Legio I Minervia, VIII Augusta, XXII Primigenia, XXX Ulpia Victrix, I Adiutrix, etc.) and auxiliary unit names (ala, cohors) must NOT be extracted as persons.

**Input:** "Atepomaro / Atti f(ilio) / v(otum) s(olvit) / l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "GA1", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Atepomarus", "gender": "male", "status": null, "raw_name": "Atepomaro"},
    {"praenomen": null, "nomen": null, "cognomen": "Attus", "gender": "male", "status": "pater", "raw_name": "Atti f(ilio)"}
  ]}]
}

**Input:** "D(is) M(anibus) / Iulio Masueto / mil(iti) leg(ionis) VIII / Aug(ustae) / Iulia Bricca / uxor fecit"
**Output:**
{
  "results": [{"id": "GA2", "persons": [
    {"praenomen": null, "nomen": "Iulius", "cognomen": "Masuetus", "gender": "male", "status": "miles legionis VIII Augustae", "raw_name": "Iulio Masueto"},
    {"praenomen": null, "nomen": "Iulia", "cognomen": "Bricca", "gender": "female", "status": "uxor", "raw_name": "Iulia Bricca"}
  ]}]
}

**Input:** "Eponae Aug(ustae) sac(rum) / v(otum) s(olvit) l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "GA3", "persons": []}]
}

**Input:** "Matribus / Treveris / et Italicis / sacrum"
**Output:**
{
  "results": [{"id": "GA4", "persons": []}]
}

**Input:** "Leg(io) XXII Pr(imigenia) p(ia) f(idelis) / Imp(eratori) Caes(ari) / [pro salute]"
**Output:**
{
  "results": [{"id": "GA5", "persons": []}]
}

**Input:** "D(is) M(anibus) / Aurelia / Litaviccae / ann(orum) XXV / coniugi piissimae / M(arcus) Aur(elius) Acceptus"
**Output:**
{
  "results": [{"id": "GA6", "persons": [
    {"praenomen": null, "nomen": "Aurelia", "cognomen": "Litavicca", "gender": "female", "status": "pia, coniunx", "raw_name": "Aurelia Litaviccae"},
    {"praenomen": "Marcus", "nomen": "Aurelius", "cognomen": "Acceptus", "gender": "male", "status": null, "raw_name": "M. Aur. Acceptus"}
  ]}]
}"""

    elif province.lower() in ('dalmatia', 'pannonia superior', 'pannonia inferior',
                              'noricum', 'dacia', 'moesia superior', 'moesia inferior'):
        extra_examples = """
**Input:** "Bato Platoris f(ilius) eq(ues) alae / Claudiae novae / vix(it) an(nos) XXXV / Epicadus f(ilius) p(osuit)"
**Output:**
{
  "results": [{"id": "D1", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Bato", "gender": "male", "status": "eques alae Claudiae novae", "raw_name": "Bato Platoris f."},
    {"praenomen": null, "nomen": null, "cognomen": "Plator", "gender": "male", "status": "pater", "raw_name": "Platoris"},
    {"praenomen": null, "nomen": null, "cognomen": "Epicadus", "gender": "male", "status": "filius", "raw_name": "Epicadus f."}
  ]}]
}

**Input:** "D(is) M(anibus) / T(ito) Aurelio / Dasantis f(ilio) Batoni / vet(erano) leg(ionis) XI C(laudiae) / vixit an(nos) LV"
**Output:**
{
  "results": [{"id": "D2", "persons": [
    {"praenomen": "Titus", "nomen": "Aurelius", "cognomen": "Bato", "gender": "male", "status": "veteranus legionis XI Claudiae", "raw_name": "T. Aurelio Dasantis f. Batoni"}
  ]}]
}

**Input:** "Silvano / sacrum / vicus / [3]p[3]posu/it"
**Output:**
{
  "results": [{"id": "D3", "persons": []}]
}

**Input:** "D(is) M(anibus) / Val(erio) Valenti / domo Salona / vixit an(nos) XX"
**Output:**
{
  "results": [{"id": "D4", "persons": [
    {"praenomen": null, "nomen": "Valerius", "cognomen": "Valens", "gender": "male", "status": "domo Salona", "raw_name": "Val. Valenti"}
  ]}]
}

**Input:** "Ripanio Flaviano aedil(icia) potestate Claud(ii) Vir(uni) defuncto"
**Output:**
{
  "results": [{"id": "D5", "persons": [
    {"praenomen": null, "nomen": "Ripanius", "cognomen": "Flavianus", "gender": "male", "status": "aedilicia potestate Claudii Viruni", "raw_name": "Ripanio Flaviano"}
  ]}]
}

**Input:** "|(Hastata posterior) / |(centuria) Pol(l)i / Veri"
**Output:**
{
  "results": [{"id": "D6", "persons": [
    {"praenomen": null, "nomen": "Pollius", "cognomen": "Verus", "gender": "male", "status": null, "raw_name": "Pol(l)i Veri"}
  ]}]
}

**Input:** "C(aius) Sempronius C(ai) fil(ius) / Cl(audia) Marcellinus"
**Output:**
{
  "results": [{"id": "D7", "persons": [
    {"praenomen": "Gaius", "nomen": "Sempronius", "cognomen": "Marcellinus", "gender": "male", "status": "tribus: Claudia", "raw_name": "C. Sempronius C. fil. Cl. Marcellinus"}
  ]}]
}

**Input:** "I(ovi) O(ptimo) M(aximo) / et Gen(io) loci / v(otum) s(olvit) l(ibens) m(erito)"
**Output:**
{
  "results": [{"id": "D8", "persons": []}]
}"""
    else:
        # Generic examples for Roma, Italia, Hispania, Gallia, Germania, and all other provinces.
        # These cover freedman naming, senatorial tria nomina, and single-name slaves/peregrini.
        extra_examples = """
**Input:** "T(ito) Statilio T(iti) l(iberto) Apro / Statilia T(iti) l(iberta) Tyche / patrono optimo"
**Output:**
{
  "results": [{"id": "G1", "persons": [
    {"praenomen": "Titus", "nomen": "Statilius", "cognomen": "Aper", "gender": "male", "status": "libertus Titi", "raw_name": "T. Statilio T. l. Apro"},
    {"praenomen": null, "nomen": "Statilia", "cognomen": "Tyche", "gender": "female", "status": "liberta Titi", "raw_name": "Statilia T. l. Tyche"}
  ]}]
}

**Input:** "D(is) M(anibus) / L(ucio) Caecilio L(uci) f(ilio) / Volt(inia) Metello / IIvir(o) quinq(uennali)"
**Output:**
{
  "results": [{"id": "G2", "persons": [
    {"praenomen": "Lucius", "nomen": "Caecilius", "cognomen": "Metellus", "gender": "male", "status": "tribus: Voltinia, IIvir quinquennalis", "raw_name": "L. Caecilio L. f. Volt. Metello"}
  ]}]
}

**Input:** "Iovi O(ptimo) M(aximo) / pro salute / Philargyri / Caesaris ser(vi)"
**Output:**
{
  "results": [{"id": "G3", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Philargyrus", "gender": "male", "status": "servus Caesaris", "raw_name": "Philargyri"}
  ]}]
}

**Input:** "C(aio) Aelio C(ai) f(ilio) Turpioni / mater"
**Output:**
{
  "results": [{"id": "G4", "persons": [
    {"praenomen": "Gaius", "nomen": "Aelius", "cognomen": "Turpio", "gender": "male", "status": null, "raw_name": "C. Aelio C. f. Turpioni"}
  ]}]
}

**Input:** "ann(orum) XIII / pia in suis / h(ic) s(ita) e(st) s(it) t(ibi) t(erra) l(evis)"
**Output:**
{
  "results": [{"id": "G5", "persons": []}]
}

**Input:** "Imp(eratori) Caes(ari) M(arco) Aurelio / Antonino Pio / Felici Aug(usto)"
**Output:**
{
  "results": [{"id": "G6", "persons": [
    {"praenomen": "Marcus", "nomen": "Aurelius", "cognomen": "Antoninus", "gender": "male", "status": "Imperator Caesar, Pius, Felix, Augustus", "raw_name": "Imp. Caes. M. Aurelio Antonino Pio Felici Aug."}
  ]}]
}

**Input:** "D(is) M(anibus) / Felici C(ai) Iuli / ser(vo) / vix(it) ann(os) XX"
**Output:**
{
  "results": [{"id": "G7", "persons": [
    {"praenomen": null, "nomen": null, "cognomen": "Felix", "gender": "male", "status": "servus", "raw_name": "Felici"},
    {"praenomen": "Gaius", "nomen": "Iulius", "cognomen": null, "gender": "male", "status": "dominus", "raw_name": "C. Iuli"}
  ]}]
}

**Input:** "Q(uintus) Pompeius Senecio / Roscius Murena / Coelius / legatus Aug(usti)"
**Output:**
{
  "results": [{"id": "G8", "persons": [
    {"praenomen": "Quintus", "nomen": "Pompeius", "cognomen": "Senecio Roscius Murena Coelius", "gender": "male", "status": "legatus Augusti", "raw_name": "Q. Pompeius Senecio Roscius Murena Coelius"}
  ]}]
}"""

    return f"""You are an expert Latin epigrapher specializing in the Roman inscriptions of {province}.
You will be provided with a list of inscriptions, each with a unique ID.
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
1. Deconstruct the name into praenomen, nomen, and cognomen using the rules below.
2. Identify gender ('male', 'female', or 'unknown') and social/professional status markers.
3. Expand standard abbreviations (e.g., 'L.' to 'Lucius', 'M.' to 'Marcus', 'f.' to 'filius').
4. fragmentary flag: set fragmentary=true ONLY when the name's OWN tokens are damaged — i.e. the raw_name you record contains a bracket: a restored reading ([P], [abc]), a gap ([3], [---]), or a trailing unclosed '['. If raw_name contains NO bracket, fragmentary MUST be false — even when other parts of the inscription are damaged. A complete, legible name on a broken stone is NOT fragmentary. When a name is cut off by a lacuna, keep the bracket in raw_name (e.g. 'Aurelius Saturn[3]', 'Iulius Roga[') so the damage stays visible. Do NOT set fragmentary=true for unresolved abbreviations or parenthetical expansions like '(ius)'.
5. Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons list.

INSCRIPTION CONVENTIONS:
- '[abc]' = letters damaged on stone but restored by editors. Treat as present; but flag the name as fragmentary (see rule 4).
- '[3]' or '[---]' = a lacuna of N missing characters. The name is INCOMPLETE.
- '<a=b>' = letter 'b' was inscribed in place of 'a'. Use 'a'.
- '{{abc}}' = letters erroneously engraved on the stone; DELETE them. 'Br{{p}}ituenda' → 'Brituenda'.
- '/' = line break. Ignore.
- '(...)' = editorial expansion. ALWAYS use the expanded form. Never store just the abbreviated letter(s). Example: 'C(a)ecil(ius)' → 'Caecilius', 'Aur(elius)' → 'Aurelius', 'Val(erio)' → 'Valerius'.

PRAENOMEN RULES:
- Only these 18 names are valid praenomina: {', '.join(sorted(PRAENOMINA))}
- Iulius, Flavius, Aurelius, Valerius, etc. are NOMINA, not praenomina.
- If only one name is present, classify it as cognomen.
- Filiation praenomen: when a praenomen appears in filiation context (e.g. 'C. f(iliae)', 'L. f(ilii)'), that praenomen belongs to the FATHER, not the subject. Example: 'Baebiae C(ai) f(iliae) Crinitae' → subject is Baebia Crinita (female), status='filia Cai'. Do NOT assign 'Caius' as the subject's own praenomen.

NOMEN vs COGNOMEN:
- In two-name sequences (e.g., 'Tonneia Restuta'), the first is almost always a NOMEN and the second a COGNOMEN.
- Common nomina to watch for: Tonneia, Aemilia, Iulia, Flavia, Aurelia, Maria, Claudia.

TRIBUS:
- These are Roman voting tribes, not nomina. Record in status as 'tribus: X':
- {', '.join(sorted(TRIBUS))}
- Tribus may be abbreviated: Cl. or Cl(audia) = Claudia, Fab. = Fabia, Volt. = Voltinia, Pal. = Palatina. An abbreviated tribus typically appears between the filiation marker (f. / fil.) and the cognomen — expand it and record as 'tribus: [full name]'.

CASE NORMALIZATION — store every name in the NOMINATIVE case. This is mandatory and the single most common error. The stone almost always shows names in the dative (honouring the deceased: 'Iulio', 'Geminio Crescenti', 'Tonneiae') or genitive (filiation/possession: 'Iulii', 'Aviani', 'Gargili'). DECLINE them back to the nominative — never copy the inflected surface form into a name field.
- SELF-CHECK (nomen): a nominative nomen ends in -us, -ius, or (feminine) -a. If you are about to write a nomen ending in -o or -i, you have copied a dative/genitive — fix it: Geminio→Geminius, Apertio→Apertius, Porcio→Porcius, Lurio→Lurius, Axio→Axius, Oppi→Oppius, Sergi→Sergius, Viri→Virius.
- Genitive -i → nominative -us: Aviani→Avianus, Gargili→Gargilius, Caecili→Caecilius, Septi→Septius
- Genitive -ii → nominative -ius: Iulii→Iulius, Flavii→Flavius, Aquilii→Aquilius
- Genitive/dative -ae → nominative -a: Tonneiae→Tonneia, Iuliae→Iulia, Aemiliae→Aemilia
- Dative -o → nominative -us (applies to BOTH nomina and cognomina): Iulio→Iulius, Aurelio→Aurelius, Geminio→Geminius, Rufo→Rufus, Marcello→Marcellus, Saturnino→Saturninus.
- 3rd-declension cognomina (dative/genitive → nominative): Valenti→Valens, Crescenti/Crescente→Crescens, Victori/Victoris→Victor, Magni→Magnus, Apri→Aper, Materni→Maternus.
- Narrow exception: a FEW cognomina are genuinely nominative already in -o (their genitive is -onis): Cato, Fronto, Hilario, Pantaleo, Naso. Leave only THESE in -o; convert every other -o form to -us.
- The raw_name field must preserve the original inflected text exactly as it appears.

STATUS extraction:
- Status should only contain descriptive titles (miles, veteranus, uxor, filius, etc.).
- NEVER put name elements (like 'Ofelius') into the status field.
- Adjectives 'pius' / 'pia' belong in status, NEVER in cognomen. Their inflected forms 'Piae' (gen./dat. f.) and 'Pio' (dat. m.) are NOT names — even when capitalised, record them as 'pia'/'pius' in status. Example: 'Aemiliae / Piae / ux(ori)' → nomen=Aemilia, cognomen=null, status='pia, uxor'.
- Imperial epithets (Pius, Felix, Invictus, Victor, Fortis, and Maximus when used as an honorary epithet) belong in status, NOT in cognomen. The emperor's dynastic cognomen (Antoninus, Severus, Traianus, Hadrianus, Commodus, etc.) goes in cognomen; epithets go in status. 'Imp. Caes. M. Aurelio Antonino Pio Felici Aug.' → praenomen=Marcus, nomen=Aurelius, cognomen=Antoninus, status='Imperator Caesar, Pius, Felix, Augustus'.

NAME FIELD RULES:
- praenomen, nomen, and cognomen fields must contain ONLY name text.
- Never put gender values ('male', 'female') or status words into name fields.
- If a name element is missing or uncertain, use null.
- **raw_name** must contain ONLY the original text tokens belonging to THAT specific individual. Never include separators (et, cum) or names of other people in this field.

NAME COHERENCE:
- Consecutive Latin name elements without a separator ('et', 'cum', verbs, filiation) belong to the SAME person.
- Separators that split persons: 'et', 'cum', filiation (filius, filia, uxor, mater, pater, soror, frater), or verbs (vixit, fecit, posuit).
- Filiation direction: in 'Bato Platoris f(ilius)', Bato is the subject (his inscription), Plator is the father — extract Plator with status 'pater'. The 'f(ilius)' belongs to Bato's filiation, NOT to Plator's status.
- Relational nouns WITHOUT a name: if 'mater', 'pater', 'uxor', 'coniunx' (coniugi, coniuge), 'frater', 'soror', 'nata', 'filius' appear in the inscription but NO personal name follows or precedes them for that individual, do NOT extract a person for them. E.g. "Gaio Aelio Turpioni / mater" → extract Gaius Aelius Turpio only; do not create a second person named 'mater'. Similarly, 'coniugi bene merenti' is a dedicatory formula that describes the deceased — absorb it into status of the main person, do NOT create a second blank person.
- Formula-only fragments: if the visible text contains ONLY formula words (annorum, pia/pius in suis, hic situs est, sit tibi terra levis, etc.) with no recognisable name token, return persons: [] for that record.
- Polyonymy: Late Republican/Imperial aristocrats and senators sometimes bear 3-5 cognomina in a continuous sequence. When multiple name tokens appear in sequence after a nomen without a verb, separator ('et'), or filiation marker, treat them as additional cognomina for the SAME person — do NOT split into multiple persons. E.g. 'Q. Pompeius Senecio Roscius Murena Coelius' → one person, cognomen='Senecio Roscius Murena Coelius'.

EXAMPLES:
{extra_examples}

**Input:** "D(is) M(anibus) / Tonneiae / Restutae p(ia)"
**Output:**
{{
  "results": [{{
    "id": "T1",
    "persons": [
      {{"praenomen": null, "nomen": "Tonneia", "cognomen": "Restuta", "gender": "female", "status": "pia", "raw_name": "Tonneiae Restutae"}}
    ]
  }}]
}}

**Input:** "Memori(a)e C(ai) / Ann(a)ei Fortu/nati C(aius) Fl(avius) Satul/lus"
**Output:**
{{
  "results": [{{
    "id": "T2",
    "persons": [
      {{"praenomen": "Gaius", "nomen": "Annaeus", "cognomen": "Fortunatus", "gender": "male", "status": null, "raw_name": "C. Ann(a)ei Fortunati"}},
      {{"praenomen": "Gaius", "nomen": "Flavius", "cognomen": "Satullus", "gender": "male", "status": null, "raw_name": "C. Fl. Satullus"}}
    ]
  }}]
}}

**Input:** "D(is) M(anibus) / Gargili / [3]"
**Output:**
{{
  "results": [{{
    "id": "T3",
    "persons": [
      {{"praenomen": null, "nomen": "Gargilius", "cognomen": null, "gender": "unknown", "status": null, "raw_name": "Gargili", "fragmentary": true}}
    ]
  }}]
}}

**Input:** "Rogatus / Faustiniani / vixit an(nos) XLV / h(ic) s(itus) e(st)"
**Output:**
{{
  "results": [{{
    "id": "T4",
    "persons": [
      {{"praenomen": null, "nomen": null, "cognomen": "Rogatus", "gender": "male", "status": null, "raw_name": "Rogatus"}},
      {{"praenomen": null, "nomen": null, "cognomen": "Faustinianus", "gender": "male", "status": "pater", "raw_name": "Faustiniani"}}
    ]
  }}]
}}

**Input:** "D(is) M(anibus) s(acrum) / Aemiliae / Piae / ux(ori)"
**Output:**
{{
  "results": [{{
    "id": "T5",
    "persons": [
      {{"praenomen": null, "nomen": "Aemilia", "cognomen": null, "gender": "female", "status": "pia, uxor", "raw_name": "Aemiliae Piae"}}
    ]
  }}]
}}

**Input:** "Titiae / L(uci) f(iliae) / [P]roculae / ["
**Output:**
{{
  "results": [{{
    "id": "T6",
    "persons": [
      {{"praenomen": null, "nomen": "Titia", "cognomen": "Procula", "gender": "female", "status": null, "raw_name": "Titiae [P]roculae", "fragmentary": true}}
    ]
  }}]
}}

**Input:** "L(ucio) Geminio / Crescenti / vix(it) an(nos) XL"
**Output:**
{{
  "results": [{{
    "id": "T7",
    "persons": [
      {{"praenomen": "Lucius", "nomen": "Geminius", "cognomen": "Crescens", "gender": "male", "status": null, "raw_name": "L. Geminio Crescenti", "fragmentary": false}}
    ]
  }}]
}}
"""
