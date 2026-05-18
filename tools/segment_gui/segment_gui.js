const HYDRATE_API = "/api/routes/hydrate";
const ACTIVE_SCENARIO_API = "/api/scenarios/active";
const G = 9.81;
const RHO0 = 1.225;
const SCALE_HEIGHT_M = 8500;
const STANDARD_TEMP_K = 288.15;

const protectionTypes = {
  moto5: { label: "Moto 5 m", aeroMultiplier: 0.60, color: "#4f8f72" },
  moto10: { label: "Moto 10 m", aeroMultiplier: 0.77, color: "#3d7fa3" },
  protected: { label: "Protected", aeroMultiplier: 0.55, color: "#7a9152" },
  low: { label: "Low protection", aeroMultiplier: 0.58, color: "#d1a23b" },
  solo: { label: "Solo", aeroMultiplier: 1.0, color: "#b85d4d" }
};

const state = {
  route: null,
  segments: [
    { start: 0, end: 0, type: "moto10" },
    { start: 0, end: 0, type: "solo" }
  ],
  draggingHandle: null,
  selectedBreakpointIndex: null,
  placingBreakpoint: false,
  viewMode: "profile",
  route3d: {
    renderer: null,
    scene: null,
    camera: null,
    controls: null,
    routeGroup: null,
    handleGroup: null,
    points3d: [],
    bounds: null,
    pointerDown: null,
    animationFrame: null
  }
};

  const els = {
    profileView: document.getElementById("profileView"),
    route3dView: document.getElementById("route3dView"),
    route3dStatus: document.getElementById("route3dStatus"),
    profileViewButton: document.getElementById("profileViewButton"),
    route3dViewButton: document.getElementById("route3dViewButton"),
    reset3dView: document.getElementById("reset3dView"),
    cursorReadout: document.getElementById("cursorReadout"),
    svg: document.getElementById("profile"),
    routeTitle: document.getElementById("routeTitle"),
    routeSummary: document.getElementById("routeSummary"),
    errorBox: document.getElementById("errorBox"),
    segmentList: document.getElementById("segmentList"),
    addBreakpoint: document.getElementById("addBreakpoint"),
    gpxFile: document.getElementById("gpxFile"),
  riderMass: document.getElementById("riderMass"),
  bikeMass: document.getElementById("bikeMass"),
  cda: document.getElementById("cda"),
  crr: document.getElementById("crr"),
  temperature: document.getElementById("temperature"),
  windDirection: document.getElementById("windDirection"),
  wkg: document.getElementById("wkg"),
  power: document.getElementById("power"),
  aero: document.getElementById("aero"),
  gradient: document.getElementById("gradient"),
  aslpPower: document.getElementById("aslpPower"),
  aslpWkg: document.getElementById("aslpWkg"),
  standardWkg: document.getElementById("standardWkg"),
  vam: document.getElementById("vam"),
  altitudeLoss: document.getElementById("altitudeLoss"),
  gravityPower: document.getElementById("gravityPower"),
  rollingPower: document.getElementById("rollingPower"),
  advancedAeroPower: document.getElementById("advancedAeroPower"),
  stillAirAeroPower: document.getElementById("stillAirAeroPower"),
  windDeltaPower: document.getElementById("windDeltaPower"),
  headwindReadout: document.getElementById("headwindReadout"),
  airDensity: document.getElementById("airDensity"),
  tempReadout: document.getElementById("tempReadout"),
  windDirectionReadout: document.getElementById("windDirectionReadout"),
  windSpeedReadout: document.getElementById("windSpeedReadout"),
  weatherSource: document.getElementById("weatherSource"),
  segmentBreakdown: document.getElementById("segmentBreakdown")
};

init();

async function init() {
  try {
    loadRoute(await hydrateRoute({ route_id: "la-redoute" }));
    wireEvents();
    render();
  } catch (error) {
    showError(error.message);
  }
}

function wireEvents() {
  [
    els.riderMass,
    els.bikeMass,
    els.cda,
    els.crr
  ]
    .forEach(input => input.addEventListener("input", render));

  els.gpxFile.addEventListener("change", async () => {
    const file = els.gpxFile.files[0];
    if (!file) return;

    try {
      loadRoute(await hydrateRoute({ gpx_text: await file.text(), file_name: file.name }));
      render();
    } catch (error) {
      showError(error.message);
    } finally {
      els.gpxFile.value = "";
    }
  });

  els.addBreakpoint.addEventListener("click", () => {
    if (!state.route) return;
    state.placingBreakpoint = !state.placingBreakpoint;
    updateInteractionState();
  });

  els.profileViewButton.addEventListener("click", () => setViewMode("profile"));
  els.route3dViewButton.addEventListener("click", () => setViewMode("route3d"));
  els.reset3dView.addEventListener("click", reset3dCamera);

  els.svg.addEventListener("pointerdown", event => {
    if (!state.route || event.target.classList.contains("handle-hit")) return;
    const distance = nearestRouteDistanceFrom2D(event.clientX);
    selectOrInsertBreakpoint(distance);
    event.preventDefault();
  });

  els.route3dView.addEventListener("pointerdown", event => {
    state.route3d.pointerDown = { x: event.clientX, y: event.clientY };
  });

  els.route3dView.addEventListener("pointerup", event => {
    if (!state.route || state.viewMode !== "route3d") return;
    const start = state.route3d.pointerDown;
    state.route3d.pointerDown = null;
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 4) return;
    const distance = nearestRouteDistanceFrom3D(event);
    if (distance !== null) {
      selectOrInsertBreakpoint(distance);
    }
  });

  els.route3dView.addEventListener("pointermove", event => {
    if (!state.route || state.viewMode !== "route3d") return;
    const distance = nearestRouteDistanceFrom3D(event);
    updateCursorReadout(distance);
  });

  window.addEventListener("pointermove", event => {
    if (state.draggingHandle === null || !state.route) return;
    const distance = nearestRouteDistanceFrom2D(event.clientX);
    moveBreakpoint(state.draggingHandle, distance);
    render();
  });

  window.addEventListener("pointerup", () => {
    state.draggingHandle = null;
  });
}

async function hydrateRoute(payload) {
  const response = await fetch(HYDRATE_API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.error || "Could not hydrate route");
  }
  return result;
}

function loadRoute(payload) {
  dispose3dRoute();
  state.route = routeFromHydratedPayload(payload);
  const soloRemaining = Math.min(865, state.route.distanceM / 2);
  const split = Math.max(0, state.route.distanceM - soloRemaining);
  state.segments = [
    { start: 0, end: split, type: "moto10" },
    { start: split, end: state.route.distanceM, type: "solo" }
  ];
  state.selectedBreakpointIndex = state.segments.length > 1 ? 1 : null;
  state.placingBreakpoint = false;
  updateRouteTitle();
  els.errorBox.textContent = "";
  els.errorBox.style.display = "none";
  syncWeatherControls();
  init3dRoute();
  if (state.route.weather.warning) {
    showError(state.route.weather.warning);
  }
}

function routeFromHydratedPayload(payload) {
  const routePayload = payload.route;
  const weather = payload.weather || { status: "unavailable", samples: [] };
  return {
    points: routePayload.points.map(point => ({
      lat: point.latitude,
      lon: point.longitude,
      ele: point.elevation_m,
      time: point.time ? new Date(point.time) : null,
      distance: point.distance_m
    })),
    segments: routePayload.segments.map(segment => ({
      startDistanceM: segment.start_distance_m,
      endDistanceM: segment.end_distance_m,
      distanceM: segment.distance_m,
      elevationDeltaM: segment.elevation_delta_m,
      elapsedS: segment.elapsed_s,
      bearingDeg: segment.bearing_deg,
      startTime: segment.start_time ? new Date(segment.start_time) : null,
      endTime: segment.end_time ? new Date(segment.end_time) : null,
      startElevationM: segment.start_elevation_m,
      endElevationM: segment.end_elevation_m
    })),
    name: routePayload.name || "GPX Route",
    distanceM: routePayload.distance_m,
    ascentM: routePayload.ascent_m,
    descentM: routePayload.descent_m,
    durationS: routePayload.duration_s,
    avgAltitudeM: routePayload.avg_altitude_m,
    minElevationM: routePayload.min_elevation_m,
    maxElevationM: routePayload.max_elevation_m,
    weather: {
      ...weather,
      samples: (weather.samples || []).map(sample => ({
        ...sample,
        time: new Date(sample.time)
      }))
    }
  };
}

function updateRouteTitle() {
  const title = `${state.route.name} Segment Model`;
  els.routeTitle.textContent = title;
  document.title = title;
}

function syncWeatherControls() {
  const sample = nearestWeatherSampleForTime(null);
  if (!sample) {
    els.temperature.value = els.temperature.defaultValue;
    els.windDirection.value = els.windDirection.defaultValue;
    return;
  }
  els.temperature.value = Number(sample.temperature_c).toFixed(1);
  els.windDirection.value = normalizeDegrees(Number(sample.wind_direction_deg)).toFixed(0);
}

function parseGpx(text) {
  const xml = new DOMParser().parseFromString(text, "application/xml");
  const trkpts = [...xml.getElementsByTagNameNS("*", "trkpt")];
  if (trkpts.length < 2) throw new Error("GPX needs at least two track points");

  const points = trkpts.map(point => {
    const eleNode = point.getElementsByTagNameNS("*", "ele")[0];
    const timeNode = point.getElementsByTagNameNS("*", "time")[0];
    return {
      lat: Number(point.getAttribute("lat")),
      lon: Number(point.getAttribute("lon")),
      ele: eleNode ? Number(eleNode.textContent) : null,
      time: timeNode ? new Date(timeNode.textContent) : null,
      distance: 0
    };
  });

  const segments = [];
  let cumulative = 0;
  let ascent = 0;
  let descent = 0;

  for (let i = 0; i < points.length - 1; i += 1) {
    const start = points[i];
    const end = points[i + 1];
    const distanceM = haversine(start.lat, start.lon, end.lat, end.lon);
    if (distanceM <= 0) continue;
    const elevationDeltaM = end.ele !== null && start.ele !== null ? end.ele - start.ele : 0;
    const elapsedS = start.time && end.time ? (end.time - start.time) / 1000 : null;
    end.distance = cumulative + distanceM;
    cumulative += distanceM;
    ascent += Math.max(0, elevationDeltaM);
    descent += Math.abs(Math.min(0, elevationDeltaM));
    segments.push({
      startDistanceM: cumulative - distanceM,
      endDistanceM: cumulative,
      distanceM,
      elevationDeltaM,
      elapsedS,
      bearingDeg: bearing(start.lat, start.lon, end.lat, end.lon),
      start,
      end
    });
  }

  const elevations = points.map(point => point.ele).filter(value => value !== null);
  const startTime = points.find(point => point.time)?.time;
  const endTime = [...points].reverse().find(point => point.time)?.time;
  const durationS = startTime && endTime ? (endTime - startTime) / 1000 : null;

  return {
    points,
    segments,
    distanceM: cumulative,
    ascentM: ascent,
    descentM: descent,
    durationS,
    avgAltitudeM: average(elevations),
    minElevationM: Math.min(...elevations),
    maxElevationM: Math.max(...elevations)
  };
}

function render() {
  if (!state.route) return;
  normalizeSegments();
  renderActiveView();
  renderSegmentList();
  renderResults();
  updateInteractionState();
}

function renderActiveView() {
  renderChart();
  if (state.viewMode === "route3d") {
    render3dRoute();
  }
}

function normalizeSegments() {
  state.segments.sort((a, b) => a.start - b.start);
  state.segments[0].start = 0;
  state.segments[state.segments.length - 1].end = state.route.distanceM;
  for (let i = 0; i < state.segments.length - 1; i += 1) {
    const boundary = clamp(state.segments[i].end, state.segments[i].start + 10, state.segments[i + 1].end - 10);
    state.segments[i].end = boundary;
    state.segments[i + 1].start = boundary;
  }
  if (
    state.selectedBreakpointIndex !== null
    && (state.selectedBreakpointIndex <= 0 || state.selectedBreakpointIndex >= state.segments.length)
  ) {
    state.selectedBreakpointIndex = state.segments.length > 1 ? 1 : null;
  }
}

function renderChart() {
  const width = 980;
  const height = 440;
  const pad = { left: 54, right: 20, top: 28, bottom: 46 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const route = state.route;

  els.svg.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  const x = distance => pad.left + (distance / route.distanceM) * plotW;
  const y = ele => pad.top + (1 - (ele - route.minElevationM) / (route.maxElevationM - route.minElevationM)) * plotH;

  for (let i = 0; i <= 4; i += 1) {
    const yy = pad.top + (plotH / 4) * i;
    addLine(ns, yy, yy, pad.left, width - pad.right, "grid");
  }

  for (const segment of state.segments) {
    const info = protectionTypes[segment.type];
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("class", "segment-band");
    rect.setAttribute("x", x(segment.start));
    rect.setAttribute("y", pad.top);
    rect.setAttribute("width", Math.max(1, x(segment.end) - x(segment.start)));
    rect.setAttribute("height", plotH);
    rect.setAttribute("fill", info.color);
    els.svg.appendChild(rect);

    const label = document.createElementNS(ns, "text");
    label.setAttribute("class", "segment-label");
    label.setAttribute("x", x(segment.start) + 8);
    label.setAttribute("y", pad.top + 20);
    label.textContent = info.label;
    els.svg.appendChild(label);
  }

  const points = route.points.filter(point => point.ele !== null);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.distance).toFixed(2)} ${y(point.ele).toFixed(2)}`).join(" ");
  const area = `${path} L ${x(route.distanceM).toFixed(2)} ${height - pad.bottom} L ${pad.left} ${height - pad.bottom} Z`;
  const profile = document.createElementNS(ns, "path");
  profile.setAttribute("class", "profile");
  profile.setAttribute("d", area);
  els.svg.appendChild(profile);

  addLine(ns, height - pad.bottom, height - pad.bottom, pad.left, width - pad.right, "axis");
  addLine(ns, pad.top, height - pad.bottom, pad.left, pad.left, "axis");

  for (let i = 1; i < state.segments.length; i += 1) {
    const handleX = x(state.segments[i].start);
    const hit = document.createElementNS(ns, "rect");
    hit.setAttribute("class", "handle-hit");
    hit.setAttribute("x", handleX - 24);
    hit.setAttribute("y", pad.top);
    hit.setAttribute("width", 48);
    hit.setAttribute("height", plotH);
    hit.addEventListener("pointerdown", event => {
      state.draggingHandle = i;
      state.selectedBreakpointIndex = i;
      state.placingBreakpoint = false;
      updateInteractionState();
      event.preventDefault();
      event.stopPropagation();
    });
    els.svg.appendChild(hit);

    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", i === state.selectedBreakpointIndex ? "handle selected" : "handle");
    line.setAttribute("x1", handleX);
    line.setAttribute("x2", handleX);
    line.setAttribute("y1", pad.top);
    line.setAttribute("y2", height - pad.bottom);
    line.setAttribute("stroke", protectionTypes[state.segments[i].type].color);
    els.svg.appendChild(line);
  }

  addText(ns, pad.left, height - 16, "0 km");
  addText(ns, width - pad.right - 52, height - 16, `${(route.distanceM / 1000).toFixed(2)} km`);
  addText(ns, 10, pad.top + 4, `${route.maxElevationM.toFixed(0)} m`);
  addText(ns, 10, height - pad.bottom, `${route.minElevationM.toFixed(0)} m`);

  els.svg.onpointermove = event => updateCursorReadout(nearestRouteDistanceFrom2D(event.clientX));

  function addText(ns, tx, ty, text) {
    const node = document.createElementNS(ns, "text");
    node.setAttribute("x", tx);
    node.setAttribute("y", ty);
    node.setAttribute("font-size", "12");
    node.setAttribute("fill", "#9aa4b2");
    node.textContent = text;
    els.svg.appendChild(node);
  }

  function addLine(ns, y1, y2, x1, x2, className) {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", className);
    line.setAttribute("x1", x1);
    line.setAttribute("x2", x2);
    line.setAttribute("y1", y1);
    line.setAttribute("y2", y2);
    els.svg.appendChild(line);
  }
}

function renderSegmentList() {
  els.segmentList.innerHTML = "";
  state.segments.forEach((segment, index) => {
    const info = protectionTypes[segment.type];
    const row = document.createElement("div");
    row.className = index === state.selectedBreakpointIndex ? "segment-row selected" : "segment-row";
    row.addEventListener("click", () => {
      state.selectedBreakpointIndex = index;
      state.placingBreakpoint = false;
      render();
    });

    const swatch = document.createElement("div");
    swatch.className = "swatch";
    swatch.style.background = info.color;
    row.appendChild(swatch);

    const meta = document.createElement("div");
    meta.className = "segment-meta";
    const remainingStart = state.route.distanceM - segment.start;
    const remainingEnd = state.route.distanceM - segment.end;
    meta.innerHTML = `<strong>${meters(segment.end - segment.start)}</strong><span>${meters(remainingStart)} to ${meters(remainingEnd)} remaining</span>`;
    row.appendChild(meta);

    const select = document.createElement("select");
    for (const [type, typeInfo] of Object.entries(protectionTypes)) {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = typeInfo.label;
      option.selected = type === segment.type;
      select.appendChild(option);
    }
    select.addEventListener("change", () => {
      segment.type = select.value;
      render();
    });
    select.addEventListener("click", event => event.stopPropagation());
    row.appendChild(select);

    const remove = document.createElement("button");
    remove.textContent = "Del";
    remove.disabled = state.segments.length <= 1;
    remove.addEventListener("click", () => {
      removeSegment(index);
      render();
    });
    remove.addEventListener("click", event => event.stopPropagation());
    row.appendChild(remove);

    const controls = document.createElement("div");
    controls.className = "segment-controls";

    const startLabel = document.createElement("label");
    startLabel.textContent = "Start m";
    const startInput = document.createElement("input");
    startInput.type = "number";
    startInput.min = "0";
    startInput.step = "1";
    startInput.value = segment.start.toFixed(0);
    startInput.disabled = index === 0;
    startInput.addEventListener("change", () => {
      moveBreakpoint(index, Number(startInput.value));
      state.selectedBreakpointIndex = index;
      render();
    });
    startInput.addEventListener("click", event => event.stopPropagation());
    startLabel.appendChild(startInput);

    const remainingLabel = document.createElement("label");
    remainingLabel.textContent = "Remaining m";
    const remainingInput = document.createElement("input");
    remainingInput.type = "number";
    remainingInput.min = "0";
    remainingInput.step = "1";
    remainingInput.value = (state.route.distanceM - segment.start).toFixed(0);
    remainingInput.disabled = index === 0;
    remainingInput.addEventListener("change", () => {
      moveBreakpoint(index, state.route.distanceM - Number(remainingInput.value));
      state.selectedBreakpointIndex = index;
      render();
    });
    remainingInput.addEventListener("click", event => event.stopPropagation());
    remainingLabel.appendChild(remainingInput);

    controls.appendChild(startLabel);
    controls.appendChild(remainingLabel);
    row.appendChild(controls);

    els.segmentList.appendChild(row);
  });
}

function renderResults() {
  if (!state.route.durationS || state.route.durationS <= 0) {
    els.routeSummary.textContent = `${(state.route.distanceM / 1000).toFixed(2)} km, ${state.route.ascentM.toFixed(0)} m ascent, no timing data`;
    [
      els.wkg,
      els.power,
      els.aero,
      els.gradient,
      els.aslpPower,
      els.aslpWkg,
      els.standardWkg,
      els.vam,
      els.altitudeLoss,
      els.gravityPower,
      els.rollingPower,
      els.advancedAeroPower,
      els.stillAirAeroPower,
      els.windDeltaPower,
      els.headwindReadout,
      els.airDensity,
      els.tempReadout,
      els.windDirectionReadout,
      els.windSpeedReadout
    ].forEach(element => {
      element.textContent = "--";
    });
    els.weatherSource.textContent = weatherLabel();
    els.segmentBreakdown.innerHTML = "";
    return;
  }
  const result = calculatePower();
  els.routeSummary.textContent = `${(state.route.distanceM / 1000).toFixed(2)} km, ${state.route.ascentM.toFixed(0)} m ascent, ${formatTime(state.route.durationS)}`;
  els.wkg.textContent = result.wkg.toFixed(2);
  els.power.textContent = `${result.totalPowerW.toFixed(0)} W`;
  els.aero.textContent = `${result.aeroPowerW.toFixed(0)} W`;
  els.gradient.textContent = `${result.gradientPercent.toFixed(1)} %`;
  els.aslpPower.textContent = `${result.aslpPowerW.toFixed(0)} W`;
  els.aslpWkg.textContent = result.aslpWkg.toFixed(2);
  els.standardWkg.textContent = result.standard60Wkg.toFixed(2);
  els.vam.textContent = `${result.vam.toFixed(0)} m/h`;
  els.altitudeLoss.textContent = `${result.altitudeLossPercent.toFixed(1)} %`;
  els.gravityPower.textContent = `${result.gravityPowerW.toFixed(0)} W`;
  els.rollingPower.textContent = `${result.rollingPowerW.toFixed(0)} W`;
  els.advancedAeroPower.textContent = `${result.aeroPowerW.toFixed(0)} W`;
  els.stillAirAeroPower.textContent = `${result.stillAirAeroPowerW.toFixed(0)} W`;
  els.windDeltaPower.textContent = `${formatSigned(result.windDeltaPowerW.toFixed(0))} W`;
  els.headwindReadout.textContent = `${formatSigned(result.headwindMS.toFixed(2))} m/s`;
  els.airDensity.textContent = `${result.airDensityKgM3.toFixed(3)} kg/m3`;
  els.tempReadout.textContent = `${result.temperatureC.toFixed(1)} C`;
  els.windDirectionReadout.textContent = `${result.windDirectionDeg.toFixed(0)} deg`;
  els.windSpeedReadout.textContent = `${result.windSpeedMS.toFixed(2)} m/s`;
  els.weatherSource.textContent = result.weatherLabel;
  syncWeatherControlsFromResult(result);
  renderSegmentBreakdown(result.segmentStats);
  persistActiveScenario(result);
}

const persistActiveScenario = debounce(result => {
  if (!state.route) return;
  fetch(ACTIVE_SCENARIO_API, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(activeScenarioPayload(result))
  }).catch(() => {});
}, 300);

function activeScenarioPayload(result) {
  return {
    saved_at: new Date().toISOString(),
    route: {
      name: state.route.name,
      distance_m: state.route.distanceM,
      ascent_m: state.route.ascentM,
      duration_s: state.route.durationS,
      avg_altitude_m: state.route.avgAltitudeM
    },
    route_segments: state.route.segments.map(segment => ({
      start_distance_m: segment.startDistanceM,
      end_distance_m: segment.endDistanceM,
      distance_m: segment.distanceM,
      elevation_delta_m: segment.elevationDeltaM,
      elapsed_s: segment.elapsedS,
      bearing_deg: segment.bearingDeg,
      start_time: segment.startTime ? segment.startTime.toISOString() : null,
      end_time: segment.endTime ? segment.endTime.toISOString() : null,
      start_elevation_m: segment.startElevationM,
      end_elevation_m: segment.endElevationM
    })),
    weather: {
      status: state.route.weather.status,
      source: state.route.weather.source,
      samples: (state.route.weather.samples || []).map(sample => ({
        ...sample,
        time: sample.time instanceof Date ? sample.time.toISOString() : sample.time
      }))
    },
    assumptions: {
      rider_mass_kg: readNumber(els.riderMass),
      bike_mass_kg: readNumber(els.bikeMass),
      cda_m2: readNumber(els.cda),
      crr: readNumber(els.crr),
      temperature_c: readNumber(els.temperature),
      wind_direction_deg: readNumber(els.windDirection)
    },
    protection_types: protectionTypes,
    segments: state.segments.map(segment => {
      const typeInfo = protectionTypes[segment.type];
      return {
        type: segment.type,
        label: typeInfo.label,
        start_distance_m: segment.start,
        end_distance_m: segment.end,
        aero_multiplier: typeInfo.aeroMultiplier
      };
    }),
    result: result ? {
      total_power_w: result.totalPowerW,
      watts_per_kg: result.wkg,
      aslp_w_per_kg: result.aslpWkg,
      gravity_power_w: result.gravityPowerW,
      rolling_power_w: result.rollingPowerW,
      aero_power_w: result.aeroPowerW,
      headwind_m_s: result.headwindMS,
      air_density_kg_m3: result.airDensityKgM3
    } : null
  };
}

function syncWeatherControlsFromResult(result) {
  els.temperature.value = result.temperatureC.toFixed(1);
  els.windDirection.value = normalizeDegrees(result.windDirectionDeg).toFixed(0);
}

function calculatePower() {
  const route = state.route;
  const riderMass = readNumber(els.riderMass);
  const bikeMass = readNumber(els.bikeMass);
  const totalMass = riderMass + bikeMass;
  const standardRiderMass = 60;
  const standardTotalMass = standardRiderMass + bikeMass;
  const cda = readNumber(els.cda);
  const baseCrr = readNumber(els.crr);

  let gravityWork = 0;
  let rollingWork = 0;
  let aeroWork = 0;
  let stillAirAeroWork = 0;
  let propulsiveWork = 0;
  let standardPropulsiveWork = 0;
  let brakingWork = 0;
  let weatherWeightedTimeS = 0;
  let temperatureTimeSum = 0;
  let windSpeedTimeSum = 0;
  let windDirectionSinTimeSum = 0;
  let windDirectionCosTimeSum = 0;
  let headwindTimeSum = 0;
  let airDensityTimeSum = 0;
  const segmentStats = state.segments.map((segment, index) => ({
    index,
    type: segment.type,
    distanceM: segment.end - segment.start,
    ascentM: 0,
    descentM: 0,
    elevationChangeM: 0,
    timeS: 0,
    gravityWorkJ: 0,
    rollingWorkJ: 0,
    aeroWorkJ: 0,
    propulsiveWorkJ: 0,
    brakingWorkJ: 0
  }));

  for (const segment of route.segments) {
    if (!segment.elapsedS || segment.elapsedS <= 0) continue;
    const roadSpeed = segment.distanceM / segment.elapsedS;
    const sample = nearestWeatherSampleForSegment(segment);
    const temperatureC = sample ? Number(sample.temperature_c) : readNumber(els.temperature);
    const windSpeedMS = sample ? Number(sample.wind_speed_m_s) : 0;
    const windDirectionDeg = sample
      ? normalizeDegrees(Number(sample.wind_direction_deg))
      : normalizeDegrees(readNumber(els.windDirection));
    const headwindMS = sample
      ? windToComponents(windSpeedMS, windDirectionDeg, segment.bearingDeg).headwind
      : 0;
    const airSpeed = Math.max(0, roadSpeed + headwindMS);
    const segmentAltitudeM = average([
      segment.startElevationM,
      segment.endElevationM
    ].filter(value => value !== null && Number.isFinite(value)));
    const rho = airDensityAtAltitudeAndTemperature(
      Number.isFinite(segmentAltitudeM) ? segmentAltitudeM : route.avgAltitudeM,
      temperatureC
    );
    weatherWeightedTimeS += segment.elapsedS;
    temperatureTimeSum += temperatureC * segment.elapsedS;
    windSpeedTimeSum += windSpeedMS * segment.elapsedS;
    windDirectionSinTimeSum += Math.sin(radians(windDirectionDeg)) * segment.elapsedS;
    windDirectionCosTimeSum += Math.cos(radians(windDirectionDeg)) * segment.elapsedS;
    headwindTimeSum += headwindMS * segment.elapsedS;
    airDensityTimeSum += rho * segment.elapsedS;
    const slices = segmentSlices(segment);
    for (const slice of slices) {
      const fraction = slice.distanceM / segment.distanceM;
      const typeInfo = protectionTypes[slice.type];
      const timeS = segment.elapsedS * fraction;
      const elevationChangeM = segment.elevationDeltaM * fraction;
      const ascentM = Math.max(0, elevationChangeM);
      const descentM = Math.abs(Math.min(0, elevationChangeM));
      const gravitySlice = totalMass * G * elevationChangeM;
      const rollingSlice = baseCrr * totalMass * G * slice.distanceM;
      const aeroSlice = 0.5 * rho * cda * typeInfo.aeroMultiplier * Math.pow(airSpeed, 3) * timeS;
      const stillAirAeroSlice = 0.5 * rho * cda * typeInfo.aeroMultiplier * Math.pow(roadSpeed, 3) * timeS;
      const netSliceWork = gravitySlice + rollingSlice + aeroSlice;
      const propulsiveSlice = Math.max(0, netSliceWork);
      const brakingSlice = Math.max(0, -netSliceWork);
      const standardGravitySlice = standardTotalMass * G * elevationChangeM;
      const standardRollingSlice = baseCrr * standardTotalMass * G * slice.distanceM;
      const standardNetSliceWork = standardGravitySlice + standardRollingSlice + aeroSlice;
      const standardPropulsiveSlice = Math.max(0, standardNetSliceWork);

      gravityWork += gravitySlice;
      rollingWork += rollingSlice;
      aeroWork += aeroSlice;
      stillAirAeroWork += stillAirAeroSlice;
      propulsiveWork += propulsiveSlice;
      standardPropulsiveWork += standardPropulsiveSlice;
      brakingWork += brakingSlice;

      const stat = segmentStats[slice.overlayIndex];
      stat.ascentM += ascentM;
      stat.descentM += descentM;
      stat.elevationChangeM += elevationChangeM;
      stat.timeS += timeS;
      stat.gravityWorkJ += gravitySlice;
      stat.rollingWorkJ += rollingSlice;
      stat.aeroWorkJ += aeroSlice;
      stat.propulsiveWorkJ += propulsiveSlice;
      stat.brakingWorkJ += brakingSlice;
    }
  }

  const totalPowerW = propulsiveWork / route.durationS;
  const standard60PowerW = standardPropulsiveWork / route.durationS;
  const cpFraction = cpRemainingFractionAtAltitude(route.avgAltitudeM);
  const aslpPowerW = totalPowerW / cpFraction;
  const averageTemperatureC = weatherWeightedTimeS > 0
    ? temperatureTimeSum / weatherWeightedTimeS
    : readNumber(els.temperature);
  const averageWindSpeedMS = weatherWeightedTimeS > 0
    ? windSpeedTimeSum / weatherWeightedTimeS
    : 0;
  const averageWindDirectionDeg = weatherWeightedTimeS > 0
    ? weightedDirectionDegrees(windDirectionSinTimeSum, windDirectionCosTimeSum)
    : normalizeDegrees(readNumber(els.windDirection));
  const averageHeadwindMS = weatherWeightedTimeS > 0
    ? headwindTimeSum / weatherWeightedTimeS
    : 0;
  const averageAirDensity = weatherWeightedTimeS > 0
    ? airDensityTimeSum / weatherWeightedTimeS
    : airDensityAtAltitudeAndTemperature(route.avgAltitudeM, averageTemperatureC);
  return {
    totalPowerW,
    gravityPowerW: gravityWork / route.durationS,
    rollingPowerW: rollingWork / route.durationS,
    aeroPowerW: aeroWork / route.durationS,
    stillAirAeroPowerW: stillAirAeroWork / route.durationS,
    windDeltaPowerW: (aeroWork - stillAirAeroWork) / route.durationS,
    brakingPowerW: brakingWork / route.durationS,
    wkg: totalPowerW / riderMass,
    standard60Wkg: standard60PowerW / standardRiderMass,
    gradientPercent: route.ascentM / route.distanceM * 100,
    vam: route.ascentM / (route.durationS / 3600),
    aslpPowerW,
    aslpWkg: aslpPowerW / riderMass,
    altitudeLossPercent: (1 - cpFraction) * 100,
    airDensityKgM3: averageAirDensity,
    temperatureC: averageTemperatureC,
    windDirectionDeg: averageWindDirectionDeg,
    windSpeedMS: averageWindSpeedMS,
    headwindMS: averageHeadwindMS,
    weatherLabel: weatherLabel(),
    segmentStats: segmentStats.map(stat => ({
      ...stat,
      vam: stat.timeS > 0 ? stat.ascentM / (stat.timeS / 3600) : 0,
      gradientPercent: stat.distanceM > 0 ? stat.elevationChangeM / stat.distanceM * 100 : 0,
      totalPowerW: stat.timeS > 0 ? stat.propulsiveWorkJ / stat.timeS : 0,
      aeroPowerW: stat.timeS > 0 ? stat.aeroWorkJ / stat.timeS : 0
    }))
  };
}

function nearestWeatherSampleForSegment(segment) {
  if (!segment.startTime || !segment.endTime) return nearestWeatherSampleForTime(null);
  const midpointTime = new Date((segment.startTime.getTime() + segment.endTime.getTime()) / 2);
  return nearestWeatherSampleForTime(midpointTime);
}

function nearestWeatherSampleForTime(targetTime) {
  const samples = state.route && state.route.weather ? state.route.weather.samples : [];
  if (!samples || samples.length === 0) return null;
  if (!targetTime) return samples[0];

  return samples.reduce((nearest, sample) => {
    const nearestDelta = Math.abs(nearest.time.getTime() - targetTime.getTime());
    const sampleDelta = Math.abs(sample.time.getTime() - targetTime.getTime());
    return sampleDelta < nearestDelta ? sample : nearest;
  }, samples[0]);
}

function windToComponents(windSpeedMS, windDirectionDeg, riderHeadingDeg) {
  const windToDeg = (windDirectionDeg + 180) % 360;
  const relDeg = (windToDeg - riderHeadingDeg + 360) % 360;
  const relRad = radians(relDeg);
  const along = windSpeedMS * Math.cos(relRad);
  const across = windSpeedMS * Math.sin(relRad);
  return {
    headwind: -along,
    crosswind: Math.abs(across)
  };
}

function airDensityAtAltitudeAndTemperature(altitudeM, temperatureC) {
  const altitudeDensity = RHO0 * Math.exp(-Math.max(0, altitudeM || 0) / SCALE_HEIGHT_M);
  return altitudeDensity * (STANDARD_TEMP_K / (temperatureC + 273.15));
}

function weatherLabel() {
  const weather = state.route && state.route.weather ? state.route.weather : null;
  if (!weather) return "unavailable";
  if (weather.source) return `${weather.status} / ${weather.source}`;
  return weather.status || "unavailable";
}

function segmentSlices(routeSegment) {
  const slices = [];
  state.segments.forEach((overlay, overlayIndex) => {
    const start = Math.max(routeSegment.startDistanceM, overlay.start);
    const end = Math.min(routeSegment.endDistanceM, overlay.end);
    if (end > start) {
      slices.push({ distanceM: end - start, type: overlay.type, overlayIndex });
    }
  });
  return slices;
}

function renderSegmentBreakdown(segmentStats) {
  els.segmentBreakdown.innerHTML = "";
  segmentStats.forEach(stat => {
    const info = protectionTypes[stat.type];
    const row = document.createElement("div");
    row.className = "breakdown-row";
    row.innerHTML = `
      <strong>${info.label} · ${meters(stat.distanceM)}</strong>
      <div class="breakdown-metrics">
        <span>Grade ${stat.gradientPercent.toFixed(1)}%</span>
        <span>VAM ${stat.vam.toFixed(0)}</span>
        <span>Power ${stat.totalPowerW.toFixed(0)} W</span>
        <span>Aero ${stat.aeroPowerW.toFixed(0)} W</span>
        <span>Elev ${stat.elevationChangeM.toFixed(0)} m</span>
        <span>Ascent ${stat.ascentM.toFixed(0)} m</span>
        <span>Descent ${stat.descentM.toFixed(0)} m</span>
        <span>Time ${formatTime(stat.timeS)}</span>
      </div>
    `;
    els.segmentBreakdown.appendChild(row);
  });
}

function moveBreakpoint(index, distance) {
  if (index <= 0 || index >= state.segments.length) return;
  const minLength = minimumSegmentLength();
  const min = state.segments[index - 1].start + minLength;
  const max = state.segments[index].end - minLength;
  const value = clamp(distance, min, max);
  state.segments[index - 1].end = value;
  state.segments[index].start = value;
  state.selectedBreakpointIndex = index;
}

function removeSegment(index) {
  if (state.segments.length <= 1) return;
  if (index === 0) {
    state.segments[1].start = 0;
  } else {
    state.segments[index - 1].end = state.segments[index].end;
  }
  state.segments.splice(index, 1);
  state.selectedBreakpointIndex = state.segments.length > 1
    ? clamp(index, 1, state.segments.length - 1)
    : null;
}

function minimumSegmentLength() {
  return Math.min(10, Math.max(0.1, state.route.distanceM / 4));
}

function nearestRouteDistanceFrom2D(clientX) {
  const rect = els.svg.getBoundingClientRect();
  const x = ((clientX - rect.left) / rect.width) * 980;
  const padLeft = 54;
  const padRight = 20;
  const plotW = 980 - padLeft - padRight;
  return clamp(((x - padLeft) / plotW) * state.route.distanceM, 0, state.route.distanceM);
}

function selectOrInsertBreakpoint(distance) {
  if (state.placingBreakpoint) {
    insertBreakpointAtDistance(distance, nearestSegmentType(distance));
    state.placingBreakpoint = false;
    render();
    return;
  }

  const nearest = nearestBreakpointIndex(distance);
  if (nearest !== null) {
    state.selectedBreakpointIndex = nearest;
    updateCursorReadout(state.segments[nearest].start);
  } else {
    state.selectedBreakpointIndex = null;
    updateCursorReadout(distance);
  }
  render();
}

function insertBreakpointAtDistance(distance, defaultType) {
  const minLength = minimumSegmentLength();
  const segmentIndex = state.segments.findIndex(segment => (
    distance > segment.start + minLength && distance < segment.end - minLength
  ));
  if (segmentIndex < 0) return false;

  const segment = state.segments[segmentIndex];
  const split = clamp(distance, segment.start + minLength, segment.end - minLength);
  state.segments.splice(
    segmentIndex,
    1,
    { start: segment.start, end: split, type: segment.type },
    { start: split, end: segment.end, type: defaultType || segment.type }
  );
  state.selectedBreakpointIndex = segmentIndex + 1;
  return true;
}

function nearestSegmentType(distance) {
  const segment = state.segments.find(item => distance >= item.start && distance <= item.end);
  return segment ? segment.type : "solo";
}

function nearestBreakpointIndex(distance) {
  if (state.segments.length <= 1) return null;
  const threshold = Math.max(12, state.route.distanceM * 0.015);
  let best = null;
  let bestDelta = Infinity;
  for (let i = 1; i < state.segments.length; i += 1) {
    const delta = Math.abs(state.segments[i].start - distance);
    if (delta < bestDelta) {
      best = i;
      bestDelta = delta;
    }
  }
  return bestDelta <= threshold ? best : null;
}

function distanceToRoutePoint(distanceM) {
  if (!state.route || !state.route.points.length) return null;
  const distance = clamp(distanceM, 0, state.route.distanceM);
  for (let i = 1; i < state.route.points.length; i += 1) {
    const previous = state.route.points[i - 1];
    const current = state.route.points[i];
    if (current.distance >= distance) {
      const span = current.distance - previous.distance;
      const fraction = span > 0 ? (distance - previous.distance) / span : 0;
      return {
        lat: linearInterpolate(fraction, 0, previous.lat, 1, current.lat),
        lon: linearInterpolate(fraction, 0, previous.lon, 1, current.lon),
        ele: linearInterpolate(
          fraction,
          0,
          previous.ele ?? state.route.avgAltitudeM,
          1,
          current.ele ?? state.route.avgAltitudeM
        ),
        distance
      };
    }
  }
  return state.route.points[state.route.points.length - 1];
}

function updateInteractionState() {
  els.addBreakpoint.classList.toggle("active", state.placingBreakpoint);
  els.addBreakpoint.textContent = state.placingBreakpoint ? "Click Route" : "Add Breakpoint";
  els.profileViewButton.classList.toggle("active", state.viewMode === "profile");
  els.route3dViewButton.classList.toggle("active", state.viewMode === "route3d");
  els.profileView.classList.toggle("active", state.viewMode === "profile");
  els.route3dView.classList.toggle("active", state.viewMode === "route3d");
  if (state.placingBreakpoint) {
    els.cursorReadout.textContent = "Click the route to place a breakpoint.";
  }
}

function updateCursorReadout(distance) {
  if (distance === null || !Number.isFinite(distance) || !state.route) return;
  const point = distanceToRoutePoint(distance);
  const elevation = point && Number.isFinite(point.ele) ? `, ${point.ele.toFixed(0)} m` : "";
  els.cursorReadout.textContent = `${meters(distance)} from start, ${meters(state.route.distanceM - distance)} remaining${elevation}`;
}

function setViewMode(viewMode) {
  state.viewMode = viewMode;
  updateInteractionState();
  if (viewMode === "route3d") {
    init3dRoute();
    render3dRoute();
    resize3dRenderer();
  }
}

function init3dRoute() {
  if (!state.route || state.route3d.renderer) return;
  if (!window.THREE || !THREE.OrbitControls) {
    els.route3dStatus.textContent = "3D unavailable. Three.js CDN could not be loaded; 2D profile still works.";
    return;
  }

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  els.route3dView.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x121820);
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 100000);
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  const ambient = new THREE.AmbientLight(0xffffff, 0.78);
  scene.add(ambient);
  const light = new THREE.DirectionalLight(0xffffff, 0.72);
  light.position.set(200, 400, 300);
  scene.add(light);

  state.route3d.renderer = renderer;
  state.route3d.scene = scene;
  state.route3d.camera = camera;
  state.route3d.controls = controls;
  state.route3d.routeGroup = new THREE.Group();
  state.route3d.handleGroup = new THREE.Group();
  scene.add(state.route3d.routeGroup);
  scene.add(state.route3d.handleGroup);
  build3dPoints();
  reset3dCamera();
  animate3dRoute();
  els.route3dStatus.textContent = "";
  window.addEventListener("resize", resize3dRenderer);
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
  state.route3d = {
    renderer: null,
    scene: null,
    camera: null,
    controls: null,
    routeGroup: null,
    handleGroup: null,
    points3d: [],
    bounds: null,
    pointerDown: null,
    animationFrame: null
  };
  els.route3dStatus.textContent = "3D route loading";
}

function build3dPoints() {
  const route = state.route;
  if (!route || !route.points.length) return;
  const lat0 = route.points.reduce((sum, point) => sum + point.lat, 0) / route.points.length;
  const lon0 = route.points.reduce((sum, point) => sum + point.lon, 0) / route.points.length;
  const metersPerLat = 111320;
  const metersPerLon = 111320 * Math.cos(radians(lat0));
  const minEle = Number.isFinite(route.minElevationM) ? route.minElevationM : 0;
  const verticalScale = Math.max(1.5, Math.min(5, route.distanceM / Math.max(1, (route.maxElevationM - route.minElevationM) * 6)));

  state.route3d.points3d = route.points.map(point => ({
    distance: point.distance,
    x: (point.lon - lon0) * metersPerLon,
    y: ((point.ele ?? route.avgAltitudeM) - minEle) * verticalScale,
    z: -(point.lat - lat0) * metersPerLat
  }));

  const box = new THREE.Box3();
  for (const point of state.route3d.points3d) {
    box.expandByPoint(new THREE.Vector3(point.x, point.y, point.z));
  }
  state.route3d.bounds = box;
}

function render3dRoute() {
  if (!state.route || !state.route3d.renderer) return;
  clear3dGroup(state.route3d.routeGroup);
  clear3dGroup(state.route3d.handleGroup);
  render3dSegments();
  render3dBreakpoints();
  resize3dRenderer();
}

function render3dSegments() {
  for (const segment of state.segments) {
    const points = state.route3d.points3d
      .filter(point => point.distance >= segment.start && point.distance <= segment.end)
      .map(point => new THREE.Vector3(point.x, point.y, point.z));
    const startPoint = route3dPointAtDistance(segment.start);
    const endPoint = route3dPointAtDistance(segment.end);
    if (startPoint) points.unshift(startPoint);
    if (endPoint) points.push(endPoint);
    if (points.length < 2) continue;

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
      color: new THREE.Color(protectionTypes[segment.type].color),
      linewidth: 3
    });
    state.route3d.routeGroup.add(new THREE.Line(geometry, material));
  }
}

function render3dBreakpoints() {
  const markerGeometry = new THREE.SphereGeometry(8, 18, 18);
  for (let i = 1; i < state.segments.length; i += 1) {
    const point = route3dPointAtDistance(state.segments[i].start);
    if (!point) continue;
    const material = new THREE.MeshStandardMaterial({
      color: i === state.selectedBreakpointIndex ? 0x5f96ff : 0xf2f7ff,
      emissive: i === state.selectedBreakpointIndex ? 0x1b315e : 0x000000
    });
    const sphere = new THREE.Mesh(markerGeometry, material);
    sphere.position.copy(point);
    sphere.userData.breakpointIndex = i;
    state.route3d.handleGroup.add(sphere);
  }
}

function route3dPointAtDistance(distance) {
  const points = state.route3d.points3d;
  if (!points.length) return null;
  const clamped = clamp(distance, 0, state.route.distanceM);
  for (let i = 1; i < points.length; i += 1) {
    if (points[i].distance >= clamped) {
      const previous = points[i - 1];
      const current = points[i];
      const span = current.distance - previous.distance;
      const fraction = span > 0 ? (clamped - previous.distance) / span : 0;
      return new THREE.Vector3(
        linearInterpolate(fraction, 0, previous.x, 1, current.x),
        linearInterpolate(fraction, 0, previous.y, 1, current.y),
        linearInterpolate(fraction, 0, previous.z, 1, current.z)
      );
    }
  }
  const last = points[points.length - 1];
  return new THREE.Vector3(last.x, last.y, last.z);
}

function nearestRouteDistanceFrom3D(event) {
  if (!state.route3d.renderer || !state.route3d.points3d.length) return null;
  const rect = state.route3d.renderer.domElement.getBoundingClientRect();
  const mouseX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  const mouseY = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  let best = null;
  let bestDistance = Infinity;
  const projected = new THREE.Vector3();

  for (const point of state.route3d.points3d) {
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
  if (state.route3d.controls) {
    state.route3d.controls.target.copy(center);
    state.route3d.controls.update();
  }
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
  if (state.route3d.controls) {
    state.route3d.controls.update();
  }
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

function haversine(lat1, lon1, lat2, lon2) {
  const earthRadiusM = 6371000;
  const phi1 = radians(lat1);
  const phi2 = radians(lat2);
  const dPhi = radians(lat2 - lat1);
  const dLambda = radians(lon2 - lon1);
  const a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLambda / 2) ** 2;
  return 2 * earthRadiusM * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function bearing(lat1, lon1, lat2, lon2) {
  const phi1 = radians(lat1);
  const phi2 = radians(lat2);
  const dLambda = radians(lon2 - lon1);
  const x = Math.sin(dLambda) * Math.cos(phi2);
  const y = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLambda);
  return (degrees(Math.atan2(x, y)) + 360) % 360;
}

function cpRemainingFractionAtAltitude(avgAltitudeM) {
  const points = [
    [0.25, 1.0000],
    [1.25, 0.9518],
    [2.25, 0.8707],
    [3.25, 0.8062],
    [4.25, 0.7258]
  ];
  const x = Math.max(0, avgAltitudeM) / 1000;
  if (x <= points[0][0]) return 1.0;

  for (let i = 0; i < points.length - 1; i += 1) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    if (x >= x0 && x <= x1) {
      return linearInterpolate(x, x0, y0, x1, y1);
    }
  }

  const [x0, y0] = points[points.length - 2];
  const [x1, y1] = points[points.length - 1];
  return Math.max(0.5, linearInterpolate(x, x0, y0, x1, y1));
}

function linearInterpolate(x, x0, y0, x1, y1) {
  if (x1 === x0) return y0;
  return y0 + (y1 - y0) * ((x - x0) / (x1 - x0));
}

function normalizeDegrees(value) {
  return ((value % 360) + 360) % 360;
}

function weightedDirectionDegrees(sinSum, cosSum) {
  if (sinSum === 0 && cosSum === 0) return 0;
  return normalizeDegrees(degrees(Math.atan2(sinSum, cosSum)));
}

function readNumber(input) {
  return Number(input.value || 0);
}

function debounce(callback, delayMs) {
  let timeoutId = null;
  return (...args) => {
    window.clearTimeout(timeoutId);
    timeoutId = window.setTimeout(() => callback(...args), delayMs);
  };
}

function formatSigned(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number > 0 ? `+${value}` : `${value}`;
}

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function radians(value) {
  return value * Math.PI / 180;
}

function degrees(value) {
  return value * 180 / Math.PI;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function meters(value) {
  if (value >= 1000) return `${(value / 1000).toFixed(2)} km`;
  return `${value.toFixed(0)} m`;
}

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${rest}`;
}

function showError(message) {
  els.errorBox.textContent = message;
  els.errorBox.style.display = "block";
}