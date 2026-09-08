import numpy as np

def descriptive_statistics(values):
    values = np.asarray(values, dtype="float64")
    values = values[np.isfinite(values)]

    if values.size == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "p05": None,
            "p95": None,
        }

    return {
        "count": int(values.size),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "std": float(np.std(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "p05": float(np.percentile(values, 5)),
        "p95": float(np.percentile(values, 95)),
    }

def pearson_correlation(x, y):
    x = np.asarray(x, dtype="float64").ravel()
    y = np.asarray(y, dtype="float64").ravel()
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]

    if x.size < 2:
        return None

    return float(np.corrcoef(x, y)[0, 1])
