"""Conservative cross-province cluster merging.

Reads all per-province cluster summary CSVs and geojson files, extracts
high-confidence cluster representatives, and merges clusters across
provinces that likely refer to the same individual.

Conservative matching criteria (ALL must pass):
  1. cluster_confidence = 'high' in both clusters
  2. is_imperial = False in both clusters
  3. praenomen, nomen, cognomen all present in both
  4. nomen (normalized) is not 'aurelius' (Antoniniana effect)
  5. Both clusters have date data (from inscription-level dates)
  6. Date ranges genuinely overlap
  7. Praenomens compatible (not conflicting after variant normalization)
  8. Nomen AND cognomen 6-char prefix match after Latin orthographic normalization

Outputs:
  data/global_cluster_map.csv
    province, local_cluster_id, global_cluster_id, global_cluster_size

Downstream consumer:
  scripts/10_build_sqlite.py reads this file and annotates person objects
  with global_cluster_id / global_cluster_size before writing to SQLite.
"""
import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Copied from 08_cluster_attestations.py — must stay in sync
# ---------------------------------------------------------------------------

PREFIX_LEN = 6

PRAENOMEN_NORM = {
    'caius': 'gaius',
    'caia': 'gaia',
    'caeso': 'kaeso',
}


def normalize_latin_orthography(text: Optional[str]) -> Optional[str]:
    """Normalise Latin spelling variants to a canonical form."""
    if not text:
        return text
    s = text.lower()
    s = s.replace('ae', 'e').replace('oe', 'e')
    s = s.replace('v', 'u')
    # strip leading/trailing h, and common h-insertion points
    s = s.replace('ph', 'f')
    s = s.replace('th', 't')
    s = s.replace('ch', 'c')
    # double consonants → single
    for c in 'lmnrst':
        s = s.replace(c + c, c)
    return s.strip()


def normalize_praenomen(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return PRAENOMEN_NORM.get(name.lower().strip(), name.lower().strip())


def compatible_praenomen(a: Optional[str], b: Optional[str]) -> bool:
    """Return False only if both are present and they clearly differ."""
    if not a or not b:
        return True
    return normalize_praenomen(a) == normalize_praenomen(b)


def prefix(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    n = normalize_latin_orthography(s)
    return n[:PREFIX_LEN] if n else None


# ---------------------------------------------------------------------------
# UnionFind for cluster merging
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self._parent: dict = {}
        self._rank: dict = {}

    def find(self, x):
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _parse_date_range(date_range: str) -> Optional[tuple[int, int]]:
    """Parse 'YYYY..YYYY' → (from, to) ints, or None if not parseable."""
    s = date_range.strip()
    if '..' not in s:
        return None
    parts = s.split('..')
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, TypeError):
        return None


def _dates_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if the two [from, to] ranges overlap (inclusive)."""
    return a[0] <= b[1] and b[0] <= a[1]


def load_province_clusters(
    data_dir: Path,
    webapp_data_dir: Path,
    province: str,
) -> dict[int, dict]:
    """
    Load cluster representatives for one province.

    Returns dict keyed by local cluster_id. Each value is a dict with:
      praenomen, nomen, cognomen, cluster_size, is_imperial,
      cluster_confidence, date_range (tuple or None)
    """
    summary_path = data_dir / f"clusters_summary_{province}.csv"
    if not summary_path.exists():
        return {}

    # Build cluster representatives from summary CSV
    clusters: dict[int, dict] = {}
    with open(summary_path) as f:
        for row in csv.DictReader(f):
            try:
                cid = int(row['cluster_id'])
            except (ValueError, KeyError):
                continue
            clusters[cid] = {
                'cluster_id': cid,
                'province': province,
                'praenomen': row.get('praenomen', '').strip() or None,
                'nomen': row.get('nomen', '').strip() or None,
                'cognomen': row.get('cognomen', '').strip() or None,
                'cluster_size': int(row.get('cluster_size', 1)),
                'is_imperial': row.get('is_imperial', 'False').strip() == 'True',
                'cluster_confidence': row.get('cluster_confidence', '').strip(),
                'date_range': _parse_date_range(row.get('date_range', '')),
            }

    # Augment date ranges from inscription-level geojson dates
    geojson_path = webapp_data_dir / f"inscriptions_{province}.geojson"
    if geojson_path.exists():
        date_froms: dict[int, list[int]] = {}
        date_tos: dict[int, list[int]] = {}

        with open(geojson_path) as f:
            geojson = json.load(f)

        for feat in geojson.get('features', []):
            props = feat.get('properties', {})
            df = props.get('date_from')
            dt = props.get('date_to')
            for person in props.get('persons', []):
                cid = person.get('cluster_id')
                if cid is None:
                    continue
                if df is not None:
                    date_froms.setdefault(cid, []).append(int(df))
                if dt is not None:
                    date_tos.setdefault(cid, []).append(int(dt))

        for cid, cluster in clusters.items():
            if cluster['date_range'] is not None:
                continue  # already have dates from summary CSV
            froms = date_froms.get(cid, [])
            tos = date_tos.get(cid, [])
            if froms and tos:
                cluster['date_range'] = (min(froms), max(tos))

    return clusters


# ---------------------------------------------------------------------------
# Cross-province matching
# ---------------------------------------------------------------------------

def is_eligible(cluster: dict) -> bool:
    """True if this cluster is a candidate for cross-province merging."""
    if cluster['cluster_confidence'] != 'high':
        return False
    if cluster['is_imperial']:
        return False
    if not cluster['praenomen']:
        return False
    if not cluster['nomen']:
        return False
    if not cluster['cognomen']:
        return False
    if cluster['date_range'] is None:
        return False
    # Extra caution: skip Aurelius nomen (Antoniniana name proliferation)
    if normalize_latin_orthography(cluster['nomen']) == normalize_latin_orthography('aurelius'):
        return False
    return True


def names_match(a: dict, b: dict) -> bool:
    """True if both names are compatible under conservative cross-province criteria."""
    if not compatible_praenomen(a['praenomen'], b['praenomen']):
        return False
    np_a = prefix(a['nomen'])
    np_b = prefix(b['nomen'])
    if not np_a or not np_b or np_a != np_b:
        return False
    cp_a = prefix(a['cognomen'])
    cp_b = prefix(b['cognomen'])
    if not cp_a or not cp_b or cp_a != cp_b:
        return False
    return True


def find_cross_province_merges(
    all_clusters: list[dict],
) -> list[tuple]:
    """
    Return list of (key_a, key_b) pairs where key = (province, cluster_id).

    Uses bucket approach: group by (nomen_prefix, cognomen_prefix) then check
    each bucket for compatible pairs from different provinces.
    """
    from collections import defaultdict

    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for c in all_clusters:
        key = (prefix(c['nomen']), prefix(c['cognomen']))
        if key[0] and key[1]:
            buckets[key].append(c)

    pairs = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i], bucket[j]
                if a['province'] == b['province']:
                    continue  # same province — per-province script handles this
                if not names_match(a, b):
                    continue
                if not _dates_overlap(a['date_range'], b['date_range']):
                    continue
                pairs.append(
                    ((a['province'], a['cluster_id']), (b['province'], b['cluster_id']))
                )
    return pairs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    project_root = Path(__file__).parent.parent
    data_dir = project_root / 'data'
    webapp_data_dir = project_root / 'webapp' / 'data'
    output_path = data_dir / 'global_cluster_map.csv'

    # Discover provinces from cluster summary files
    provinces = sorted(
        p.stem.removeprefix('clusters_summary_')
        for p in data_dir.glob('clusters_summary_*.csv')
        if p.stem != 'clusters_summary'
    )
    print(f"Found {len(provinces)} provinces")

    # Load all province clusters
    all_clusters: list[dict] = []
    eligible: list[dict] = []
    for prov in provinces:
        clusters = load_province_clusters(data_dir, webapp_data_dir, prov)
        all_clusters.extend(clusters.values())
        prov_eligible = [c for c in clusters.values() if is_eligible(c)]
        eligible.extend(prov_eligible)
        if prov_eligible:
            print(f"  {prov}: {len(clusters)} clusters, {len(prov_eligible)} eligible")

    print(f"\nTotal eligible for cross-province matching: {len(eligible)}")

    if len(eligible) < 2:
        print("Not enough eligible clusters for cross-province matching.")
        _write_empty(output_path)
        return

    # Find matching pairs
    pairs = find_cross_province_merges(eligible)
    print(f"Found {len(pairs)} matching cross-province pairs")

    if not pairs:
        print("No cross-province merges found.")
        _write_empty(output_path)
        return

    # Assign global cluster IDs via UnionFind
    uf = UnionFind()
    for key_a, key_b in pairs:
        uf.union(key_a, key_b)

    # Collect all keys that appear in any merge pair
    merged_keys: set = set()
    for key_a, key_b in pairs:
        merged_keys.add(key_a)
        merged_keys.add(key_b)

    # Group by global root
    from collections import defaultdict
    root_to_keys: dict = defaultdict(list)
    for key in merged_keys:
        root_to_keys[uf.find(key)].append(key)

    # Assign sequential global IDs (1-indexed)
    # Global cluster size = sum of local cluster sizes
    cluster_lookup = {(c['province'], c['cluster_id']): c for c in all_clusters}

    rows = []
    for gid, (root, keys) in enumerate(sorted(root_to_keys.items()), start=1):
        global_size = sum(
            cluster_lookup[(prov, cid)]['cluster_size']
            for prov, cid in keys
            if (prov, cid) in cluster_lookup
        )
        province_list = sorted(set(prov for prov, _ in keys))
        for prov, cid in sorted(keys):
            rows.append({
                'province': prov,
                'local_cluster_id': cid,
                'global_cluster_id': gid,
                'global_cluster_size': global_size,
                'global_province_count': len(province_list),
                'global_provinces': '; '.join(province_list),
            })

    rows.sort(key=lambda r: (r['global_cluster_id'], r['province'], r['local_cluster_id']))

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'province', 'local_cluster_id', 'global_cluster_id',
            'global_cluster_size', 'global_province_count', 'global_provinces',
        ])
        writer.writeheader()
        writer.writerows(rows)

    total_global = len(root_to_keys)
    total_local = len(merged_keys)
    print(f"\nWrote {output_path}")
    print(f"  {total_global} global clusters spanning {total_local} local clusters")
    print(f"  {rows[0]['global_provinces'] if rows else 'n/a'} (first example)")

    # Show top matches
    print("\nTop cross-province merges:")
    for root, keys in sorted(root_to_keys.items(),
                             key=lambda kv: -sum(cluster_lookup.get(k, {}).get('cluster_size', 0) for k in kv[1])):
        total_sz = sum(cluster_lookup.get(k, {}).get('cluster_size', 0) for k in keys)
        rep = cluster_lookup.get(keys[0])
        name = ' '.join(filter(None, [rep.get('praenomen'), rep.get('nomen'), rep.get('cognomen')])) if rep else '?'
        provs = ', '.join(f"{p}#{cid}" for p, cid in sorted(keys))
        print(f"  [{total_sz} att] {name!r}  ← {provs}")
        if root == list(sorted(root_to_keys.keys()))[min(9, total_global - 1)]:
            break


def _write_empty(path: Path):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'province', 'local_cluster_id', 'global_cluster_id',
            'global_cluster_size', 'global_province_count', 'global_provinces',
        ])
        writer.writeheader()
    print(f"Wrote empty {path}")


if __name__ == '__main__':
    main()
