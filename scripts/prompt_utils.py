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
        extra_examples = ""

    return f"""You are an expert Latin epigrapher specializing in the Roman inscriptions of {province}.
You will be provided with a list of inscriptions, each with a unique ID.
Your task is to perform Named Entity Recognition (NER) on each inscription and extract personal names.

For each person identified:
1. Deconstruct the name into praenomen, nomen, and cognomen using the rules below.
2. Identify gender ('male', 'female', or 'unknown') and social/professional status markers.
3. Expand standard abbreviations (e.g., 'L.' to 'Lucius', 'M.' to 'Marcus', 'f.' to 'filius').
4. Set fragmentary=true if the name overlaps a lacuna or is otherwise visibly incomplete.
5. Return a JSON object containing a 'results' list, where each item matches an ID to its extracted persons list.

INSCRIPTION CONVENTIONS:
- '[abc]' = letters abc are damaged but restored by editors. Treat as present.
- '[3]' or '[---]' = a lacuna of N missing characters. The name is INCOMPLETE.
- '<a=b>' = letter 'b' was inscribed in place of 'a'. Use 'a'.
- '/' = line break. Ignore.
- '(...)' = editorial expansion. Use it.

PRAENOMEN RULES:
- Only these 18 names are valid praenomina: {', '.join(sorted(PRAENOMINA))}
- Iulius, Flavius, Aurelius, Valerius, etc. are NOMINA, not praenomina.
- If only one name is present, classify it as cognomen.

TRIBUS:
- These are Roman voting tribes, not nomina. Record in status as 'tribus: X':
- {', '.join(sorted(TRIBUS))}

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

**Input:** "Imperatori Caesari Lucio Septimio Severo Pio Pertinaci Augusto"
**Output:**
{{
  "results": [{{
    "id": "E1",
    "persons": [
      {{"praenomen": "Lucius", "nomen": "Septimius", "cognomen": "Severus", "gender": "male", "status": "emperor, Pius Pertinax", "raw_name": "Lucio Septimio Severo Pertinaci"}}
    ]
  }}]
}}
"""
