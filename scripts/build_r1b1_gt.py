"""
Build a Romans 1by1 ground truth dataset and merge it with LIRE.

Downloads all pages of rpeople.xls and rinscriptions.xls from Romans 1by1,
iterating by province to bypass the default 20k record export limit.
Resolves inscription codes to EDCS IDs via the TM→EDCS bridge in LIRE,
and writes a GT file in the same format used by 05_evaluate_ner.py.

Usage:
    python3 scripts/build_r1b1_gt.py               # full run
    python3 scripts/build_r1b1_gt.py --dry-run      # test first 2 provinces only
    python3 scripts/build_r1b1_gt.py --skip-download # reuse cached files

Output:
    R1B1_GT_PATH (see scripts/config.py) — {EDCS-ID: [{"praenomen":..,"nomen":..,"cognomen":..}, ...]}
"""

import os, re, json, time, argparse, sys
from collections import defaultdict
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import LIRE_PATH, R1B1_GT_PATH

BASE_URL = "http://romans1by1.com"
CACHE_DIR = "data/r1b1_cache"
OUT_PATH   = str(R1B1_GT_PATH)

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
# has missing rows vs R1b1 internal count, causing rank drift that corrupts the bridge.
UNRELIABLE_ABBREVS = {'MI', 'PS', 'MS'}


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
# Download all pages for all provinces
# ---------------------------------------------------------------------------

def download_all_by_province(endpoint, parser, label, dry_run):
    all_rows = []
    provinces = sorted(PROVINCE_ABBREVS.keys())
    
    # Correct Ransack parameter names identified from HTML source
    if 'people' in endpoint:
        prov_param = "q[rinscriptions_rprovince_name_cont]"
    else:
        prov_param = "q[rprovince_name_cont]"

    if dry_run:
        provinces = provinces[:2]
        
    for prov in provinces:
        print(f"\n--- Province: {prov} ---")
        prov_slug = prov.lower().replace(' ', '_')
        prov_encoded = urllib.parse.quote_plus(prov)
        
        for page in range(1, 1000): # Hard limit to prevent infinite loops
            # Use the correct Ransack query syntax
            url = f"{BASE_URL}/{endpoint}?{prov_param}={prov_encoded}&page={page}"
            cache = os.path.join(CACHE_DIR, f"{endpoint.replace('.xls','')}_{prov_slug}_p{page:03d}.bin")
            
            raw = fetch_page(url, cache)
            if raw is None:
                print(f"  [{label}] {prov} page {page}: fetch failed, skipping province")
                break
                
            _, rows = parser(raw)
            if not rows:
                print(f"  [{label}] {prov} page {page}: empty, moving to next province")
                break
                
            all_rows.extend(rows)
            print(f"  [{label}] {prov} page {page}: +{len(rows)} rows (total {len(all_rows)})")
            
            if dry_run and page >= 1:
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
        # Support both old and new LIRE field names for TM URI/ID
        tm = str(p.get('trismegistos_uri') or p.get('idno_tm') or '').strip()
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
            continue
            
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
    print(f"  Unreliable prov:  {stats['unreliable_province']:,}  (MI/PS/MS excluded — rank drift too large)")
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
                        help='Download only first 2 provinces (testing)')
    parser.add_argument('--skip-download', action='store_true',
                        help='Use cached files only, skip HTTP requests')
    parser.add_argument('--province', type=str, help='Only download/process a specific province')
    args = parser.parse_args()

    # Step 1: download
    if not args.skip_download:
        provinces = [args.province] if args.province else sorted(PROVINCE_ABBREVS.keys())
        if args.dry_run and not args.province:
            provinces = provinces[:2]
        
        people_rows = []
        inscription_rows = []
        
        # Refactor download logic to allow per-province targeting
        for prov in provinces:
            print(f"\n=== Province: {prov} ===")
            prov_slug = prov.lower().replace(' ', '_')
            prov_encoded = urllib.parse.quote_plus(prov)
            
            # Download people
            p_param = "q[rinscriptions_rprovince_name_cont]"
            for page in range(1, 1000):
                url = f"{BASE_URL}/rpeople.xls?{p_param}={prov_encoded}&page={page}"
                cache = os.path.join(CACHE_DIR, f"rpeople_{prov_slug}_p{page:03d}.bin")
                raw = fetch_page(url, cache)
                if raw is None: break
                _, rows = parse_html_table(raw)
                if not rows: break
                people_rows.extend(rows)
                print(f"  [people] {prov} page {page}: +{len(rows)} rows")
                if args.dry_run: break
            
            # Download inscriptions
            i_param = "q[rprovince_name_cont]"
            for page in range(1, 1000):
                url = f"{BASE_URL}/rinscriptions.xls?{i_param}={prov_encoded}&page={page}"
                cache = os.path.join(CACHE_DIR, f"rinscriptions_{prov_slug}_p{page:03d}.bin")
                raw = fetch_page(url, cache)
                if raw is None: break
                _, rows = parse_xml_table(raw)
                if not rows: break
                inscription_rows.extend(rows)
                print(f"  [inscriptions] {prov} page {page}: +{len(rows)} rows")
                if args.dry_run: break

    else:
        print("\n=== Loading from cache ===")
        people_rows, inscription_rows = [], []
        if not os.path.exists(CACHE_DIR):
            print(f"ERROR: {CACHE_DIR} not found")
            return
            
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
