const map = L.map("map").setView([37.7, 13.4], 8);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors"
}).addTo(map);

const drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

const drawControl = new L.Control.Draw({
  edit: { featureGroup: drawnItems },
  draw: {
    polygon: true,
    rectangle: true,
    polyline: false,
    circle: false,
    marker: false,
    circlemarker: false
  }
});
map.addControl(drawControl);

let currentAOI = null;
let acquisitions = [];
let analysisLayers = {};
let layerControl = null;

map.on(L.Draw.Event.CREATED, function (event) {
  drawnItems.clearLayers();
  drawnItems.addLayer(event.layer);
  currentAOI = event.layer.toGeoJSON();
  map.fitBounds(event.layer.getBounds());
  setMessage("AOI selected.");
});

map.on(L.Draw.Event.EDITED, function () {
  const layers = drawnItems.getLayers();
  currentAOI = layers.length ? layers[0].toGeoJSON() : null;
});

map.on(L.Draw.Event.DELETED, function () {
  currentAOI = null;
});

document.getElementById("searchBtn").addEventListener("click", searchAcquisitions);
document.getElementById("runBtn").addEventListener("click", runAnalysis);

async function searchAcquisitions() {
  if (!currentAOI) {
    setMessage("Draw an AOI before searching.", true);
    return;
  }

  const payload = {
    aoi: currentAOI,
    start_date: document.getElementById("startDate").value,
    end_date: document.getElementById("endDate").value,
    cloud_cover: Number(document.getElementById("cloudCover").value)
  };

  setMessage("Searching Sentinel-2 acquisitions...");

  try {
    const response = await fetch("/api/acquisitions/search", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();

    if (!response.ok) throw new Error(data.error || "Search failed.");

    acquisitions = data.acquisitions;
    populateAcquisitionSelectors(acquisitions);
    setMessage(`${data.count} acquisition dates found.`);
  } catch (error) {
    setMessage(error.message, true);
  }
}

function populateAcquisitionSelectors(items) {
  const t1 = document.getElementById("t1");
  const t2 = document.getElementById("t2");
  t1.innerHTML = "";
  t2.innerHTML = "";

  items.forEach((item) => {
    const cloud = item.cloud_cover_mean == null
      ? "n/a"
      : Number(item.cloud_cover_mean).toFixed(1);

    const tileCount = (item.mgrs_tiles || []).length;
    const tileWord = tileCount === 1 ? "tile" : "tiles";
    const tiles = (item.mgrs_tiles || []).map(t => `T${t}`).join(", ");

    const label =
      `${item.date} · ${item.time_utc} UTC | clouds ${cloud}% | ` +
      `${tileCount} ${tileWord}${tiles ? " | " + tiles : ""}`;

    [t1, t2].forEach((select) => {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = label;
      select.appendChild(option);
    });
  });

  if (items.length > 1) t2.selectedIndex = items.length - 1;
}

function selectedBands() {
  return [
    document.getElementById("band1").value,
    document.getElementById("band2").value
  ];
}

function selectedAnalyses() {
  return [...document.querySelectorAll('input[name="analysis"]:checked')]
    .map(el => el.value);
}

async function runAnalysis() {
  if (!currentAOI) {
    setMessage("Draw an AOI first.", true);
    return;
  }

  const t1 = document.getElementById("t1").value;
  const t2 = document.getElementById("t2").value;
  const bands = selectedBands();
  const analyses = selectedAnalyses();

  if (!t1 || !t2) {
    setMessage("Search and select two acquisitions first.", true);
    return;
  }

  if (t1 === t2) {
    setMessage("T1 and T2 must be different acquisition dates.", true);
    return;
  }

  if (!analyses.length) {
    setMessage("Select at least one analysis.", true);
    return;
  }

  const needsBands = analyses.includes("scatterplot") || analyses.includes("histogram");
  if (needsBands && (!bands[0] || !bands[1] || bands[0] === bands[1])) {
    setMessage("Band analysis requires two different bands.", true);
    return;
  }

  const payload = {
    aoi: currentAOI,
    t1,
    t2,
    bands,
    analyses,
    cloud_cover: Number(document.getElementById("cloudCover").value)
  };

  setMessage("Running Sentinel-2 analysis...");
  document.getElementById("runBtn").disabled = true;

  try {
    const response = await fetch("/api/analysis/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });
    const data = await response.json();

    document.getElementById("results").textContent =
      JSON.stringify(data, null, 2);

    if (!response.ok) {
      throw new Error(data.error || "Analysis request failed.");
    }

    renderResults(data);
    setMessage("Analysis completed.");
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    document.getElementById("runBtn").disabled = false;
  }
}

function renderResults(data) {
  clearAnalysisLayers();
  document.getElementById("summary").innerHTML = `
    <div class="result-card">
      <strong>Multitemporal comparison</strong><br>
      T1: ${data.acquisitions.t1}<br>
      T2: ${data.acquisitions.t2}
    </div>
  `;

  renderSpectralIndices(data.spectral_indices || {});
  renderBandAnalysis(data.band_analysis || {});
}

function renderSpectralIndices(indices) {
  const container = document.getElementById("indexResults");
  container.innerHTML = "";

  Object.entries(indices).forEach(([key, item]) => {
    const card = document.createElement("div");
    card.className = "result-card";

    const t1 = statsTableRows(item.t1.statistics);
    const t2 = statsTableRows(item.t2.statistics);
    const delta = statsTableRows(item.delta_t2_minus_t1.statistics);

    const coverage = item.common_valid_area || {};
    card.innerHTML = `
      <h3>${item.label}</h3>
      <p>Automatic bands: ${item.formula_bands.join(" + ")}</p>
      <p>
        Common valid area: ${formatNumber(coverage.common_valid_km2)} km²
        (${formatNumber(coverage.coverage_percent)}% of AOI)
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Metric</th><th>T1</th><th>T2</th><th>Δ T2−T1</th></tr>
          </thead>
          <tbody>
            ${["mean","median","std","min","max","p05","p95"].map(metric => `
              <tr>
                <td>${metric}</td>
                <td>${formatNumber(item.t1.statistics[metric])}</td>
                <td>${formatNumber(item.t2.statistics[metric])}</td>
                <td>${formatNumber(item.delta_t2_minus_t1.statistics[metric])}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
    container.appendChild(card);

    addAnalysisLayer(`${item.label} T1`, item.t1.tile_url);
    addAnalysisLayer(`${item.label} T2`, item.t2.tile_url);
    addAnalysisLayer(`Δ${item.label} T2−T1`, item.delta_t2_minus_t1.tile_url);
  });

  refreshLayerControl();
}

function renderBandAnalysis(bandAnalysis) {
  const charts = document.getElementById("charts");
  charts.innerHTML = "";

  if (!bandAnalysis || !bandAnalysis.bands) return;

  const meta = document.createElement("div");
  meta.className = "result-card";
  const coverage = bandAnalysis.common_valid_area || {};
  meta.innerHTML = `
    <h3>Selected-band analysis</h3>
    <p>
      ${bandAnalysis.bands[0].code} (${bandAnalysis.bands[0].name}) vs
      ${bandAnalysis.bands[1].code} (${bandAnalysis.bands[1].name}) ·
      common analysis scale: ${bandAnalysis.analysis_scale_m} m
    </p>
    <p>
      Resampling: ${bandAnalysis.resampling}
    </p>
    <p>
      Common valid area: ${formatNumber(coverage.common_valid_km2)} km²
      (${formatNumber(coverage.coverage_percent)}% of AOI)
    </p>
    <p>
      Paired sample locations: ${bandAnalysis.samples.paired_locations}
    </p>
  `;
  charts.appendChild(meta);

  if (bandAnalysis.scatterplot) {
    const scatter = document.createElement("div");
    scatter.className = "chart-card";
    scatter.innerHTML = `
      <h3>Band-to-band scatterplot</h3>
      <div id="scatterPlot" class="plot"></div>
      <p class="hint">
        Pearson r: T1 = ${formatNumber(bandAnalysis.scatterplot.pearson_r.t1)},
        T2 = ${formatNumber(bandAnalysis.scatterplot.pearson_r.t2)}
      </p>
    `;
    charts.appendChild(scatter);

    const p1 = bandAnalysis.scatterplot.t1_points;
    const p2 = bandAnalysis.scatterplot.t2_points;

    Plotly.newPlot("scatterPlot", [
      {
        x: p1.map(p => p[0]),
        y: p1.map(p => p[1]),
        mode: "markers",
        type: "scattergl",
        name: `T1 · ${document.getElementById("t1").value}`,
        marker: {size: 4, opacity: 0.45}
      },
      {
        x: p2.map(p => p[0]),
        y: p2.map(p => p[1]),
        mode: "markers",
        type: "scattergl",
        name: `T2 · ${document.getElementById("t2").value}`,
        marker: {size: 4, opacity: 0.45}
      }
    ], {
      xaxis: {title: bandAnalysis.scatterplot.x_band},
      yaxis: {title: bandAnalysis.scatterplot.y_band},
      margin: {t: 20, r: 20, b: 55, l: 60},
      legend: {orientation: "h"}
    }, {responsive: true});
  }

  if (bandAnalysis.histogram) {
    Object.entries(bandAnalysis.histogram).forEach(([band, hist], index) => {
      const id = `histogram_${index}`;
      const card = document.createElement("div");
      card.className = "chart-card";
      card.innerHTML = `
        <h3>Histogram · ${band}</h3>
        <div id="${id}" class="plot"></div>
      `;
      charts.appendChild(card);

      Plotly.newPlot(id, [
        {
          x: hist.bin_centers,
          y: hist.t1_counts,
          type: "bar",
          name: `T1 · ${document.getElementById("t1").value}`,
          opacity: 0.55
        },
        {
          x: hist.bin_centers,
          y: hist.t2_counts,
          type: "bar",
          name: `T2 · ${document.getElementById("t2").value}`,
          opacity: 0.55
        }
      ], {
        barmode: "overlay",
        xaxis: {title: `${band} surface reflectance`},
        yaxis: {title: "Sample count"},
        margin: {t: 20, r: 20, b: 55, l: 60},
        legend: {orientation: "h"}
      }, {responsive: true});
    });
  }
}

function addAnalysisLayer(name, tileUrl) {
  if (!tileUrl) return;
  const layer = L.tileLayer(tileUrl, {
    opacity: 0.75,
    attribution: "Google Earth Engine / Copernicus Sentinel-2"
  });
  analysisLayers[name] = layer;
}

function clearAnalysisLayers() {
  Object.values(analysisLayers).forEach(layer => map.removeLayer(layer));
  analysisLayers = {};
  if (layerControl) {
    map.removeControl(layerControl);
    layerControl = null;
  }
}

function refreshLayerControl() {
  if (!Object.keys(analysisLayers).length) return;

  layerControl = L.control.layers(null, analysisLayers, {
    collapsed: false
  }).addTo(map);

  const firstLayer = Object.values(analysisLayers)[0];
  firstLayer.addTo(map);
}

function statsTableRows(stats) {
  return stats || {};
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(4);
}

function setMessage(message, isError=false) {
  const el = document.getElementById("message");
  el.textContent = message;
  el.className = isError ? "message error" : "message";
}
