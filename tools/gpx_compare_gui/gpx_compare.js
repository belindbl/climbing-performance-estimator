const LOAD_API = "/api/compare/load";
const SEGMENT_API = "/api/compare/segment";
const TRACK_COLORS = ["#5f96ff", "#57b883", "#d8a84a", "#d06f61", "#b383ff", "#52c7d8"];

const state = {
  rawTracks: [],
  tracks: [],
  commonDistanceM: 0,
  startDistanceM: 0,
  endDistanceM: 0,
  activeBoundary: "start",
  draggingBoundary: null,
  referenceIndex: 0,
  syncMode: "distance",
  comparison: null,
  viewMode: "profile",
  route3d: empty3dState()
};

const els = {
  summary: document.getElementById("summary"),
  errorBox: document.getElementById("errorBox"),
  gpxFiles: document.getElementById("gpxFiles"),
  profile: document.getElementById("profile"),
  gapChart: document.getElementById("gapChart"),
  profileView: document.getElementById("profileView"),
  route3dView: document.getElementById("route3dView"),
  route3dStatus: document.getElementById("route3dStatus"),
  profileViewButton: document.getElementById("profileViewButton"),
  route3dViewButton: document.getElementById("route3dViewButton"),
  reset3dView: document.getElementById("reset3dView"),
  startBoundary: document.getElementById("startBoundary"),
  endBoundary: document.getElementById("endBoundary"),
  cursorReadout: document.getElementById("cursorReadout"),
  startDistance: document.getElementById("startDistance"),
  endDistance: document.getElementById("endDistance"),
  referenceTrack: document.getElementById("referenceTrack"),
  syncMode: document.getElementById("syncMode"),
  bikeMass: document.getElementById("bikeMass"),
  cda: document.getElementById("cda"),
  crr: document.getElementById("crr"),
  referenceTemperature: document.getElementById("referenceTemperature"),
  referencePressure: document.getElementById("referencePressure"),
  referenceHumidity: document.getElementById("referenceHumidity"),
  trackList: document.getElementById("trackList"),
  resultsBody: document.getElementById("resultsBody"),
  segmentDistance: document.getElementById("segmentDistance"),
  referenceName: document.getElementById("referenceName"),
  bestTime: document.getElementById("bestTime"),
  bestWkg: document.getElementById("bestWkg")
};

wireEvents();
renderEmpty();

function wireEvents() {
  els.gpxFiles.addEventListener("change", loadSelectedFiles);
  els.profileViewButton.addEventListener("click", () => setViewMode("profile"));
  els.route3dViewButton.addEventListener("click", () => setViewMode("route3d"));
  els.reset3dView.addEventListener("click", reset3dCamera);
  els.startBoundary.addEventListener("click", () => setActiveBoundary("start"));
  els.endBoundary.addEventListener("click", () => setActiveBoundary("end"));

  [els.bikeMass, els.cda, els.crr, els.referenceTemperature, els.referencePressure, els.referenceHumidity].forEach(input => {
    input.addEventListener("input", debounce(compareSelectedSegment, 250));
  });

  els.referenceTrack.addEventListener("change", () => {
    state.referenceIndex = Number(els.referenceTrack.value || 0);
    compareSelectedSegment();
  });
  els.syncMode.addEventListener("change", () => {
    state.syncMode = els.syncMode.value;
    compareSelectedSegment();
  });

  els.startDistance.addEventListener("change", () => {
    setBoundary("start", Number(els.startDistance.value || 0));
  });
  els.endDistance.addEventListener("change", () => {
    setBoundary("end", Number(els.endDistance.value || 0));
  });

  els.profile.addEventListener("pointerdown", event => {
    if (!state.tracks.length) return;
    const distance = distanceFromProfileX(event.clientX);
    const startDelta = Math.abs(distance - state.startDistanceM);
    const endDelta = Math.abs(distance - state.endDistanceM);
    const boundary = Math.min(startDelta, endDelta) < state.commonDistanceM * 0.035
      ? (startDelta <= endDelta ? "start" : "end")
      : state.activeBoundary;
    setActiveBoundary(boundary);
    state.draggingBoundary = boundary;
    setBoundary(boundary, distance, { deferCompare: true });
    event.preventDefault();
  });

  els.profile.addEventListener("pointermove", event => {
    if (!state.tracks.length) return;
    const distance = distanceFromProfileX(event.clientX);
    updateCursor(distance);
    if (state.draggingBoundary) {
      setBoundary(state.draggingBoundary, distance, { deferCompare: true });
    }
  });

  window.addEventListener("pointerup", () => {
    if (!state.draggingBoundary) return;
    state.draggingBoundary = null;
    compareSelectedSegment();
  });

  els.route3dView.addEventListener("pointermove", event => {
    if (!state.tracks.length || state.viewMode !== "route3d") return;
    const distance = nearestRouteDistanceFrom3D(event);
    if (distance !== null) updateCursor(distance);
  });

  els.route3dView.addEventListener("pointerdown", event => {
    if (!state.tracks.length || state.viewMode !== "route3d") return;
    const distance = nearestRouteDistanceFrom3D(event);
    if (distance === null) return;
    setBoundary(state.activeBoundary, distance);
  });

  window.addEventListener("resize", resize3dRenderer);
}

async function loadSelectedFiles() {
  const files = [...els.gpxFiles.files];
  if (!files.length) return;

  try {
    const rawTracks = [];
    for (let index = 0; index < files.length; index += 1) {
      rawTracks.push({
        name: files[index].name,
        gpx_text: await files[index].text(),
        rider_mass_kg: 60,
        color: TRACK_COLORS[index % TRACK_COLORS.length]
      });
    }
    state.rawTracks = rawTracks;
    await loadTracks();
  } catch (error) {
    showError(error.message);
  } finally {
    els.gpxFiles.value = "";
  }
}

async function loadTracks() {
  const payload = await postJson(LOAD_API, { tracks: state.rawTracks, fetch_weather: true });
  dispose3dRoute();
  state.tracks = payload.tracks.map(track => ({
    ...track,
    color: track.color || TRACK_COLORS[track.index % TRACK_COLORS.length],
    weatherSample: track.weather_sample || null,
    route: routeFromPayload(track.route)
  }));
  state.commonDistanceM = payload.common_distance_m;
  state.referenceIndex = Math.min(state.referenceIndex, state.tracks.length - 1);
  state.startDistanceM = 0;
  state.endDistanceM = state.commonDistanceM;
  syncInputs();
  renderTrackControls();
  renderReferenceSelect();
  renderProfile();
  init3dRoute();
  await compareSelectedSegment();
}

async function compareSelectedSegment() {
  if (!state.rawTracks.length || state.endDistanceM <= state.startDistanceM) {
    render();
    return;
  }

  try {
    clearError();
    state.comparison = await postJson(SEGMENT_API, {
      tracks: state.rawTracks,
      reference_index: state.referenceIndex,
      sync_mode: state.syncMode,
      start_distance_m: state.startDistanceM,
      end_distance_m: state.endDistanceM,
      distance_step_m: Math.max(5, (state.endDistanceM - state.startDistanceM) / 120),
      assumptions: {
        bike_mass_kg: readNumber(els.bikeMass),
        cda_m2: readNumber(els.cda),
        crr: readNumber(els.crr),
        weather_samples: state.tracks.map(track => track.weatherSample),
        reference_weather: referenceWeatherInput()
      }
    });
  } catch (error) {
    state.comparison = null;
    showError(error.message);
  }
  render();
}

function referenceWeatherInput() {
  if ([els.referenceTemperature, els.referencePressure, els.referenceHumidity]
    .some(input => input.value.trim() === "")) return null;
  const temperature = Number(els.referenceTemperature.value);
  const pressure = Number(els.referencePressure.value);
  const humidity = Number(els.referenceHumidity.value);
  if (![temperature, pressure, humidity].every(Number.isFinite)) return null;
  return {
    temperature_c: temperature,
    surface_pressure_hpa: pressure,
    relative_humidity_pct: humidity
  };
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "Request failed");
  }
  return result;
}

function routeFromPayload(routePayload) {
  return {
    name: routePayload.name,
    points: routePayload.points.map(point => ({
      lat: point.latitude,
      lon: point.longitude,
      ele: point.elevation_m,
      time: point.time ? new Date(point.time) : null,
      distance: point.distance_m
    })),
    distanceM: routePayload.distance_m,
    ascentM: routePayload.ascent_m,
    durationS: routePayload.duration_s,
    avgAltitudeM: routePayload.avg_altitude_m,
    minElevationM: routePayload.min_elevation_m,
    maxElevationM: routePayload.max_elevation_m
  };
}

function render() {
  syncInputs();
  renderProfile();
  render3dRoute();
  renderResults();
  renderGapChart();
  updateButtons();
}

function renderEmpty() {
  els.resultsBody.innerHTML = "";
  els.referenceTrack.innerHTML = "";
  els.trackList.innerHTML = "";
  renderProfile();
  renderGapChart();
  updateButtons();
}

function renderProfile() {
  const width = 980;
  const height = 420;
  const pad = { left: 54, right: 22, top: 24, bottom: 42 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const ns = "http://www.w3.org/2000/svg";
  els.profile.innerHTML = "";

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    addLine(ns, els.profile, pad.left, y, width - pad.right, y, "grid");
  }
  addLine(ns, els.profile, pad.left, height - pad.bottom, width - pad.right, height - pad.bottom, "axis");

  if (!state.tracks.length) {
    addText(ns, els.profile, pad.left, pad.top + 20, "Load GPX files");
    return;
  }

  const minEle = Math.min(...state.tracks.map(track => track.route.minElevationM).filter(Number.isFinite));
  const maxEle = Math.max(...state.tracks.map(track => track.route.maxElevationM).filter(Number.isFinite));
  const x = distance => pad.left + (distance / state.commonDistanceM) * plotW;
  const y = ele => {
    const span = Math.max(1, maxEle - minEle);
    return pad.top + (1 - (ele - minEle) / span) * plotH;
  };

  const band = document.createElementNS(ns, "rect");
  band.setAttribute("class", "selection-band");
  band.setAttribute("x", x(state.startDistanceM));
  band.setAttribute("y", pad.top);
  band.setAttribute("width", Math.max(1, x(state.endDistanceM) - x(state.startDistanceM)));
  band.setAttribute("height", plotH);
  els.profile.appendChild(band);

  for (const track of state.tracks) {
    const points = track.route.points.filter(point => point.ele !== null && point.distance <= state.commonDistanceM);
    if (points.length < 2) continue;
    const path = points
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.distance).toFixed(2)} ${y(point.ele).toFixed(2)}`)
      .join(" ");
    const line = document.createElementNS(ns, "path");
    line.setAttribute("class", "profile-line");
    line.setAttribute("d", path);
    line.setAttribute("stroke", track.color);
    els.profile.appendChild(line);
  }

  renderHandle(ns, x(state.startDistanceM), pad.top, height - pad.bottom, "start");
  renderHandle(ns, x(state.endDistanceM), pad.top, height - pad.bottom, "end");
  addText(ns, els.profile, pad.left, height - 15, "0 km");
  addText(ns, els.profile, width - pad.right - 58, height - 15, `${(state.commonDistanceM / 1000).toFixed(2)} km`);
  addText(ns, els.profile, 10, pad.top + 4, `${maxEle.toFixed(0)} m`);
  addText(ns, els.profile, 10, height - pad.bottom, `${minEle.toFixed(0)} m`);
}

function renderHandle(ns, x, y1, y2, boundary) {
  const hit = document.createElementNS(ns, "rect");
  hit.setAttribute("class", "handle-hit");
  hit.setAttribute("x", x - 18);
  hit.setAttribute("y", y1);
  hit.setAttribute("width", 36);
  hit.setAttribute("height", y2 - y1);
  hit.addEventListener("pointerdown", event => {
    setActiveBoundary(boundary);
    state.draggingBoundary = boundary;
    event.preventDefault();
    event.stopPropagation();
  });
  els.profile.appendChild(hit);

  const line = document.createElementNS(ns, "line");
  line.setAttribute("class", "handle");
  line.setAttribute("x1", x);
  line.setAttribute("x2", x);
  line.setAttribute("y1", y1);
  line.setAttribute("y2", y2);
  els.profile.appendChild(line);
}

function renderResults() {
  if (!state.tracks.length) {
    els.summary.textContent = "No tracks loaded";
    els.segmentDistance.textContent = "--";
    els.referenceName.textContent = "--";
    els.bestTime.textContent = "--";
    els.bestWkg.textContent = "--";
    els.resultsBody.innerHTML = "";
    return;
  }

  els.summary.textContent = `${state.tracks.length} tracks, common ${(state.commonDistanceM / 1000).toFixed(2)} km, sync by ${state.syncMode}`;
  els.segmentDistance.textContent = meters(state.endDistanceM - state.startDistanceM);
  els.referenceName.textContent = state.tracks[state.referenceIndex]?.name || "--";

  const rows = state.comparison ? state.comparison.tracks : [];
  const timedRows = rows.filter(row => row.segment.elapsed_s !== null);
  const best = timedRows.reduce((current, row) => (
    !current || row.segment.elapsed_s < current.segment.elapsed_s ? row : current
  ), null);
  const bestWkg = rows.reduce((current, row) => {
    const value = row.metrics.standard_60kg_w_per_kg;
    if (value === null) return current;
    return current === null || value > current ? value : current;
  }, null);

  els.bestTime.textContent = best ? formatTime(best.segment.elapsed_s) : "--";
  els.bestWkg.textContent = bestWkg === null ? "--" : bestWkg.toFixed(2);
  els.resultsBody.innerHTML = "";

  for (const row of rows) {
    const track = state.tracks[row.index];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><span class="track-name"><span class="swatch" style="background:${track.color}"></span>${escapeHtml(row.name)}</span></td>
      <td>${formatNullableTime(row.segment.elapsed_s)}</td>
      <td>${formatSignedTime(row.elapsed_gap_s)}</td>
      <td>${formatWatts(row.metrics.total_power_w)}</td>
      <td>${formatNumber(row.metrics.watts_per_kg, 2)}</td>
      <td>${formatNumber(row.metrics.standard_60kg_w_per_kg, 2)}</td>
      <td>${formatSpeed(row.metrics.road_speed_m_per_s)}</td>
      <td>${formatNumber(row.segment.vam_m_per_h, 0)}</td>
      <td>${formatPercent(row.segment.gradient_percent)}</td>
    `;
    els.resultsBody.appendChild(tr);
  }
}

function renderGapChart() {
  const width = 980;
  const height = 260;
  const pad = { left: 54, right: 22, top: 20, bottom: 38 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const ns = "http://www.w3.org/2000/svg";
  els.gapChart.innerHTML = "";

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    addLine(ns, els.gapChart, pad.left, y, width - pad.right, y, "grid");
  }
  addLine(ns, els.gapChart, pad.left, height - pad.bottom, width - pad.right, height - pad.bottom, "axis");

  if (!state.comparison || !state.comparison.gap_samples.length) {
    addText(ns, els.gapChart, pad.left, pad.top + 20, "No timing data");
    return;
  }

  const allGaps = state.comparison.gap_samples
    .flatMap(track => track.samples.map(sample => sample.gap_s))
    .filter(value => value !== null && Number.isFinite(value));
  if (!allGaps.length) {
    addText(ns, els.gapChart, pad.left, pad.top + 20, "No timing data");
    return;
  }

  const maxAbs = Math.max(1, ...allGaps.map(value => Math.abs(value)));
  const x = distance => pad.left + ((distance - state.startDistanceM) / (state.endDistanceM - state.startDistanceM)) * plotW;
  const y = gap => pad.top + (0.5 + gap / (2 * maxAbs)) * plotH;
  addLine(ns, els.gapChart, pad.left, y(0), width - pad.right, y(0), "axis");

  for (const trackSamples of state.comparison.gap_samples) {
    const points = trackSamples.samples.filter(sample => sample.gap_s !== null);
    if (points.length < 2) continue;
    const path = points
      .map((sample, index) => `${index === 0 ? "M" : "L"} ${x(sample.distance_m).toFixed(2)} ${y(sample.gap_s).toFixed(2)}`)
      .join(" ");
    const line = document.createElementNS(ns, "path");
    line.setAttribute("class", "gap-line");
    line.setAttribute("d", path);
    line.setAttribute("stroke", state.tracks[trackSamples.index]?.color || TRACK_COLORS[0]);
    els.gapChart.appendChild(line);
  }

  addText(ns, els.gapChart, 10, pad.top + 4, `+${maxAbs.toFixed(0)} s`);
  addText(ns, els.gapChart, 14, y(0) - 5, "0 s");
  addText(ns, els.gapChart, 14, height - pad.bottom, `-${maxAbs.toFixed(0)} s`);
}

function renderTrackControls() {
  els.trackList.innerHTML = "";
  state.tracks.forEach(track => {
    const row = document.createElement("div");
    row.className = "track-row";
    row.innerHTML = `
      <div class="swatch" style="background:${track.color}"></div>
      <div><strong>${escapeHtml(track.name)}</strong><span>${(track.route.distanceM / 1000).toFixed(2)} km, ${track.route.ascentM.toFixed(0)} m</span></div>
      <label>kg<input type="number" min="1" step="0.1" value="${track.rider_mass_kg.toFixed(1)}"></label>
    `;
    const input = row.querySelector("input");
    input.addEventListener("input", debounce(() => {
      track.rider_mass_kg = Number(input.value || 60);
      state.rawTracks[track.index].rider_mass_kg = track.rider_mass_kg;
      compareSelectedSegment();
    }, 250));
    els.trackList.appendChild(row);
  });
}

function renderReferenceSelect() {
  els.referenceTrack.innerHTML = "";
  state.tracks.forEach(track => {
    const option = document.createElement("option");
    option.value = track.index;
    option.textContent = track.name;
    option.selected = track.index === state.referenceIndex;
    els.referenceTrack.appendChild(option);
  });
}

function setBoundary(boundary, distance, options = {}) {
  const minGap = Math.min(10, Math.max(0.1, state.commonDistanceM / 10));
  if (boundary === "start") {
    state.startDistanceM = clamp(distance, 0, state.endDistanceM - minGap);
  } else {
    state.endDistanceM = clamp(distance, state.startDistanceM + minGap, state.commonDistanceM);
  }
  syncInputs();
  renderProfile();
  render3dRoute();
  updateCursor(boundary === "start" ? state.startDistanceM : state.endDistanceM);
  if (!options.deferCompare) {
    compareSelectedSegment();
  }
}

function setActiveBoundary(boundary) {
  state.activeBoundary = boundary;
  updateButtons();
}

function syncInputs() {
  els.startDistance.value = state.startDistanceM.toFixed(0);
  els.endDistance.value = state.endDistanceM.toFixed(0);
  els.syncMode.value = state.syncMode;
}

function updateButtons() {
  els.startBoundary.classList.toggle("active", state.activeBoundary === "start");
  els.endBoundary.classList.toggle("active", state.activeBoundary === "end");
  els.profileViewButton.classList.toggle("active", state.viewMode === "profile");
  els.route3dViewButton.classList.toggle("active", state.viewMode === "route3d");
  els.profileView.classList.toggle("active", state.viewMode === "profile");
  els.route3dView.classList.toggle("active", state.viewMode === "route3d");
}

function updateCursor(distance) {
  if (!Number.isFinite(distance) || !state.tracks.length) return;
  els.cursorReadout.textContent = `${meters(distance)} from start, ${meters(state.commonDistanceM - distance)} remaining`;
}

function distanceFromProfileX(clientX) {
  const rect = els.profile.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * 980;
  const padLeft = 54;
  const padRight = 22;
  const plotW = 980 - padLeft - padRight;
  return clamp(((x - padLeft) / plotW) * state.commonDistanceM, 0, state.commonDistanceM);
}

function setViewMode(viewMode) {
  state.viewMode = viewMode;
  updateButtons();
  if (viewMode === "route3d") {
    init3dRoute();
    render3dRoute();
    resize3dRenderer();
  }
}

function init3dRoute() {
  if (!state.tracks.length || state.route3d.renderer) return;
  if (!window.THREE || !THREE.OrbitControls) {
    els.route3dStatus.textContent = "3D unavailable";
    return;
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  els.route3dView.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x121a22);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100000);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  scene.add(new THREE.AmbientLight(0xffffff, 0.78));
  const light = new THREE.DirectionalLight(0xffffff, 0.72);
  light.position.set(200, 400, 300);
  scene.add(light);

  state.route3d = {
    renderer,
    scene,
    camera,
    controls,
    routeGroup: new THREE.Group(),
    handleGroup: new THREE.Group(),
    pointsByTrack: [],
    bounds: null,
    animationFrame: null
  };
  scene.add(state.route3d.routeGroup);
  scene.add(state.route3d.handleGroup);
  build3dPoints();
  reset3dCamera();
  animate3dRoute();
  els.route3dStatus.textContent = "";
}

function dispose3dRoute() {
  const route3d = state.route3d;
  if (route3d.animationFrame) {
    cancelAnimationFrame(route3d.animationFrame);
  }
  if (route3d.renderer) {
    route3d.renderer.dispose();
    route3d.renderer.domElement.remove();
  }
  state.route3d = empty3dState();
  els.route3dStatus.textContent = "3D route loading";
}

function empty3dState() {
  return {
    renderer: null,
    scene: null,
    camera: null,
    controls: null,
    routeGroup: null,
    handleGroup: null,
    pointsByTrack: [],
    bounds: null,
    animationFrame: null
  };
}

function build3dPoints() {
  if (!state.route3d.renderer || !state.tracks.length) return;
  const allPoints = state.tracks.flatMap(track => track.route.points);
  const lat0 = allPoints.reduce((sum, point) => sum + point.lat, 0) / allPoints.length;
  const lon0 = allPoints.reduce((sum, point) => sum + point.lon, 0) / allPoints.length;
  const metersPerLat = 111320;
  const metersPerLon = 111320 * Math.cos(radians(lat0));
  const minEle = Math.min(...allPoints.map(point => point.ele).filter(Number.isFinite));
  const maxEle = Math.max(...allPoints.map(point => point.ele).filter(Number.isFinite));
  const verticalScale = Math.max(1.5, Math.min(5, state.commonDistanceM / Math.max(1, (maxEle - minEle) * 6)));
  const box = new THREE.Box3();

  state.route3d.pointsByTrack = state.tracks.map(track => {
    const points = track.route.points.map(point => ({
      distance: point.distance,
      x: (point.lon - lon0) * metersPerLon,
      y: ((point.ele ?? minEle) - minEle) * verticalScale,
      z: -(point.lat - lat0) * metersPerLat
    }));
    points.forEach(point => box.expandByPoint(new THREE.Vector3(point.x, point.y, point.z)));
    return points;
  });
  state.route3d.bounds = box;
}

function render3dRoute() {
  if (!state.route3d.renderer || !state.tracks.length) return;
  clear3dGroup(state.route3d.routeGroup);
  clear3dGroup(state.route3d.handleGroup);

  state.route3d.pointsByTrack.forEach((points, index) => {
    const vectors = points
      .filter(point => point.distance <= state.commonDistanceM)
      .map(point => new THREE.Vector3(point.x, point.y, point.z));
    if (vectors.length < 2) return;
    const geometry = new THREE.BufferGeometry().setFromPoints(vectors);
    const material = new THREE.LineBasicMaterial({ color: new THREE.Color(state.tracks[index].color) });
    state.route3d.routeGroup.add(new THREE.Line(geometry, material));
  });

  render3dBoundary(state.startDistanceM, 0x5f96ff);
  render3dBoundary(state.endDistanceM, 0xf2f7ff);
  resize3dRenderer();
}

function render3dBoundary(distance, color) {
  const point = route3dPointAtDistance(distance);
  if (!point) return;
  const geometry = new THREE.SphereGeometry(9, 18, 18);
  const material = new THREE.MeshStandardMaterial({ color, emissive: color === 0x5f96ff ? 0x1b315e : 0x000000 });
  const sphere = new THREE.Mesh(geometry, material);
  sphere.position.copy(point);
  state.route3d.handleGroup.add(sphere);
}

function route3dPointAtDistance(distance) {
  const points = state.route3d.pointsByTrack[state.referenceIndex] || [];
  if (!points.length) return null;
  const clamped = clamp(distance, 0, state.commonDistanceM);
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].distance >= clamped) {
      const previous = points[i - 1];
      const current = points[i];
      const span = current.distance - previous.distance;
      const fraction = span > 0 ? (clamped - previous.distance) / span : 0;
      return new THREE.Vector3(
        lerp(previous.x, current.x, fraction),
        lerp(previous.y, current.y, fraction),
        lerp(previous.z, current.z, fraction)
      );
    }
  }
  const last = points[points.length - 1];
  return new THREE.Vector3(last.x, last.y, last.z);
}

function nearestRouteDistanceFrom3D(event) {
  if (!state.route3d.renderer || !state.route3d.pointsByTrack.length) return null;
  const points = state.route3d.pointsByTrack[state.referenceIndex] || [];
  const rect = state.route3d.renderer.domElement.getBoundingClientRect();
  const mouseX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  const mouseY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  const projected = new THREE.Vector3();
  let best = null;
  let bestDistance = Infinity;

  for (const point of points) {
    if (point.distance > state.commonDistanceM) continue;
    projected.set(point.x, point.y, point.z).project(state.route3d.camera);
    const dx = projected.x - mouseX;
    const dy = projected.y - mouseY;
    const distance = dx * dx + dy * dy;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = point.distance;
    }
  }

  return best;
}

function reset3dCamera() {
  if (!state.route3d.camera || !state.route3d.bounds) return;
  const box = state.route3d.bounds;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 100);
  state.route3d.camera.position.set(center.x + radius * 0.9, center.y + radius * 0.65, center.z + radius * 0.9);
  state.route3d.camera.near = Math.max(0.1, radius / 1000);
  state.route3d.camera.far = radius * 20;
  state.route3d.camera.lookAt(center);
  state.route3d.camera.updateProjectionMatrix();
  state.route3d.controls.target.copy(center);
  state.route3d.controls.update();
}

function resize3dRenderer() {
  if (!state.route3d.renderer || !state.route3d.camera) return;
  const rect = els.route3dView.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = 440;
  state.route3d.renderer.setSize(width, height, false);
  state.route3d.camera.aspect = width / height;
  state.route3d.camera.updateProjectionMatrix();
}

function animate3dRoute() {
  if (!state.route3d.renderer) return;
  state.route3d.animationFrame = requestAnimationFrame(animate3dRoute);
  state.route3d.controls.update();
  state.route3d.renderer.render(state.route3d.scene, state.route3d.camera);
}

function clear3dGroup(group) {
  while (group.children.length) {
    const child = group.children[0];
    group.remove(child);
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  }
}

function addLine(ns, parent, x1, y1, x2, y2, className) {
  const line = document.createElementNS(ns, "line");
  line.setAttribute("class", className);
  line.setAttribute("x1", x1);
  line.setAttribute("x2", x2);
  line.setAttribute("y1", y1);
  line.setAttribute("y2", y2);
  parent.appendChild(line);
}

function addText(ns, parent, x, y, text) {
  const node = document.createElementNS(ns, "text");
  node.setAttribute("x", x);
  node.setAttribute("y", y);
  node.setAttribute("font-size", "12");
  node.setAttribute("fill", "#99a6b5");
  node.textContent = text;
  parent.appendChild(node);
}

function readNumber(input) {
  return Number(input.value || 0);
}

function meters(value) {
  if (!Number.isFinite(value)) return "--";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} km`;
  return `${value.toFixed(0)} m`;
}

function formatTime(seconds) {
  if (seconds === null || !Number.isFinite(seconds)) return "--";
  const sign = seconds < 0 ? "-" : "";
  const abs = Math.abs(seconds);
  const minutes = Math.floor(abs / 60);
  const rest = Math.round(abs % 60).toString().padStart(2, "0");
  return `${sign}${minutes}:${rest}`;
}

function formatNullableTime(seconds) {
  return seconds === null ? "--" : formatTime(seconds);
}

function formatSignedTime(seconds) {
  if (seconds === null || !Number.isFinite(seconds)) return "--";
  if (Math.abs(seconds) < 0.05) return "0:00";
  return `${seconds > 0 ? "+" : ""}${formatTime(seconds)}`;
}

function formatWatts(value) {
  return value === null || !Number.isFinite(value) ? "--" : `${value.toFixed(0)} W`;
}

function formatSpeed(value) {
  return value === null || !Number.isFinite(value) ? "--" : `${(value * 3.6).toFixed(1)} km/h`;
}

function formatNumber(value, decimals) {
  return value === null || !Number.isFinite(value) ? "--" : value.toFixed(decimals);
}

function formatPercent(value) {
  return value === null || !Number.isFinite(value) ? "--" : `${value.toFixed(1)} %`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char]));
}

function showError(message) {
  els.errorBox.textContent = message;
  els.errorBox.style.display = "block";
}

function clearError() {
  els.errorBox.textContent = "";
  els.errorBox.style.display = "none";
}

function debounce(callback, delayMs) {
  let timeoutId = null;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delayMs);
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function radians(value) {
  return value * Math.PI / 180;
}

function lerp(start, end, fraction) {
  return start + (end - start) * fraction;
}
