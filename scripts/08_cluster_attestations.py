"""Cluster name attestations to identify likely-same-individual groupings.

Produces two artifacts:
1. Updated parquet/CSV with three new columns:
   - cluster_id          int        sequential cluster identifier
   - cluster_size        int        number of attestations in the cluster
   - cluster_confidence  str        'high' / 'low' / 'excluded'
2. data/clusters_summary.csv — one row per cluster with representative name,
   members, findspots, date range, and flags. This is the file a classicist
   actually reads to skim the dataset.

Universe: all attestations EXCEPT is_deity / is_place / is_bare_epithet
flagged True (those aren't persons — they get cluster_confidence='excluded'
and no cluster_id). is_imperial and fragmentary records ARE included with
flags propagated through.

Match key:
- Primary pool (has nomen + cognomen): 6-char-prefix match on both.
- Single-cognomen pool (no nomen): 6-char-prefix on cognomen, with the
  stricter requirement that findspot text matches exactly. Single names
  collide too easily across the province to allow looser matching.

Compatibility checks within a bucket (all must pass for an edge):
- Praenomen: if both present and they differ (after spelling normalization
  Caius/Gaius etc.), no edge.
- Location: same findspot text (case-insensitive) OR coordinates within
  50km. Permissive if one or both have no location data.
- Date: date_from/date_to ranges must overlap. Permissive if either side
  has no date data.

Confidence labels:
- 'low': cluster is single-cognomen-only (no nomen in any member), OR is
  post-212 CE with majority Aurelius nomen (Constitutio Antoniniana
  effect — name-based clustering breaks down).
- 'high': everything else, including imperial clusters (which are real
  same-individuals just famous ones).
- 'excluded': flagged non-person (deity/place/epithet).

Singletons (cluster_size=1) are still assigned a cluster_id — every
in-universe attestation gets one.
"""
import json
import math
import os
import sys
from collections import defaultdict

import pandas as pd

KM_THRESHOLD = 50.0
PREFIX_LEN = 6
ANTONINIANA_YEAR = 212

# Praenomen spelling-variant normalization. We treat e.g. Caius and Gaius
# as the same praenomen for compatibility checks.
PRAENOMEN_NORM = {
    'caius': 'gaius',
    'caia': 'gaia',
    'caeso': 'kaeso',
}


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def prefix(s, n=PREFIX_LEN):
    if not s:
        return None
    return str(s).strip().lower()[:n]


def normalize_praenomen(s):
    if not s:
        return None
    s = str(s).strip().lower()
    return PRAENOMEN_NORM.get(s, s)


def parse_year(v):
    """LIRE date_from/date_to are stored as strings or numbers; tolerate both."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None


def compatible_praenomen(p1, p2):
    if p1 and p2 and p1 != p2:
        return False
    return True


def compatible_location(r1, r2, require_findspot_exact=False):
    """Spatial check between two records.

    With require_findspot_exact=True (single-cognomen pool), we demand that
    both records have findspot text and that those texts match exactly
    (case-insensitive). No coordinate fallback — single names collide too
    easily to allow proximity-based matching.
    """
    if require_findspot_exact:
        fs1, fs2 = r1.get('findspot'), r2.get('findspot')
        if not fs1 or not fs2:
            return False
        return fs1.lower().strip() == fs2.lower().strip()

    lat1, lon1 = r1.get('lat'), r2.get('lat')  # placeholder, real check below
    lat1, lon1 = r1.get('lat'), r1.get('lon')
    lat2, lon2 = r2.get('lat'), r2.get('lon')
    if lat1 is not None and lon1 is not None and lat2 is not None and lon2 is not None:
        return haversine_km(lat1, lon1, lat2, lon2) <= KM_THRESHOLD
    fs1, fs2 = r1.get('findspot'), r2.get('findspot')
    if fs1 and fs2:
        return fs1.lower().strip() == fs2.lower().strip()
    # One or both records have no location data — permissive.
    return True


def compatible_date(r1, r2):
    df1, dt1 = r1.get('date_from_year'), r1.get('date_to_year')
    df2, dt2 = r2.get('date_from_year'), r2.get('date_to_year')
    if df1 is None or dt1 is None or df2 is None or dt2 is None:
        return True
    return max(df1, df2) <= min(dt1, dt2)


def cluster_pool(records, indices, key_fn, require_findspot_exact=False):
    """Run union-find over a pool of records.

    `records` is the full list; `indices` is the subset to cluster.
    Returns a list of lists — each inner list is one cluster's indices.
    Singletons (indices that don't match anyone) are returned as single-element lists.
    """
    if not indices:
        return []

    # Map external indices -> compact 0..N for the union-find
    compact = {idx: i for i, idx in enumerate(indices)}
    uf = UnionFind(len(indices))

    # Bucket by key — only attestations sharing a key can possibly cluster
    buckets = defaultdict(list)
    for idx in indices:
        key = key_fn(records[idx])
        if key is None:
            continue
        buckets[key].append(idx)

    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            a = members[i]
            ra = records[a]
            for j in range(i + 1, len(members)):
                b = members[j]
                rb = records[b]
                if not compatible_praenomen(ra['praenomen_norm'], rb['praenomen_norm']):
                    continue
                if not compatible_location(ra, rb, require_findspot_exact):
                    continue
                if not compatible_date(ra, rb):
                    continue
                uf.union(compact[a], compact[b])

    components = defaultdict(list)
    for idx in indices:
        root = uf.find(compact[idx])
        components[root].append(idx)
    return list(components.values())


def build_records(universe_df):
    records = []
    for _, row in universe_df.iterrows():
        nomen = row.get('nomen') if pd.notna(row.get('nomen')) else None
        cognomen = row.get('cognomen') if pd.notna(row.get('cognomen')) else None
        praenomen = row.get('praenomen') if pd.notna(row.get('praenomen')) else None
        findspot = row.get('findspot') if pd.notna(row.get('findspot')) else None

        def _coord(x):
            if x is None or (isinstance(x, float) and math.isnan(x)):
                return None
            try:
                return float(x)
            except (ValueError, TypeError):
                return None

        records.append({
            'original_index': int(row['_orig_idx']),
            'attestation_id': row['attestation_id'],
            'source_id': row['source_id'],
            'praenomen': praenomen,
            'praenomen_norm': normalize_praenomen(praenomen),
            'nomen': nomen,
            'cognomen': cognomen,
            'nomen_prefix': prefix(nomen),
            'cognomen_prefix': prefix(cognomen),
            'lat': _coord(row.get('latitude')),
            'lon': _coord(row.get('longitude')),
            'findspot': str(findspot).strip() if findspot else None,
            'date_from_year': parse_year(row.get('date_from')),
            'date_to_year': parse_year(row.get('date_to')),
            'is_imperial': bool(row.get('is_imperial', False)),
            'fragmentary': bool(row.get('fragmentary', False)),
        })
    return records


def assign_confidence(members):
    """Return 'high' or 'low' for a cluster."""
    is_single_cog = all(m['nomen_prefix'] is None for m in members)
    if len(members) > 1 and is_single_cog:
        return 'low'

    post_212 = any(
        m['date_from_year'] is not None and m['date_from_year'] >= ANTONINIANA_YEAR
        for m in members
    )
    n_aurelius = sum(
        1 for m in members
        if m['nomen'] and m['nomen'].strip().lower() == 'aurelius'
    )
    if post_212 and n_aurelius > len(members) / 2:
        return 'low'

    return 'high'


def representative(members):
    """Pick the member with the most-complete name as the cluster representative."""
    def score(m):
        return (
            int(bool(m['praenomen'])) + int(bool(m['nomen'])) + int(bool(m['cognomen'])),
            len(m.get('cognomen') or ''),
            -len(m.get('attestation_id') or ''),  # ties broken by shorter ID (older EDCS records first)
        )
    return max(members, key=score)


def main():
    input_parquet = 'data/roman_names_africa_proconsularis.parquet'
    output_parquet = input_parquet
    output_csv = 'data/roman_names_africa_proconsularis.csv'
    output_clusters = 'data/clusters_summary.csv'

    print(f"Loading {input_parquet}...")
    df = pd.read_parquet(input_parquet)
    print(f"  {len(df)} attestations")

    # Track original positions for write-back
    df = df.reset_index(drop=True)
    df['_orig_idx'] = df.index

    # Initialize cluster columns (all excluded by default)
    df['cluster_id'] = pd.array([pd.NA] * len(df), dtype='Int64')
    df['cluster_size'] = pd.array([pd.NA] * len(df), dtype='Int64')
    df['cluster_confidence'] = 'excluded'

    # Universe: not deity, not place, not bare_epithet
    def _f(col):
        return df[col].fillna(False).astype(bool) if col in df.columns else False
    universe_mask = ~(_f('is_deity') | _f('is_place') | _f('is_bare_epithet'))
    universe = df[universe_mask].copy()
    print(f"  Universe (excl. deity/place/epithet): {len(universe)}")

    records = build_records(universe)

    has_full = [i for i, r in enumerate(records) if r['nomen_prefix'] and r['cognomen_prefix']]
    single_cog = [i for i, r in enumerate(records) if not r['nomen_prefix'] and r['cognomen_prefix']]
    no_key = [i for i, r in enumerate(records) if not r['cognomen_prefix']]
    print(f"    has nomen+cognomen: {len(has_full)}")
    print(f"    single cognomen:    {len(single_cog)}")
    print(f"    no usable key:      {len(no_key)}  (each becomes own singleton)")

    print("Clustering main pool (nomen+cognomen prefix)...")
    main_clusters = cluster_pool(
        records, has_full,
        key_fn=lambda r: (r['nomen_prefix'], r['cognomen_prefix']),
    )

    print("Clustering single-cognomen pool (findspot-strict, exact cognomen match)...")
    # Exact cognomen match (not prefix) — the 6-char prefix conflates Victor /
    # Victorinus / Victorina etc. (all share "victor"). In the main pool the
    # nomen discriminates between derivatives, but here cognomen is the only
    # signal so we tighten to exact match. Case-variant losses (Victor / Victori)
    # are an acceptable tradeoff — single-name clusters are already low-confidence.
    cog_clusters = cluster_pool(
        records, single_cog,
        key_fn=lambda r: (str(r['cognomen']).strip().lower(),) if r['cognomen'] else None,
        require_findspot_exact=True,
    )

    no_key_clusters = [[i] for i in no_key]
    all_clusters = main_clusters + cog_clusters + no_key_clusters
    print(f"Formed {len(all_clusters)} clusters covering {sum(len(c) for c in all_clusters)} records")

    # Write back per-attestation cluster columns + build cluster summary
    cluster_ids = [pd.NA] * len(df)
    cluster_sizes = [pd.NA] * len(df)
    cluster_confs = ['excluded'] * len(df)

    summary_rows = []
    for cid, member_indices in enumerate(all_clusters):
        members = [records[i] for i in member_indices]
        size = len(members)
        confidence = assign_confidence(members)
        rep = representative(members)
        rep_name = ' '.join(filter(None, [rep['praenomen'], rep['nomen'], rep['cognomen']]))

        for m in members:
            oi = m['original_index']
            cluster_ids[oi] = cid
            cluster_sizes[oi] = size
            cluster_confs[oi] = confidence

        findspots = sorted({m['findspot'] for m in members if m['findspot']})
        date_froms = [m['date_from_year'] for m in members if m['date_from_year'] is not None]
        date_tos = [m['date_to_year'] for m in members if m['date_to_year'] is not None]
        if date_froms or date_tos:
            df_min = min(date_froms) if date_froms else ''
            dt_max = max(date_tos) if date_tos else ''
            date_str = f'{df_min}..{dt_max}'
        else:
            date_str = ''

        summary_rows.append({
            'cluster_id': cid,
            'cluster_size': size,
            'representative_name': rep_name,
            'praenomen': rep['praenomen'],
            'nomen': rep['nomen'],
            'cognomen': rep['cognomen'],
            'is_imperial': any(m['is_imperial'] for m in members),
            'has_fragmentary': any(m['fragmentary'] for m in members),
            'cluster_confidence': confidence,
            'n_findspots': len(findspots),
            'findspots': '; '.join(findspots[:5]) + (' …' if len(findspots) > 5 else ''),
            'date_range': date_str,
            'member_attestation_ids': '; '.join(m['attestation_id'] for m in members),
        })

    df['cluster_id'] = pd.array(cluster_ids, dtype='Int64')
    df['cluster_size'] = pd.array(cluster_sizes, dtype='Int64')
    df['cluster_confidence'] = cluster_confs
    df = df.drop(columns=['_orig_idx'])

    # Save outputs
    print(f"Writing {output_clusters}...")
    summary_df = pd.DataFrame(summary_rows).sort_values(
        ['cluster_size', 'cluster_id'], ascending=[False, True],
    )
    summary_df.to_csv(output_clusters, index=False)

    print(f"Writing {output_parquet}...")
    df.to_parquet(output_parquet, compression='snappy', index=False)

    print(f"Writing {output_csv}...")
    df.to_csv(output_csv, index=False)

    # Stats
    total_clusters = len(all_clusters)
    singletons = sum(1 for c in all_clusters if len(c) == 1)
    multi = total_clusters - singletons
    in_multi = sum(len(c) for c in all_clusters if len(c) > 1)
    in_universe = sum(len(c) for c in all_clusters)
    largest = max(len(c) for c in all_clusters)
    mean_size = in_universe / total_clusters

    print("\n" + "=" * 60)
    print("CLUSTERING SUMMARY")
    print("=" * 60)
    print(f"Total attestations:                  {len(df)}")
    print(f"  in universe:                       {in_universe}")
    print(f"  excluded (deity/place/epithet):    {len(df) - in_universe}")
    print()
    print(f"Total clusters:                      {total_clusters}")
    print(f"  singletons (size 1):               {singletons}")
    print(f"  multi-member (size >=2):           {multi}")
    print(f"  largest cluster size:              {largest}")
    print(f"  mean cluster size:                 {mean_size:.2f}")
    print(f"  attestations in multi-clusters:    {in_multi} ({in_multi / in_universe * 100:.1f}%)")
    print()
    print("Confidence distribution:")
    for k, v in df['cluster_confidence'].value_counts().items():
        print(f"  {k}: {v}")
    print()
    print("Top 10 largest clusters:")
    for _, r in summary_df.head(10).iterrows():
        flags = []
        if r['is_imperial']: flags.append('IMP')
        if r['has_fragmentary']: flags.append('frag')
        flag_str = f"  [{'/'.join(flags)}]" if flags else ''
        print(f"  cluster_id={r['cluster_id']:>5}  size={r['cluster_size']:>3}  "
              f"conf={r['cluster_confidence']:<5}  {r['representative_name']!r}{flag_str}")
    print()
    print(f"Outputs: {output_parquet}, {output_csv}, {output_clusters}")


if __name__ == "__main__":
    main()
