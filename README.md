# Sentinel-2 Multispectral Analyzer 

WebGIS prototype for semi-automated multitemporal and multispectral analysis
of Sentinel-2 imagery.

Sentinel-2 Multispectral Analyzer is an open-source WebGIS platform developed by the University of Messina within the EO4DES – Earth Observation for Desertification project.

The platform integrates Google Earth Engine, Python/Flask, and Leaflet to support semi-automated multispectral and multitemporal analysis of Sentinel-2 Level-2A imagery. Users can interactively define an Area of Interest, search and select satellite acquisitions, compute spectral indices such as NDVI and NDRE, and compare user-selected spectral bands through descriptive statistics, scatterplots, histograms, and interactive map visualization.

The platform is designed as an extensible framework for Earth Observation data analysis, with future developments including additional processing modules and machine-learning approaches.

Developed by: University of Messina
Project: EO4DES – Earth Observation for Desertification
Link: https://eo4des.github.io/project/


## V1 scientific logic

The demo has two independent analysis branches.

### A. Spectral indices

The user can request:

- NDVI at T1 and T2, plus ΔNDVI = T2 − T1.
- NDRE at T1 and T2, plus ΔNDRE = T2 − T1.

The required bands are selected automatically:

- NDVI: B8 and B4.
- NDRE: B8A and B5.

The bands manually selected in the interface do not affect NDVI/NDRE.

### B. Selected-band analysis

The user manually selects two Sentinel-2 bands (maximum two). These two bands
are used only for:

- T1/T2 scatterplots;
- T1/T2 histograms;
- descriptive sample statistics;
- Pearson correlation coefficient for the scatterplots.

For a pair such as B3 and B11, the backend samples B3/B11 at T1 and T2 using
a common analysis scale. Surface-reflectance DN values are converted using the
Sentinel-2 L2A scale factor 0.0001 before the graphs are generated.

## Important V1 change: acquisition dates instead of single tiles

The search interface now lists unique acquisition dates. If an AOI intersects
multiple MGRS tiles, the analysis backend mosaics the valid Sentinel-2 granules
for the selected date before processing.

This avoids comparing two unrelated individual granules when a large AOI
crosses tile boundaries.

## Cloud handling

The first search filter uses `CLOUDY_PIXEL_PERCENTAGE`.

During analysis, a simple Sentinel-2 Scene Classification Layer (SCL) mask
removes:

- no-data pixels;
- saturated/defective pixels;
- cloud shadows;
- medium/high probability clouds;
- cirrus;
- snow/ice.

## Running the demo

Activate the environment:

```bash
conda activate sentinel_webgis
```

Check the project variable:

```bat
echo %EARTH_ENGINE_PROJECT%
```

Then:

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Main endpoints

### POST `/api/acquisitions/search`

Returns unique Sentinel-2 acquisition dates intersecting the AOI.

### POST `/api/analysis/run`

Example:

```json
{
  "aoi": {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
  "t1": "2025-01-03",
  "t2": "2025-01-08",
  "bands": ["B4", "B8"],
  "analyses": ["ndvi", "ndre", "scatterplot", "histogram"],
  "cloud_cover": 10
}
```

The response can contain:

- `spectral_indices.ndvi`
- `spectral_indices.ndre`
- `band_analysis.scatterplot`
- `band_analysis.histogram`

NDVI/NDRE tile URLs are also returned and displayed as Leaflet overlays.


## V1.2 methodological updates

### Acquisition timestamp

Acquisitions are now grouped by acquisition timestamp and shown as:

```text
YYYY-MM-DD · HH:MM:SS UTC | clouds ... | N tiles | T33...
```

Multiple MGRS tiles acquired in the same pass are mosaicked automatically.

### Common valid-data mask

Every multitemporal comparison is restricted to pixels that are valid in both
T1 and T2. For selected-band analysis, the same paired geographic sample
locations are used for both timestamps.

The interface reports the common valid area and its percentage of the AOI.

### Different native band resolutions

When two manually selected bands have different native resolutions, the
higher-resolution band is aggregated to the coarser grid using a mean
(`ee.Reducer.mean()` through `reduceResolution`).

Examples:

```text
B4 10 m + B11 20 m -> analysis at 20 m
B8 10 m + B8A 20 m -> analysis at 20 m
B5 20 m + B11 20 m -> analysis at 20 m
```

The coarser selected-band resolution defines the analysis scale. A common grid
is used for both T1 and T2 before paired sampling.
