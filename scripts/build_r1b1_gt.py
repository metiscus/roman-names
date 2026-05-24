"""
Build a Romans 1by1 ground truth dataset and merge it with LIRE.

Downloads all pages of rpeople.xls and rinscriptions.xls from Romans 1by1,
resolves inscription codes to EDCS IDs via the TM→EDCS bridge in LIRE,
and writes a GT file in the same format used by 05_evaluate_ner.py.

Usage:
    python3 scripts/build_r1b1_gt.py               # full run
    python3 scripts/build_r1b1_gt.py --dry-run      # test first 2 pages only
    python3 scripts/build_r1b1_gt.py --skip-download # reuse cached files

Output:
    data/r1b1_gt.json   — {EDCS-ID: [{"praenomen":..,"nomen":..,"cognomen":..}, ...]}
"""

import os, re, json, time, argparse
from collections import defaultdict

BASE_URL = "http://romans1by1.com"
CACHE_DIR = "data/r1b1_cache"
OUT_PATH   = "data/r1b1_gt.json"
LIRE_PATH  = "data/LIRE_v1-2.geojson"

PROVINCE_ABBREVS = {
    'Moesia Inferior':              'MI',
    'Moesia Superior':              'MS',
    'Dacia Superior':               'DS',
    'Dacia Inferior':               'DI',
    'Dacia Porolissensis':          'DP',
    'Dacia':                        'D',
    'Pannonia Superior':            'PS',
    'Pannonia Inferior':            'PI',
    'Dalmatia':                     'DAL',
    'Noricum':                      'NOR',
    'Raetia':                       'RAET',
    'Thrace':                       'T',
    'Germania Superior':            'GS',
    'Germania Inferior':            'GI',
    'Britannia':                    'BRIT',
    'Gallia Narbonensis':           'GN',
    'Gallia Lugdunensis':           'GL',
    'Belgica':                      'BELG',
    'Hispania Citerior':            'HC',
    'Baetica':                      'BAET',
    'Lusitania':                    'LUS',
    'Aquitania':                    'AQ',
    'Africa':                       'AF',
    'Numidia':                      'NUM',
    'Italia':                       'IT',
    'Sicilia':                      'SIC',
    'Etruria':                      'ET',
    'Sardinia':                     'SAR',
    'Bithynia et Pontus':           'BP',
    'Asia':                         'A',
    'Alpes Maritimae':              'AP',
}

# Province abbreviations excluded from GT because the rinscriptions.xls export
# has too many missing rows (R1b1 internal rank ≠ our reconstructed rank):
#   MI: 63 missing → up to 63-position drift → nearly all GT entries are wrong
#   PS: 4 missing → variable drift → spot-checks confirm wrong matches
UNRELIABLE_ABBREVS = {'MI', 'PS'}


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

DELAY_SECONDS = 3
USER_AGENT = "name-research-bot/1.0 (academic; https://github.com/metiscus/roman-names)"

def fetch_page(url, cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return f.read()
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        return None
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'wb') as f:
        f.write(data)
    time.sleep(DELAY_SECONDS)
    return data


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_html_table(raw):
    """Parse HTML-disguised XLS (rpeople.xls format)."""
    try:
        html = raw.decode('utf-8', errors='replace')
    except Exception:
        html = str(raw)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
    if not rows:
        return [], []
    def cells(row):
        return [re.sub(r'<[^>]+>', '', c).strip()
                for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row,
                                    re.DOTALL | re.IGNORECASE)]
    headers = cells(rows[0])
    data = [dict(zip(headers, cells(r))) for r in rows[1:] if cells(r)]
    return headers, data


def parse_xml_table(raw):
    """Parse SpreadsheetML XLS (rinscriptions.xls format)."""
    try:
        xml = raw.decode('utf-8', errors='replace')
    except Exception:
        xml = str(raw)
    rows = re.findall(r'<Row[^>]*>(.*?)</Row>', xml, re.DOTALL | re.IGNORECASE)
    if not rows:
        return [], []
    def cells(row):
        return [re.sub(r'<[^>]+>', '', c).strip()
                for c in re.findall(r'<Cell[^>]*>(.*?)</Cell>', row,
                                    re.DOTALL | re.IGNORECASE)]
    headers = cells(rows[0])
    data = [dict(zip(headers, cells(r))) for r in rows[1:] if cells(r)]
    return headers, data


# ---------------------------------------------------------------------------
# Download all pages
# ---------------------------------------------------------------------------

def download_all(endpoint, parser, label, max_pages, dry_run):
    all_rows = []
    for page in range(1, max_pages + 1):
        url = f"{BASE_URL}/{endpoint}?page={page}"
        cache = os.path.join(CACHE_DIR, f"{endpoint.replace('.xls','')}_p{page:03d}.bin")
        raw = fetch_page(url, cache)
        if raw is None:
            print(f"  [{label}] page {page}: fetch failed, stopping")
            break
        _, rows = parser(raw)
        if not rows:
            print(f"  [{label}] page {page}: empty, stopping at {len(all_rows)} total")
            break
        all_rows.extend(rows)
        print(f"  [{label}] page {page}/{max_pages}: +{len(rows)} rows (total {len(all_rows)})")
        if dry_run and page >= 2:
            print(f"  [{label}] dry-run: stopping after 2 pages")
            break
    return all_rows


# ---------------------------------------------------------------------------
# Build TM → EDCS map from LIRE
# ---------------------------------------------------------------------------

def build_tm_to_edcs(lire_path):
    print("Building TM→EDCS map from LIRE...")
    with open(lire_path) as f:
        lire = json.load(f)
    tm_to_edcs = {}
    for feat in lire['features']:
        p = feat['properties']
        tm = str(p.get('idno_tm', '')).strip()
        edcs = p.get('EDCS-ID', '')
        if tm and edcs:
            tm_num = tm.split('/')[-1].strip()
            if tm_num.isdigit():
                tm_to_edcs[tm_num] = edcs
    print(f"  {len(tm_to_edcs):,} TM→EDCS mappings loaded")
    return tm_to_edcs


# ---------------------------------------------------------------------------
# Build inscription code → TM map from inscription XLS rows
# ---------------------------------------------------------------------------

def build_code_to_tm(inscription_rows):
    """
    Inscription code format: NNNNNPROV where NNNNN is the 1-based rank
    of the inscription within its province (sorted by global numeric ID).
    """
    print("Building inscription code→TM map...")

    # Build reverse abbrev map: province_name → abbrev
    # (some provinces may map to same abbrev — that's a data ambiguity in R1b1)
    name_to_abbrev = PROVINCE_ABBREVS

    # Group by province name, sort by global ID, assign per-province rank
    by_province = defaultdict(list)
    for row in inscription_rows:
        prov = row.get('Province', '').strip()
        try:
            gid = int(row.get('ID', 0))
        except ValueError:
            continue
        tm_raw = row.get('TM ID', '').strip()
        tm_num = tm_raw.split('/')[-1].strip() if tm_raw else ''
        if prov:
            by_province[prov].append((gid, tm_num))

    code_to_tm = {}
    for prov, entries in by_province.items():
        entries.sort(key=lambda x: x[0])   # sort by global ID
        abbrev = name_to_abbrev.get(prov)
        if not abbrev:
            # Derive a fallback abbrev from initials
            abbrev = ''.join(w[0].upper() for w in prov.split())
        for rank, (gid, tm_num) in enumerate(entries, 1):
            code = f"{rank:05d}{abbrev}"
            code_to_tm[code] = tm_num

    print(f"  {len(code_to_tm):,} inscription codes mapped")
    return code_to_tm


# ---------------------------------------------------------------------------
# Parse person rows into GT records
# ---------------------------------------------------------------------------

def clean_name(val):
    if not val:
        return None
    v = val.strip()
    return v if v else None


def parse_people(people_rows, code_to_tm, tm_to_edcs):
    print("Joining person records to EDCS IDs...")

    gt = defaultdict(list)   # EDCS-ID → list of person dicts
    stats = defaultdict(int)

    for row in people_rows:
        raw_code = row.get('Inscription code', '')
        # Code may have inscription type on next line — take first token
        code = raw_code.split()[0].strip() if raw_code.strip() else ''
        if not code:
            stats['no_code'] += 1
            continue

        m_abbrev = re.match(r'^\d+([A-Za-z]+)$', code)
        if m_abbrev and m_abbrev.group(1) in UNRELIABLE_ABBREVS:
            stats['unreliable_province'] += 1
            continue

        tm = code_to_tm.get(code)
        if tm is None:
            stats['code_not_found'] += 1
            continue
        if not tm:
            stats['no_tm_bridge'] += 1
            continue

        edcs = tm_to_edcs.get(tm, '')
        if not edcs:
            stats['tm_not_in_lire'] += 1
            continue

        praenomen = clean_name(row.get('Praenomen'))
        nomen     = clean_name(row.get('Nomen'))
        cognomen  = clean_name(row.get('Cognomen/Personal name'))

        if not any([praenomen, nomen, cognomen]):
            stats['no_name'] += 1
            continue

        gt[edcs].append({
            'praenomen': praenomen,
            'nomen':     nomen,
            'cognomen':  cognomen,
            'gender':    clean_name(row.get('Gender', '').lower()),
        })
        stats['ok'] += 1

    print(f"  Resolved:         {stats['ok']:,} person records")
    print(f"  Unreliable prov:  {stats['unreliable_province']:,}  (MI/PS excluded — rank drift too large)")
    print(f"  Code not found:   {stats['code_not_found']:,}  (province name mismatch / unknown)")
    print(f"  No TM bridge:     {stats['no_tm_bridge']:,}  (inscription has no TM ID in R1b1)")
    print(f"  TM not in LIRE:   {stats['tm_not_in_lire']:,}")
    print(f"  No name fields:   {stats['no_name']:,}")
    print(f"  No code:          {stats['no_code']:,}")
    print(f"  Unique EDCS IDs:  {len(gt):,}")
    return dict(gt)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build Romans 1by1 ground truth dataset")
    parser.add_argument('--dry-run', action='store_true',
                        help='Download only first 2 pages of each file (testing)')
    parser.add_argument('--skip-download', action='store_true',
                        help='Use cached files only, skip HTTP requests')
    args = parser.parse_args()

    max_pages = 2 if args.dry_run else 41

    # Step 1: download
    if not args.skip_download:
        print(f"\n=== Downloading people ({max_pages} pages) ===")
        people_rows = download_all('rpeople.xls', parse_html_table, 'people', max_pages, args.dry_run)
        print(f"\n=== Downloading inscriptions ({max_pages} pages) ===")
        inscription_rows = download_all('rinscriptions.xls', parse_xml_table, 'inscriptions', max_pages, args.dry_run)
    else:
        print("\n=== Loading from cache ===")
        people_rows, inscription_rows = [], []
        for fname in sorted(os.listdir(CACHE_DIR)):
            path = os.path.join(CACHE_DIR, fname)
            raw = open(path, 'rb').read()
            if 'rpeople' in fname:
                _, rows = parse_html_table(raw)
                people_rows.extend(rows)
            elif 'rinscriptions' in fname:
                _, rows = parse_xml_table(raw)
                inscription_rows.extend(rows)
        print(f"  Loaded {len(people_rows):,} people, {len(inscription_rows):,} inscriptions from cache")

    if not people_rows or not inscription_rows:
        print("ERROR: no data loaded")
        return

    # Step 2: build maps
    print()
    tm_to_edcs   = build_tm_to_edcs(LIRE_PATH)
    code_to_tm   = build_code_to_tm(inscription_rows)

    # Step 3: join
    print()
    gt = parse_people(people_rows, code_to_tm, tm_to_edcs)

    # Step 4: write
    os.makedirs('data', exist_ok=True)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {OUT_PATH}  ({len(gt):,} inscriptions, "
          f"{sum(len(v) for v in gt.values()):,} person records)")


if __name__ == '__main__':
    main()
