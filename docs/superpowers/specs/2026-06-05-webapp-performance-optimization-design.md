# Design Document: Webapp Performance Optimization

## Goal
Improve the performance, memory usage, and responsiveness of the Roman Name Attestations webapp by moving filtering to the backend, shrinking tile data payloads, implementing client-side viewport-based cache eviction, and optimizing map rendering with Leaflet.

## Constraints & Principles
- **No Database Schema Changes:** All data optimizations must work with the existing SQLite schema.
- **Portability:** Avoid specialized SQLite functions that may not be present in standard Python `sqlite3` environments (such as JSON parsing functions). Post-query filtering in Python is acceptable and robust for bounding-box limited tile queries.
- **Backwards Compatibility:** Maintain unchanged deep links, detail popups, and the existing public URL structure. Detail fetching via `/api/inscription/{edcs_id}` remains the source of truth for full record views.

---

## Part 1: Server-side Filtering and Minified Payload

### 1. Main FastAPI Route Updates (`server/main.py`)
Modify the `/api/tiles/{z}/{x}/{y}` endpoint to accept optional query parameters for filtering:
- `gender: str` (optional)
- `confidence: str` (optional)
- `hide_deity: bool` (default: `False`)
- `hide_imperial: bool` (default: `False`)
- `has_translation: bool` (default: `False`)
- `search: str` (optional)

Example endpoint definition:
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
    response.headers["Cache-Control"] = "public, max-age=86400" if not (gender or confidence or hide_deity or hide_imperial or has_translation or search) else "no-store"
    return response
```

### 2. SQLite Database & Python Filter Logic (`server/db.py`)
We update `get_markers_for_tile` to apply filters for the individual tier (`z >= ZOOM_INDIVIDUAL`):
- Filter by `has_translation` directly in the SQL statement: `AND (translation IS NOT NULL AND translation != '')`.
- Build a Python post-query filtering function `_matches_filters(persons_list, ...)` equivalent to the current frontend's `featureMatchesFilters`.
- Minify the returned properties to significantly reduce network transfer. Instead of returning the full, nested, multi-kilobyte `persons` array per inscription, we construct a compact summary representation:
  - `genders`: A list of unique genders present in the inscription (for styling marker colors).
  - `person_names`: A list of the first two person names (pre-computed and formatted) for immediate previewing in the inspection panel.
  - `person_count`: Total number of persons associated with this inscription.

Optimized individual-tier payload structure:
```json
{
  "type": "Feature",
  "geometry": {
    "type": "Point",
    "coordinates": [lon, lat]
  },
  "properties": {
    "type": "inscription",
    "edcs_id": "HD012345",
    "findspot": "Roma",
    "date_from": 100,
    "date_to": 200,
    "edcs_url": "https://edcs.hist.uzh.ch/en/document?edcs-id=HD012345",
    "genders": ["male"],
    "person_names": ["Marcus Aurelius"],
    "person_count": 1,
    "has_translation": true
  }
}
```

---

## Part 2: Frontend Client-Side Optimizations

### 1. Leaflet Canvas Rendering (`webapp/index.html`)
Initialize the Leaflet map with `preferCanvas: true` to draw markers directly onto an HTML5 Canvas, bypassing DOM node creation for thousands of circles:
```javascript
map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([41.9, 12.5], 5);
```

### 2. Batched Marker Additions
Refactor `fetchTile` to collect all new markers in a local array and insert them via `clusterLayer.addLayers(newMarkers)` rather than single `addLayer()` calls. This prevents the marker cluster layout algorithm from running on every individual marker addition.

### 3. Client Viewport Cache Eviction
Implement memory eviction inside `loadView()` to prevent infinite memory accumulation:
- Keep a key-value map `tileFeaturesMap = Map<tileKey, Set<edcs_id>>` which maps each loaded tile key (e.g., `"10/512/384"`) to the IDs of its loaded features.
- Keep a map `renderedMarkersMap = Map<edcs_id, marker>` of all currently rendered markers.
- In `loadView()`, calculate the set of visible tiles at the current request zoom level (plus a 1-tile margin buffer in each direction).
- Compare this set against `loadedTiles`. For any tile that is currently loaded but no longer in the expanded visible bounding box:
  - Retrieve its set of `edcs_ids`.
  - For each `edcs_id`, check if it is still required by any other visible/buffered tile (some inscriptions may overlap tile boundaries). If not:
    - Retrieve the marker from `renderedMarkersMap`.
    - Remove the marker from `clusterLayer`.
    - Delete the entry from `loadedFeatures` and `renderedMarkersMap`.
  - Delete the tile from `loadedTiles` and `tileFeaturesMap`.

### 4. Filter Invalidation & Query Appending
- When any filter or search input changes:
  - Clear `loadedTiles`, `loadedFeatures`, `tileFeaturesMap`, `renderedMarkersMap`.
  - Clear `clusterLayer`, `provinceLayer`, `aggregateLayer`.
  - Serialize the current filters into a query string (e.g., `?gender=female&has_translation=true`).
  - Request tiles with these parameters appended: `fetchTile(z, x, y, key, tier, queryString)`.

---

## Part 3: Verification & Impact

### 1. Memory Verification
Pan the map around dense areas (like central Italy and Tunisia) repeatedly. Ensure that the browser's memory footprint remains flat and stable after the cache eviction buffer threshold is reached, instead of increasing monotonically.

### 2. Network Payload Size Verification
Verify in the browser Network tab that:
- Individual-tier tile responses are drastically smaller (~75% reduction in size due to stripping full person records).
- Filter changes trigger fresh requests containing appropriate query parameters.
- Empty filters on cached/zoom-out views leverage standard HTTP cache controls.
