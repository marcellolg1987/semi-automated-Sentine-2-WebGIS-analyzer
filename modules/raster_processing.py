import numpy as np

def ndvi(red, nir):
    red = red.astype("float32")
    nir = nir.astype("float32")
    denominator = nir + red
    return np.divide(
        nir - red,
        denominator,
        out=np.full_like(red, np.nan, dtype="float32"),
        where=denominator != 0,
    )

def ndre(red_edge, narrow_nir):
    red_edge = red_edge.astype("float32")
    narrow_nir = narrow_nir.astype("float32")
    denominator = narrow_nir + red_edge
    return np.divide(
        narrow_nir - red_edge,
        denominator,
        out=np.full_like(red_edge, np.nan, dtype="float32"),
        where=denominator != 0,
    )

def temporal_difference(array_t1, array_t2):
    if array_t1.shape != array_t2.shape:
        raise ValueError("T1 and T2 arrays must have the same shape.")
    return array_t2.astype("float32") - array_t1.astype("float32")
