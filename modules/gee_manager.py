from collections import defaultdict
from datetime import datetime, timezone
import math

import ee
import numpy as np

from config.settings import EARTH_ENGINE_PROJECT

COLLECTION_ID = "COPERNICUS/S2_SR_HARMONIZED"

BAND_INFO = {
    "B2":  {"name": "Blue",       "resolution": 10},
    "B3":  {"name": "Green",      "resolution": 10},
    "B4":  {"name": "Red",        "resolution": 10},
    "B5":  {"name": "Red Edge 1", "resolution": 20},
    "B6":  {"name": "Red Edge 2", "resolution": 20},
    "B7":  {"name": "Red Edge 3", "resolution": 20},
    "B8":  {"name": "NIR",        "resolution": 10},
    "B8A": {"name": "Narrow NIR", "resolution": 20},
    "B11": {"name": "SWIR 1",     "resolution": 20},
    "B12": {"name": "SWIR 2",     "resolution": 20},
}

INDEX_DEFINITIONS = {
    "ndvi": {
        "label": "NDVI",
        "bands": ["B8", "B4"],
        "scale": 10,
        "vis": {
            "min": -1,
            "max": 1,
            "palette": ["7f3b08", "f6e8c3", "c7eae5", "01665e"],
        },
    },
    "ndre": {
        "label": "NDRE",
        "bands": ["B8A", "B5"],
        "scale": 20,
        "vis": {
            "min": -1,
            "max": 1,
            "palette": ["8c510a", "f6e8c3", "c7eae5", "003c30"],
        },
    },
}

MAX_SAMPLE_PIXELS = 3000
HISTOGRAM_BINS = 40


def initialize_earth_engine():
    if not EARTH_ENGINE_PROJECT:
        raise RuntimeError(
            "EARTH_ENGINE_PROJECT is not configured. "
            "Set the environment variable to your Google Cloud / Earth Engine project ID."
        )
    ee.Initialize(project=EARTH_ENGINE_PROJECT)


def get_gee_status():
    try:
        initialize_earth_engine()
        return {"initialized": True, "project": EARTH_ENGINE_PROJECT}
    except Exception as exc:
        return {
            "initialized": False,
            "project": EARTH_ENGINE_PROJECT or None,
            "message": str(exc),
        }


def _geojson_to_geometry(aoi_geojson):
    if aoi_geojson.get("type") == "Feature":
        geometry = aoi_geojson["geometry"]
    else:
        geometry = aoi_geojson

    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("The AOI must be a Polygon or MultiPolygon.")

    return ee.Geometry(geometry)


def _cloud_mask(image):
    """
    Simple Sentinel-2 L2A SCL mask for the V1 demo.
    Removes no-data, saturated/defective pixels, cloud shadow,
    medium/high-probability clouds, cirrus and snow/ice.
    """
    scl = image.select("SCL")
    valid = (
        scl.neq(0)
        .And(scl.neq(1))
        .And(scl.neq(3))
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )
    return image.updateMask(valid)


def _timestamp_key(millis):
    dt = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp_display(millis):
    dt = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return {
        "date": dt.strftime("%Y-%m-%d"),
        "time_utc": dt.strftime("%H:%M:%S"),
        "datetime_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def search_sentinel2_acquisitions(aoi_geojson, start_date, end_date, cloud_cover=10.0):
    """
    Groups Sentinel-2 granules by acquisition timestamp rather than only by date.
    If the AOI intersects multiple MGRS tiles acquired at the same pass/time,
    they are presented as one acquisition and mosaicked during processing.
    """
    initialize_earth_engine()
    aoi = _geojson_to_geometry(aoi_geojson)

    collection = (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(aoi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_cover))
        .sort("system:time_start")
    )

    def image_to_feature(image):
        image = ee.Image(image)
        return ee.Feature(
            None,
            {
                "id": image.id(),
                "time_start": image.get("system:time_start"),
                "cloud_cover": image.get("CLOUDY_PIXEL_PERCENTAGE"),
                "product_id": image.get("PRODUCT_ID"),
                "mgrs_tile": image.get("MGRS_TILE"),
            },
        )

    info = collection.map(image_to_feature).getInfo()
    grouped = defaultdict(list)

    for feature in info.get("features", []):
        props = feature.get("properties", {})
        millis = props.get("time_start")
        if millis is None:
            continue
        grouped[_timestamp_key(millis)].append({
            "id": props.get("id"),
            "time_start": millis,
            "cloud_cover": props.get("cloud_cover"),
            "product_id": props.get("product_id"),
            "mgrs_tile": props.get("mgrs_tile"),
        })

    results = []
    for key in sorted(grouped):
        granules = grouped[key]
        display = _timestamp_display(granules[0]["time_start"])

        clouds = [
            float(g["cloud_cover"])
            for g in granules
            if g.get("cloud_cover") is not None
        ]
        tiles = sorted({
            g["mgrs_tile"] for g in granules if g.get("mgrs_tile")
        })

        results.append({
            "key": key,
            "date": display["date"],
            "time_utc": display["time_utc"],
            "datetime_utc": display["datetime_utc"],
            "granule_count": len(granules),
            "cloud_cover_mean": round(float(np.mean(clouds)), 2) if clouds else None,
            "cloud_cover_max": round(float(np.max(clouds)), 2) if clouds else None,
            "mgrs_tiles": tiles,
        })

    return results


def _collection_for_timestamp(timestamp_key, aoi, cloud_cover=100.0):
    """
    Builds a narrow time window around the selected acquisition timestamp.
    A 2-minute window safely groups granules belonging to the same acquisition
    while avoiding unrelated passes.
    """
    center = ee.Date(timestamp_key)
    start = center.advance(-60, "second")
    end = center.advance(60, "second")

    return (
        ee.ImageCollection(COLLECTION_ID)
        .filterBounds(aoi)
        .filterDate(start, end)
        .filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_cover))
        .map(_cloud_mask)
    )


def _mosaic_for_timestamp(timestamp_key, aoi, cloud_cover=100.0):
    collection = _collection_for_timestamp(timestamp_key, aoi, cloud_cover)
    count = collection.size().getInfo()
    if count == 0:
        raise ValueError(f"No Sentinel-2 images found for acquisition {timestamp_key}.")
    return collection.mosaic().clip(aoi)


def _index_image(image, index_name):
    if index_name == "ndvi":
        return image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    if index_name == "ndre":
        return image.normalizedDifference(["B8A", "B5"]).rename("NDRE")
    raise ValueError(f"Unsupported index: {index_name}")


def _safe_number(value):
    if value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _image_statistics(single_band_image, band_name, aoi, scale):
    reducer = (
        ee.Reducer.mean()
        .combine(reducer2=ee.Reducer.median(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.minMax(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.percentile([5, 95]), sharedInputs=True)
    )

    raw = single_band_image.reduceRegion(
        reducer=reducer,
        geometry=aoi,
        scale=scale,
        bestEffort=True,
        maxPixels=1e9,
        tileScale=4,
    ).getInfo()

    return {
        "mean": _safe_number(raw.get(f"{band_name}_mean")),
        "median": _safe_number(raw.get(f"{band_name}_median")),
        "std": _safe_number(raw.get(f"{band_name}_stdDev")),
        "min": _safe_number(raw.get(f"{band_name}_min")),
        "max": _safe_number(raw.get(f"{band_name}_max")),
        "p05": _safe_number(raw.get(f"{band_name}_p5")),
        "p95": _safe_number(raw.get(f"{band_name}_p95")),
    }


def _tile_url(image, vis_params):
    map_id = image.getMapId(vis_params)
    return map_id["tile_fetcher"].url_format


def _common_valid_mask(image_t1, image_t2, bands):
    """
    Returns a mask that is valid only where every requested band is valid
    in both acquisitions.
    """
    mask_t1 = image_t1.select(bands).mask().reduce(ee.Reducer.min())
    mask_t2 = image_t2.select(bands).mask().reduce(ee.Reducer.min())
    return mask_t1.And(mask_t2)


def _mask_pair_to_common_valid(image_t1, image_t2, bands):
    common = _common_valid_mask(image_t1, image_t2, bands)
    return image_t1.updateMask(common), image_t2.updateMask(common), common


def _common_coverage_metrics(common_mask, aoi, scale):
    """
    Computes AOI area and common valid area in km².
    """
    pixel_area = ee.Image.pixelArea()
    common_area_img = pixel_area.updateMask(common_mask)

    common_m2 = common_area_img.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=aoi,
        scale=scale,
        bestEffort=True,
        maxPixels=1e9,
        tileScale=4,
    ).get("area")

    aoi_m2 = aoi.area(maxError=1)

    common_m2 = ee.Number(common_m2)
    aoi_m2 = ee.Number(aoi_m2)

    coverage = ee.Algorithms.If(
        aoi_m2.gt(0),
        common_m2.divide(aoi_m2).multiply(100),
        0
    )

    values = ee.Dictionary({
        "aoi_km2": aoi_m2.divide(1e6),
        "common_valid_km2": common_m2.divide(1e6),
        "coverage_percent": coverage,
    }).getInfo()

    return {
        "aoi_km2": _safe_number(values.get("aoi_km2")),
        "common_valid_km2": _safe_number(values.get("common_valid_km2")),
        "coverage_percent": _safe_number(values.get("coverage_percent")),
    }


def _index_result(index_name, image_t1, image_t2, aoi):
    definition = INDEX_DEFINITIONS[index_name]
    label = definition["label"]
    scale = definition["scale"]
    bands = definition["bands"]

    common = _common_valid_mask(image_t1, image_t2, bands)

    idx_t1 = _index_image(image_t1, index_name).updateMask(common)
    idx_t2 = _index_image(image_t2, index_name).updateMask(common)
    delta = idx_t2.subtract(idx_t1).rename(f"DELTA_{label}").updateMask(common)

    delta_vis = {
        "min": -0.5,
        "max": 0.5,
        "palette": ["b2182b", "f7f7f7", "2166ac"],
    }

    return {
        "label": label,
        "formula_bands": bands,
        "common_valid_area": _common_coverage_metrics(common, aoi, scale),
        "t1": {
            "statistics": _image_statistics(idx_t1, label, aoi, scale),
            "tile_url": _tile_url(idx_t1, definition["vis"]),
        },
        "t2": {
            "statistics": _image_statistics(idx_t2, label, aoi, scale),
            "tile_url": _tile_url(idx_t2, definition["vis"]),
        },
        "delta_t2_minus_t1": {
            "statistics": _image_statistics(
                delta, f"DELTA_{label}", aoi, scale
            ),
            "tile_url": _tile_url(delta, delta_vis),
        },
    }


def _analysis_resolution(selected_bands):
    return max(BAND_INFO[b]["resolution"] for b in selected_bands)


def _reference_projection(image, selected_bands):
    """
    Uses the first selected band already at the coarsest native resolution as
    reference grid. If both are equal resolution, Band 1 is the reference.
    """
    target = _analysis_resolution(selected_bands)
    for band in selected_bands:
        if BAND_INFO[band]["resolution"] == target:
            return image.select(band).projection()
    return image.select(selected_bands[0]).projection()


def _prepare_band_on_grid(image, band, target_scale, reference_projection):
    """
    Converts Sentinel-2 SR integers to reflectance.
    If the band is finer than the target grid, aggregates with mean using
    reduceResolution(). It is then explicitly placed on the reference grid.
    """
    native = BAND_INFO[band]["resolution"]
    img = image.select(band).multiply(0.0001).rename(band)

    if native < target_scale:
        img = (
            img.reduceResolution(
                reducer=ee.Reducer.mean(),
                maxPixels=1024,
                bestEffort=True,
            )
            .reproject(reference_projection)
        )
    else:
        img = img.reproject(reference_projection)

    return img


def _prepare_selected_bands(image_t1, image_t2, selected_bands):
    """
    Prepares both acquisitions on one common spatial grid.
    Higher-resolution bands are downsampled to the coarser resolution
    using average aggregation.
    """
    target_scale = _analysis_resolution(selected_bands)

    ref_t1 = _reference_projection(image_t1, selected_bands).atScale(target_scale)
    ref_t2 = _reference_projection(image_t2, selected_bands).atScale(target_scale)

    # Force a common CRS/grid definition using T1 as the reference grid.
    ref_common = ref_t1

    t1_prepared = ee.Image.cat([
        _prepare_band_on_grid(image_t1, band, target_scale, ref_common)
        for band in selected_bands
    ]).rename(selected_bands)

    t2_prepared = ee.Image.cat([
        _prepare_band_on_grid(image_t2, band, target_scale, ref_common)
        for band in selected_bands
    ]).rename(selected_bands)

    # Common validity after resampling/reprojection.
    common = _common_valid_mask(t1_prepared, t2_prepared, selected_bands)
    t1_prepared = t1_prepared.updateMask(common)
    t2_prepared = t2_prepared.updateMask(common)

    return t1_prepared, t2_prepared, common, target_scale


def _sample_paired_times(t1_prepared, t2_prepared, selected_bands, aoi, scale):
    """
    Samples T1 and T2 together from one stacked image so that both scatterplots
    and histograms use the same geographic sample locations.
    """
    b1, b2 = selected_bands

    stacked = (
        t1_prepared.select([b1, b2]).rename([f"{b1}_T1", f"{b2}_T1"])
        .addBands(
            t2_prepared.select([b1, b2]).rename([f"{b1}_T2", f"{b2}_T2"])
        )
    )

    fc = stacked.sample(
        region=aoi,
        scale=scale,
        numPixels=MAX_SAMPLE_PIXELS,
        seed=42,
        geometries=False,
        tileScale=4,
        dropNulls=True,
    )

    features = fc.getInfo().get("features", [])
    points_t1 = []
    points_t2 = []

    for feature in features:
        p = feature.get("properties", {})

        vals = [
            _safe_number(p.get(f"{b1}_T1")),
            _safe_number(p.get(f"{b2}_T1")),
            _safe_number(p.get(f"{b1}_T2")),
            _safe_number(p.get(f"{b2}_T2")),
        ]

        if all(v is not None for v in vals):
            points_t1.append([vals[0], vals[1]])
            points_t2.append([vals[2], vals[3]])

    return points_t1, points_t2


def _pearson(points):
    if len(points) < 2:
        return None
    arr = np.asarray(points, dtype="float64")
    if np.std(arr[:, 0]) == 0 or np.std(arr[:, 1]) == 0:
        return None
    return float(np.corrcoef(arr[:, 0], arr[:, 1])[0, 1])


def _histogram_payload(points_t1, points_t2, selected_bands):
    arr1 = np.asarray(points_t1, dtype="float64") if points_t1 else np.empty((0, 2))
    arr2 = np.asarray(points_t2, dtype="float64") if points_t2 else np.empty((0, 2))

    result = {}

    for col, band in enumerate(selected_bands):
        vals1 = arr1[:, col] if len(arr1) else np.array([], dtype="float64")
        vals2 = arr2[:, col] if len(arr2) else np.array([], dtype="float64")
        combined = np.concatenate([vals1, vals2])

        if combined.size == 0:
            result[band] = {"bin_centers": [], "t1_counts": [], "t2_counts": []}
            continue

        low = float(np.percentile(combined, 1))
        high = float(np.percentile(combined, 99))
        if not math.isfinite(low) or not math.isfinite(high) or low == high:
            low = float(np.min(combined))
            high = float(np.max(combined))
        if low == high:
            high = low + 1e-6

        edges = np.linspace(low, high, HISTOGRAM_BINS + 1)
        h1, _ = np.histogram(vals1, bins=edges)
        h2, _ = np.histogram(vals2, bins=edges)
        centers = ((edges[:-1] + edges[1:]) / 2.0).tolist()

        result[band] = {
            "bin_centers": [float(x) for x in centers],
            "t1_counts": [int(x) for x in h1.tolist()],
            "t2_counts": [int(x) for x in h2.tolist()],
            "range_percentiles": [low, high],
        }

    return result


def _band_stats_from_points(points, selected_bands):
    arr = np.asarray(points, dtype="float64") if points else np.empty((0, 2))
    result = {}
    for col, band in enumerate(selected_bands):
        values = arr[:, col] if len(arr) else np.array([], dtype="float64")
        if values.size == 0:
            result[band] = {
                "count": 0, "mean": None, "median": None, "std": None,
                "min": None, "max": None, "p05": None, "p95": None
            }
        else:
            result[band] = {
                "count": int(values.size),
                "mean": float(np.mean(values)),
                "median": float(np.median(values)),
                "std": float(np.std(values)),
                "min": float(np.min(values)),
                "max": float(np.max(values)),
                "p05": float(np.percentile(values, 5)),
                "p95": float(np.percentile(values, 95)),
            }
    return result


def run_v1_analysis(
    aoi_geojson,
    t1_date,
    t2_date,
    selected_bands,
    analyses,
    cloud_cover=100.0
):
    initialize_earth_engine()
    aoi = _geojson_to_geometry(aoi_geojson)

    if t1_date == t2_date:
        raise ValueError("T1 and T2 must be two different acquisition timestamps.")

    for band in selected_bands:
        if band not in BAND_INFO:
            raise ValueError(f"Unsupported Sentinel-2 band: {band}")

    image_t1 = _mosaic_for_timestamp(t1_date, aoi, cloud_cover)
    image_t2 = _mosaic_for_timestamp(t2_date, aoi, cloud_cover)

    requested = set(analyses)

    result = {
        "status": "ok",
        "version": "1.2",
        "acquisitions": {"t1": t1_date, "t2": t2_date},
        "selected_bands": selected_bands,
        "spectral_indices": {},
        "band_analysis": {},
    }

    for index_name in ("ndvi", "ndre"):
        if index_name in requested:
            result["spectral_indices"][index_name] = _index_result(
                index_name, image_t1, image_t2, aoi
            )

    if {"scatterplot", "histogram"}.intersection(requested):
        if len(selected_bands) != 2:
            raise ValueError(
                "Two selected bands are required for scatterplot/histogram analysis."
            )

        t1_prepared, t2_prepared, common, scale = _prepare_selected_bands(
            image_t1, image_t2, selected_bands
        )

        points_t1, points_t2 = _sample_paired_times(
            t1_prepared, t2_prepared, selected_bands, aoi, scale
        )

        band_result = {
            "bands": [
                {
                    "code": b,
                    "name": BAND_INFO[b]["name"],
                    "native_resolution_m": BAND_INFO[b]["resolution"],
                }
                for b in selected_bands
            ],
            "analysis_scale_m": scale,
            "resampling": "average aggregation to coarser selected-band resolution",
            "common_grid_reference": "T1 coarser-band projection",
            "surface_reflectance_scale_factor": 0.0001,
            "common_valid_area": _common_coverage_metrics(common, aoi, scale),
            "samples": {
                "paired_locations": len(points_t1),
                "t1": len(points_t1),
                "t2": len(points_t2),
            },
            "statistics": {
                "t1": _band_stats_from_points(points_t1, selected_bands),
                "t2": _band_stats_from_points(points_t2, selected_bands),
            },
        }

        if "scatterplot" in requested:
            band_result["scatterplot"] = {
                "x_band": selected_bands[0],
                "y_band": selected_bands[1],
                "t1_points": points_t1,
                "t2_points": points_t2,
                "pearson_r": {
                    "t1": _pearson(points_t1),
                    "t2": _pearson(points_t2),
                },
            }

        if "histogram" in requested:
            band_result["histogram"] = _histogram_payload(
                points_t1, points_t2, selected_bands
            )

        result["band_analysis"] = band_result

    return result
