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
    {"praenomen": null, "nomen": "Aemilia", "cognomen": "Victoria Fipiorina", "gender": "female", "status": null, "raw_name": "Aemilia Victoria Fipiorina"}
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
}"""

    return f"""You are an expert Latin epigrapher specializing in the Roman inscriptions of {province}.
You will be provided with a list of inscriptions, each with a unique ID.
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
1. Deconstruct the name into praenomen, nomen, and cognomen using the rules below.
2. Identify gender ('male', 'female', or 'unknown') and social/professional status markers.
3. Expand standard abbreviations (e.g., 'L.' to 'Lucius', 'M.' to 'Marcus', 'f.' to 'filius').
4. Set fragmentary=true ONLY if the name itself overlaps a lacuna marker ([---] or [3]) or is cut off mid-word. Do NOT set fragmentary=true for unresolved abbreviations or short names.
5. Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons list.

INSCRIPTION CONVENTIONS:
- '[abc]' = letters abc are damaged but restored by editors. Treat as present.
- '[3]' or '[---]' = a lacuna of N missing characters. The name is INCOMPLETE.
- '<a=b>' = letter 'b' was inscribed in place of 'a'. Use 'a'.
- '/' = line break. Ignore.
- '(...)' = editorial expansion. ALWAYS use the expanded form. Never store just the abbreviated letter(s). Example: 'C(a)ecil(ius)' → 'Caecilius', 'Aur(elius)' → 'Aurelius', 'Val(erio)' → 'Valerius'.

PRAENOMEN RULES:
- Only these 18 names are valid praenomina: {', '.join(sorted(PRAENOMINA))}
- Iulius, Flavius, Aurelius, Valerius, etc. are NOMINA, not praenomina.
- If only one name is present, classify it as cognomen.

NOMEN vs COGNOMEN:
- In two-name sequences (e.g., 'Tonneia Restuta'), the first is almost always a NOMEN and the second a COGNOMEN.
- Common nomina to watch for: Tonneia, Aemilia, Iulia, Flavia, Aurelia, Maria, Claudia.

TRIBUS:
- These are Roman voting tribes, not nomina. Record in status as 'tribus: X':
- {', '.join(sorted(TRIBUS))}

CASE NORMALIZATION — always store names in the NOMINATIVE case:
- Latin inscriptions put names in dative (for the deceased: 'Iulio', 'Tonneiae') or genitive (filiation/possession: 'Iulii', 'Aviani', 'Gargili'). Always convert to nominative.
- Genitive -i → nominative -us: Aviani→Avianus, Gargili→Gargilius, Caecili→Caecilius, Septi→Septius
- Genitive -ii → nominative -ius: Iulii→Iulius, Flavii→Flavius, Aquilii→Aquilius
- Genitive -ae → nominative -a: Tonneiae→Tonneia, Iuliae→Iulia, Aemiliae→Aemilia
- Dative -o → nominative -us: Iulio→Iulius, Aurelio→Aurelius, Valenti→Valens (3rd decl.)
- Dative -ae → nominative -a: same as genitive -ae above
- Dative/genitive 3rd decl. (Catoni→Cato, Marcioni→Marcion, Frontoni→Fronto) — remove the dative ending
- The raw_name field must preserve the original text exactly as it appears.

STATUS extraction:
- Status should only contain descriptive titles (miles, veteranus, uxor, filius, etc.).
- NEVER put name elements (like 'Ofelius') into the status field.
- Adjectives like 'pius' or 'pia' belong in status.

NAME FIELD RULES:
- praenomen, nomen, and cognomen fields must contain ONLY name text.
- Never put gender values ('male', 'female') or status words into name fields.
- If a name element is missing or uncertain, use null.
- **raw_name** must contain ONLY the original text tokens belonging to THAT specific individual. Never include separators (et, cum) or names of other people in this field.

NAME COHERENCE:
- Consecutive Latin name elements without a separator ('et', 'cum', verbs, filiation) belong to the SAME person.
- Separators that split persons: 'et', 'cum', filiation (filius, filia, uxor, mater, pater, soror, frater), or verbs (vixit, fecit, posuit).

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
"""
