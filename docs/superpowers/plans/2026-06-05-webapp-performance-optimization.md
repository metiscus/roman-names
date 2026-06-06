# Webapp Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the performance, memory usage, and responsiveness of the Roman Name Attestations webapp by moving filtering to the backend, shrinking tile data payloads, implementing client-side viewport-based cache eviction, and optimizing map rendering with Leaflet.

**Architecture:** We will update the server's tile query APIs to accept and execute filters in Python on SQL-retrieved bounding boxes, sending back a compact summary of inscription/person properties. The frontend will render using Leaflet's HTML5 canvas engine, perform batched marker injections, evict off-screen cache items to keep memory flat, and request tiles dynamically with serialized filter query parameters.

**Tech Stack:** FastAPI, SQLite, Python 3, Leaflet.js, Leaflet.markercluster.

---

### Task 1: Update DB helper functions and post-query filtering

**Files:**
- Modify: `server/db.py:91-165`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write helper for post-query Python filters and minification**
Add the `_matches_filters` and updated individual tile processing to `server/db.py`.

```python
def _matches_filters(
    persons: list,
    gender: str | None,
    confidence: str | None,
    hide_deity: bool,
    hide_imperial: bool,
    search: str | None
) -> bool:
    if search:
        search_lower = search.lower()
        hit = False
        for p in persons:
            full = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen"), p.get("raw_name")])).lower()
            if search_lower in full:
                hit = True
                break
        if not hit:
            return False

    if gender or confidence or hide_deity or hide_imperial:
        relevant = []
        for p in persons:
            if hide_deity and p.get("is_deity"):
                continue
            if hide_imperial and p.get("is_imperial"):
                continue
            if gender and p.get("gender") != gender:
                continue
            if confidence and p.get("cluster_confidence") != confidence:
                continue
            relevant.append(p)
        if len(persons) > 0 and len(relevant) == 0:
            return False
    return True
```

Modify `get_markers_for_tile` to accept the filter parameters and apply them, returning the optimized minified payload:

```python
def get_markers_for_tile(
    z: int, x: int, y: int,
    gender: str | None = None,
    confidence: str | None = None,
    hide_deity: bool = False,
    hide_imperial: bool = False,
    has_translation: bool = False,
    search: str | None = None
) -> dict:
    with _conn() as conn:
        if z < ZOOM_PROVINCE:
            rows = conn.execute("SELECT province, lat, lon, count FROM provinces").fetchall()
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "province_cluster",
                        "province": r["province"],
                        "count": r["count"],
                    },
                }
                for r in rows
            ]

        elif z < ZOOM_INDIVIDUAL:
            ax_min, ax_max, ay_min, ay_max = _aggregate_tile_range(z, x, y)
            rows = conn.execute(
                """
                SELECT tile_x, tile_y, lat, lon, count
                FROM tile_aggregates
                WHERE zoom = ? AND tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
                """,
                (AGGREGATE_ZOOM, ax_min, ax_max, ay_min, ay_max),
            ).fetchall()
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "area_cluster",
                        "count": r["count"],
                        "tile_z": AGGREGATE_ZOOM,
                        "tile_x": r["tile_x"],
                        "tile_y": r["tile_y"],
                    },
                }
                for r in rows
            ]

        else:
            x_min, x_max, y_min, y_max = _tile_range(z, x, y)
            query = """
                SELECT edcs_id, lat, lon, findspot, date_from, date_to,
                       persons, overrides,
                       (translation IS NOT NULL AND translation != '') AS has_translation
                FROM inscriptions
                WHERE tile_x BETWEEN ? AND ? AND tile_y BETWEEN ? AND ?
            """
            params = [x_min, x_max, y_min, y_max]
            if has_translation:
                query += " AND (translation IS NOT NULL AND translation != '')"

            rows = conn.execute(query, params).fetchall()
            features = []
            for r in rows:
                parsed_persons = _parse_persons(r["overrides"], r["persons"])
                if not _matches_filters(
                    parsed_persons,
                    gender=gender,
                    confidence=confidence,
                    hide_deity=hide_deity,
                    hide_imperial=hide_imperial,
                    search=search
                ):
                    continue

                genders = list(set(p.get("gender") for p in parsed_persons if p.get("gender")))
                person_names = []
                for p in parsed_persons[:2]:
                    name = " ".join(filter(None, [p.get("praenomen"), p.get("nomen"), p.get("cognomen")]))
                    display_name = name if name else (p.get("raw_name") or "(unnamed)")
                    person_names.append(display_name)

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                    "properties": {
                        "type": "inscription",
                        "edcs_id": r["edcs_id"],
                        "findspot": r["findspot"],
                        "date_from": r["date_from"],
                        "date_to": r["date_to"],
                        "edcs_url": f"https://edcs.hist.uzh.ch/en/document?edcs-id={r['edcs_id']}",
                        "genders": genders,
                        "person_names": person_names,
                        "person_count": len(parsed_persons),
                        "has_translation": bool(r["has_translation"]),
                    },
                })

    return {"type": "FeatureCollection", "features": features}
```

- [ ] **Step 2: Update database unit tests**
Modify existing tests in `tests/test_db.py` to match the new optimized payload structure. Specifically, update any assertions expecting `"persons"` array to expect `"person_names"`, `"person_count"`, and `"genders"`. Add tests for filtering in `get_markers_for_tile`.

- [ ] **Step 3: Run pytest to verify database changes**
Run: `pytest tests/test_db.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit DB changes**
```bash
git add server/db.py tests/test_db.py
git commit -m "perf: update db.py to support server-side filtering and payload minification"
```

---

### Task 2: Update FastAPI tiles router and API tests

**Files:**
- Modify: `server/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Accept optional query parameters in main router**
Modify `/api/tiles/{z}/{x}/{y}` in `server/main.py` to receive filter options and pass them to the database query function. Configure Cache-Control headers to be `no-store` if any filters are active.

```python
@app.get("/api/tiles/{z}/{x}/{y}")
def tiles(
    z: int, x: int, y: int,
    gender: str | None = None,
    confidence: str | None = None,
    hide_deity: bool = False,
    hide_imperial: bool = False,
    has_translation: bool = False,
    search: str | None = None
):
    data = db.get_markers_for_tile(
        z, x, y,
        gender=gender,
        confidence=confidence,
        hide_deity=hide_deity,
        hide_imperial=hide_imperial,
        has_translation=has_translation,
        search=search
    )
    response = JSONResponse(content=data)
    # Cache tiles publicly unless they have active query filters
    if gender or confidence or hide_deity or hide_imperial or has_translation or search:
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response
```

- [ ] **Step 2: Update API route unit tests**
Modify tests in `tests/test_api.py` to accommodate the minified features properties, and add a test case verifying the filter query parameters correctly return filtered results.

- [ ] **Step 3: Run pytest to verify API changes**
Run: `pytest tests/test_api.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit API router changes**
```bash
git add server/main.py tests/test_api.py
git commit -m "perf: update API tiles endpoint to support search and filter parameters"
```

---

### Task 3: Enable Canvas Rendering & Batched Marker Additions

**Files:**
- Modify: `webapp/index.html`

- [ ] **Step 1: Enable Leaflet Canvas Rendering**
In `webapp/index.html` around `initMap`, add `preferCanvas: true` to the Leaflet map constructor:
```javascript
  map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([41.9, 12.5], 5);
```

- [ ] **Step 2: Implement Batched Marker Additions**
In `webapp/index.html`, refactor `fetchTile()` to collect newly created markers in a temporary array and add them as a single batch using `clusterLayer.addLayers(markersArray)` instead of adding them individually.

Modify `fetchTile`:
```javascript
async function fetchTile(z, x, y, key, tier, queryString = '') {
  try {
    const resp = await fetch(`/api/tiles/${z}/${x}/${y}${queryString}`);
    if (!resp.ok) { loadedTiles.delete(key); return; }
    const data = await resp.json();
    const features = data.features || [];

    if (tier === 'province') {
      provinceFeatures = features;
    } else if (tier === 'aggregate') {
      for (const feat of features) {
        const p = feat.properties;
        const cellKey = `${p.tile_x}:${p.tile_y}`;
        if (!loadedFeatures.has(cellKey)) {
          p._lat = feat.geometry.coordinates[1];
          p._lon = feat.geometry.coordinates[0];
          loadedFeatures.set(cellKey, p);
        }
      }
    } else {
      const markersToAdd = [];
      for (const feat of features) {
        if (!loadedFeatures.has(feat.properties.edcs_id)) {
          feat.properties._lat = feat.geometry.coordinates[1];
          feat.properties._lon = feat.geometry.coordinates[0];
          loadedFeatures.set(feat.properties.edcs_id, feat.properties);

          const color = markerColor(feat.properties.genders);
          const m = L.circleMarker([feat.properties._lat, feat.properties._lon], {
            radius: 6, fillColor: color, color: '#fff', weight: 1, fillOpacity: 0.85,
          });
          m._featureProps = feat.properties;
          m.on('click', e => {
            L.DomEvent.stopPropagation(e);
            selectInscription(feat.properties.edcs_id);
          });
          renderedMarkersMap.set(feat.properties.edcs_id, m);
          markersToAdd.push(m);
        }
      }
      if (markersToAdd.length) {
        clusterLayer.addLayers(markersToAdd);
      }
    }
    renderMarkers();
  } catch (_) {
    loadedTiles.delete(key);
  }
}
```

---

### Task 4: Viewport-Based Client Cache Eviction

**Files:**
- Modify: `webapp/index.html`

- [ ] **Step 1: Track Tile Features & Rendered Markers**
In the state declarations, add mapping maps for eviction:
```javascript
const loadedTiles    = new Set();   // 'z/x/y' or 'province-view'
const loadedFeatures = new Map();   // edcs_id → feature properties
const tileFeaturesMap = new Map();  // 'z/x/y' → Set of edcs_id
const renderedMarkersMap = new Map(); // edcs_id → marker layer reference
```

- [ ] **Step 2: Implement Eviction Logic in `loadView`**
In `webapp/index.html`, modify `loadView()` to calculate visible tiles with a 1-tile buffer, then identify and clean up any off-screen tiles:

```javascript
  // Calculate visible tiles at the current zoom level with a 1-tile buffer
  const visible = new Set();
  const requestZoom = tier === 'aggregate' ? AGGREGATE_ZOOM : Math.min(zoom, MAX_TILE_ZOOM);
  if (tier !== 'province') {
    const activeTiles = getVisibleTiles(requestZoom);
    // Add active tiles and their 1-tile neighbors to the keep list
    for (const t of activeTiles) {
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          visible.add(`${t.z}/${t.x + dx}/${t.y + dy}`);
        }
      }
    }
  }

  // Evict tiles that are loaded but no longer visible
  for (const loadedKey of Array.from(loadedTiles)) {
    if (loadedKey === 'province-view') continue;
    if (!visible.has(loadedKey)) {
      const featureIds = tileFeaturesMap.get(loadedKey);
      if (featureIds) {
        for (const id of featureIds) {
          const marker = renderedMarkersMap.get(id);
          if (marker) {
            clusterLayer.removeLayer(marker);
            renderedMarkersMap.delete(id);
          }
          loadedFeatures.delete(id);
        }
        tileFeaturesMap.delete(loadedKey);
      }
      loadedTiles.delete(loadedKey);
    }
  }
```

---

### Task 5: Connect Filters to Backend API and Remove Client Filters

**Files:**
- Modify: `webapp/index.html`

- [ ] **Step 1: Serialize Active Filters as Query String**
Add a utility function to format the filters for the URL query:
```javascript
function getQueryString() {
  const f = getFilters();
  const params = new URLSearchParams();
  if (f.gender) params.set('gender', f.gender);
  if (f.confidence) params.set('confidence', f.confidence);
  if (f.hideDeity) params.set('hide_deity', 'true');
  if (f.hideImperial) params.set('hide_imperial', 'true');
  if (f.hasTranslation) params.set('has_translation', 'true');
  if (f.search) params.set('search', f.search);
  const s = params.toString();
  return s ? '?' + s : '';
}
```

- [ ] **Step 2: Update Filter / Search Change Listeners**
When a filter changes, invalidate the entire cache, clear all active markers, and invoke `loadView()`:
```javascript
function handleFilterChange() {
  loadedTiles.clear();
  loadedFeatures.clear();
  tileFeaturesMap.clear();
  renderedMarkersMap.clear();
  clusterLayer.clearLayers();
  provinceLayer.clearLayers();
  aggregateLayer.clearLayers();
  loadView();
}
```
Update listeners in `initMap`:
```javascript
  ['f-gender','f-confidence','f-hide-deity','f-hide-imperial','f-has-translation'].forEach(id => {
    document.getElementById(id).addEventListener('change', handleFilterChange);
  });
  document.getElementById('search-input').addEventListener('input', handleFilterChange);
```

- [ ] **Step 3: Remove Redundant `featureMatchesFilters`**
Delete the `featureMatchesFilters` function entirely and remove any references to it from the frontend codebase. Since the server does the filtering, all features returned are pre-matched.

- [ ] **Step 4: Commit webapp updates**
```bash
git add webapp/index.html
git commit -m "perf: enable canvas, batch marker injection, viewport cache eviction, and query parameter filtering"
```
