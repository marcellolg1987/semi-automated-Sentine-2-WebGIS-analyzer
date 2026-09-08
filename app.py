from flask import Flask, render_template, request, jsonify

from modules.gee_manager import (
    search_sentinel2_acquisitions,
    get_gee_status,
    run_v1_analysis,
)
from config.settings import APP_HOST, APP_PORT, DEBUG

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify({
        "application": "Sentinel-2 Multispectral Analyzer",
        "version": "0.2.0-demo",
        "gee": get_gee_status()
    })


@app.post("/api/acquisitions/search")
def search_acquisitions():
    payload = request.get_json(force=True)

    required = ["aoi", "start_date", "end_date", "cloud_cover"]
    missing = [key for key in required if key not in payload]
    if missing:
        return jsonify({"error": f"Missing parameters: {', '.join(missing)}"}), 400

    try:
        acquisitions = search_sentinel2_acquisitions(
            aoi_geojson=payload["aoi"],
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            cloud_cover=float(payload["cloud_cover"]),
        )
        return jsonify({
            "count": len(acquisitions),
            "acquisitions": acquisitions
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/analysis/run")
def run_analysis():
    payload = request.get_json(force=True)

    required = ["aoi", "t1", "t2", "bands", "analyses"]
    missing = [key for key in required if key not in payload]
    if missing:
        return jsonify({"error": f"Missing parameters: {', '.join(missing)}"}), 400

    try:
        analyses = [str(x).lower() for x in payload["analyses"]]
        bands = list(dict.fromkeys(payload["bands"]))[:2]

        if not analyses:
            return jsonify({"error": "Select at least one analysis."}), 400

        band_analyses = {"scatterplot", "histogram"}
        if band_analyses.intersection(analyses) and len(bands) != 2:
            return jsonify({
                "error": "Scatterplot and histogram require two different selected bands."
            }), 400

        if len(bands) == 2 and bands[0] == bands[1]:
            return jsonify({"error": "Band 1 and Band 2 must be different."}), 400

        result = run_v1_analysis(
            aoi_geojson=payload["aoi"],
            t1_date=payload["t1"],
            t2_date=payload["t2"],
            selected_bands=bands,
            analyses=analyses,
            cloud_cover=float(payload.get("cloud_cover", 100.0)),
        )
        return jsonify(result)

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=DEBUG)
