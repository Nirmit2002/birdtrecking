/**
 * app.js — MapLibre GL JS map initialisation and interaction logic.
 *
 * Map engine: MapLibre GL JS (open-source, no API key required)
 * Base tiles: CARTO Dark Matter (free, no token required)
 *
 * Layers:
 *   track-<bird>     — full trajectory LineString
 *   positions-<bird> — animated current position dot
 *   stopovers-layer  — yellow stop-over circles
 */

'use strict';

/* ── Bird metadata ─────────────────────────────────────────── */
const BIRD_META = {
  'Perneta_O285': { label: 'Perneta O285', color: '#00BCD4', cssClass: 'cyan' },
  'Castro_O284':  { label: 'Castro O284',  color: '#4CAF50', cssClass: 'green' },
  'Mineiro_O283': { label: 'Mineiro O283', color: '#E91E63', cssClass: 'pink' },
};

/* ── App state ─────────────────────────────────────────────── */
let map          = null;
let tracksData   = null;   // GeoJSON FeatureCollection
let stopoversData = null;
let statsData    = null;
let timelineData = null;   // flat array of point objects sorted by timestamp

let visibleBirds = { 'Perneta_O285': true, 'Castro_O284': true, 'Mineiro_O283': true };
let minTs        = 0;
let maxTs        = 0;
let currentTs    = 0;     // current timeline Unix timestamp
let isPlaying    = false;
let playSpeed    = 1;
let animFrameId  = null;
let lastFrameTime = null;

/* ── Initialise on DOM ready ───────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initMap();
});

/* ── Map setup ─────────────────────────────────────────────── */
function initMap() {
  map = new maplibregl.Map({
    container: 'map',
    style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
    center: [-8.014, 37.693],   // centre of actual data area (Alentejo, Portugal)
    zoom: 13,
    pitch: 25,
    bearing: 0,
    antialias: true,
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  map.addControl(new maplibregl.FullscreenControl(), 'top-right');

  map.on('load', async () => {
    await loadAllData();
    addMapLayers();
    applyLayerVisibility();
    updateMapLayers();
    renderBirdStatsPanel();
    renderLegend();
    fitMapToBirds();
  });
}

/* ── Data loading ──────────────────────────────────────────── */
async function loadAllData() {
  try {
    const [t, s, st, tl] = await Promise.all([
      fetch('/api/tracks').then(r => r.json()),
      fetch('/api/stopovers').then(r => r.json()),
      fetch('/api/stats').then(r => r.json()),
      fetch('/api/timeline').then(r => r.json()),
    ]);
    tracksData    = t;
    stopoversData = s;
    statsData     = st;
    timelineData  = tl;

    const timestamps = tl.map(p => p.timestamp);
    minTs    = Math.min(...timestamps);
    maxTs    = Math.max(...timestamps);
    currentTs = maxTs;   // start at end so full track is visible

    setupTimeline();
    initCharts(timelineData, visibleBirds);
    renderBirdStatsPanel();
  } catch (err) {
    console.error('[App] Data load error:', err);
  }
}

/* ── Map sources & layers ─────────────────────────────────── */
function addMapLayers() {
  if (!tracksData) return;

  // ── Full trajectory lines ──
  Object.keys(BIRD_META).forEach(bird => {
    const features = tracksData.features.filter(f => f.properties.bird_id === bird);
    const color    = BIRD_META[bird].color;

    map.addSource(`track-src-${bird}`, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features },
    });
    map.addLayer({
      id:   `track-${bird}`,
      type: 'line',
      source: `track-src-${bird}`,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint:  {
        'line-color':   ['match', ['get', 'segment_type'], 'stopped', '#FFC107', color],
        'line-width':   2,
        'line-opacity': 0.15,   // ghost background — trail draws on top brightly
      },
    });
  });

  // ── Animated trail (points up to currentTs) ──
  Object.keys(BIRD_META).forEach(bird => {
    const color = BIRD_META[bird].color;

    map.addSource(`trail-src-${bird}`, {
      type: 'geojson', data: { type: 'FeatureCollection', features: [] },
    });
    map.addLayer({
      id: `trail-${bird}`, type: 'line',
      source: `trail-src-${bird}`,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint:  {
        'line-color':   ['match', ['get', 'segment_type'], 'stopped', '#FFC107', color],
        'line-width':   5,
        'line-opacity': 1.0,    // fully opaque — clearly distinct from ghost background
      },
    });

    // Current position circle
    map.addSource(`pos-src-${bird}`, {
      type: 'geojson', data: { type: 'FeatureCollection', features: [] },
    });
    map.addLayer({
      id: `pos-halo-${bird}`, type: 'circle',
      source: `pos-src-${bird}`,
      paint: {
        'circle-radius': 22,
        'circle-color':  color,
        'circle-opacity': 0.30,
        'circle-stroke-width': 0,
        'circle-blur': 0.6,
      },
    });
    map.addLayer({
      id: `pos-dot-${bird}`, type: 'circle',
      source: `pos-src-${bird}`,
      paint: {
        'circle-radius': 10,
        'circle-color':  color,
        'circle-stroke-width': 3,
        'circle-stroke-color': '#ffffff',
        'circle-opacity': 1,
      },
    });

    // Click to inspect
    map.on('click', `pos-dot-${bird}`, e => {
      const props = e.features[0].properties;
      showPointInfo(props);
    });
    map.on('mouseenter', `pos-dot-${bird}`, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', `pos-dot-${bird}`, () => { map.getCanvas().style.cursor = ''; });
  });

  // ── Stop-over circles ──
  map.addSource('stopovers-src', {
    type: 'geojson',
    data: stopoversData || { type: 'FeatureCollection', features: [] },
  });
  map.addLayer({
    id: 'stopovers-halo', type: 'circle',
    source: 'stopovers-src',
    paint: {
      'circle-radius': 14, 'circle-color': '#888888',
      'circle-opacity': 0.15, 'circle-stroke-width': 0,
    },
  });
  map.addLayer({
    id: 'stopovers-layer', type: 'circle',
    source: 'stopovers-src',
    paint: {
      'circle-radius': 7, 'circle-color': '#999999',
      'circle-opacity': 0.9, 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff',
    },
  });
  map.on('click', 'stopovers-layer', e => {
    const p = e.features[0].properties;
    new maplibregl.Popup({ closeButton: false, offset: 14 })
      .setLngLat(e.lngLat)
      .setHTML(`
        <div style="font-size:13px;">
          <strong style="color:#cccccc;">⏸ Stop-over</strong><br>
          <span style="color:#8b949e;">Bird: ${p.bird_id}</span><br>
          Duration: <strong>${p.duration_h} h</strong><br>
          ${p.start_time} → ${p.end_time}
        </div>`)
      .addTo(map);
  });
}

/* ── Layer visibility (only call when toggling birds, not every frame) ── */
function applyLayerVisibility() {
  if (!map) return;
  const visibleBirdList = Object.keys(visibleBirds).filter(b => visibleBirds[b]);
  Object.keys(BIRD_META).forEach(bird => {
    const show = visibleBirds[bird];
    ['track', 'trail', 'pos-halo', 'pos-dot'].forEach(prefix => {
      if (map.getLayer(`${prefix}-${bird}`))
        map.setLayoutProperty(`${prefix}-${bird}`, 'visibility', show ? 'visible' : 'none');
    });
  });
  ['stopovers-layer', 'stopovers-halo'].forEach(id => {
    if (!map.getLayer(id)) return;
    map.setLayoutProperty(id, 'visibility', visibleBirdList.length ? 'visible' : 'none');
    map.setFilter(id, ['in', ['get', 'bird_id'], ['literal', visibleBirdList]]);
  });
}

/* ── Dynamic layer updates (called every animation frame) ─── */
function updateMapLayers() {
  if (!timelineData || !map) return;

  const visiblePoints = timelineData.filter(p => p.timestamp <= currentTs);

  Object.keys(BIRD_META).forEach(bird => {
    const show = visibleBirds[bird];
    if (!show) return;

    // Trail: ordered line from all points up to currentTs for this bird
    const bPoints = visiblePoints.filter(p => p.bird_id === bird);

    // Update trail source — one segment per point pair, colored by flying/stopped
    if (bPoints.length >= 2) {
      const segments = [];
      for (let i = 0; i < bPoints.length - 1; i++) {
        const p0 = bPoints[i];
        const p1 = bPoints[i + 1];
        const segType = parseFloat(p0.speed_kmh || 0) <= 1.0 ? 'stopped' : 'flying';
        segments.push({
          type: 'Feature',
          geometry: { type: 'LineString', coordinates: [[p0.lon, p0.lat], [p1.lon, p1.lat]] },
          properties: { segment_type: segType, bird_id: bird },
        });
      }
      map.getSource(`trail-src-${bird}`).setData({ type: 'FeatureCollection', features: segments });
    } else {
      map.getSource(`trail-src-${bird}`).setData({ type: 'FeatureCollection', features: [] });
    }

    // Current position
    const lastPt = bPoints.length > 0 ? bPoints[bPoints.length - 1] : null;
    if (lastPt) {
      const posFeature = {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lastPt.lon, lastPt.lat] },
        properties: { ...lastPt },
      };
      map.getSource(`pos-src-${bird}`).setData({ type: 'FeatureCollection', features: [posFeature] });
    } else {
      map.getSource(`pos-src-${bird}`).setData({ type: 'FeatureCollection', features: [] });
    }
  });
}

/* ── Bird toggles ─────────────────────────────────────────── */
function toggleBird(birdId) {
  visibleBirds[birdId] = !visibleBirds[birdId];
  const sw = document.getElementById(`toggle-${birdId}`);
  if (sw) sw.classList.toggle('active', visibleBirds[birdId]);
  applyLayerVisibility();
  updateMapLayers();
  updateCharts(timelineData, visibleBirds, currentTs);
}

/* ── Info panel ───────────────────────────────────────────── */
function showPointInfo(props) {
  const bird    = props.bird_id;
  const meta    = BIRD_META[bird] || {};
  const color   = meta.color || '#fff';
  const heading = parseFloat(props.heading || 0);
  const compass = degreesToCompass(heading);

  document.getElementById('point-info').innerHTML = `
    <div class="info-bird-header">
      <span class="dot dot-${meta.cssClass}"></span>
      <span class="info-bird-name" style="color:${color};">${bird.replace('_', ' ')}</span>
    </div>
    <div class="info-row"><span class="info-key">🕐 Date/Time</span>     <span class="info-value">${props.ts_label || '—'}</span></div>
    <div class="info-row"><span class="info-key">📍 Coordinates</span>   <span class="info-value">${parseFloat(props.lat).toFixed(4)}°, ${parseFloat(props.lon).toFixed(4)}°</span></div>
    <div class="info-row"><span class="info-key">⚡ Speed</span>         <span class="info-value">${parseFloat(props.speed_kmh || 0).toFixed(1)} km/h</span></div>
    <div class="info-row"><span class="info-key">🏔 Altitude</span>      <span class="info-value">${props.altitude_m} m</span></div>
    <div class="info-row"><span class="info-key">🧭 Heading</span>       <span class="info-value">${heading}° (${compass})</span></div>
    <div class="info-row"><span class="info-key">🔋 Battery</span>       <span class="info-value">${props.battery}%</span></div>
    <div class="info-row"><span class="info-key">📡 Satellites</span>    <span class="info-value">${props.satellites}</span></div>
    <div class="info-row"><span class="info-key">🌡 Temperature</span>   <span class="info-value">${props.temperature}°C</span></div>
  `;
}

function degreesToCompass(deg) {
  const dirs = ['N','NE','E','SE','S','SW','W','NW'];
  return dirs[Math.round(((deg % 360) / 45)) % 8];
}

/* ── Track color legend ───────────────────────────────────── */
function renderLegend() {
  const togglesEl = document.querySelector('.bird-toggles');
  if (!togglesEl || document.getElementById('track-legend')) return;
  const legend = document.createElement('div');
  legend.id = 'track-legend';
  legend.style.cssText = 'margin-top:10px;padding:8px 0 2px;border-top:1px solid #eeeeee;display:flex;flex-direction:column;gap:5px;';
  legend.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#666666;">
      <span style="display:inline-block;width:24px;height:3px;background:linear-gradient(90deg,#00BCD4 33%,#4CAF50 33%,#4CAF50 66%,#E91E63 66%);border-radius:2px;flex-shrink:0;"></span>
      <span>Flying (bird color)</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#666666;">
      <span style="display:inline-block;width:24px;height:3px;background:#FFC107;border-radius:2px;flex-shrink:0;"></span>
      <span>Stopped / Resting</span>
    </div>`;
  togglesEl.parentNode.appendChild(legend);
}

/* ── Bird stats panel (right sidebar) ────────────────────── */
function renderBirdStatsPanel() {
  const el = document.getElementById('bird-stats-panel');
  if (!el || !statsData) return;

  const colorMap = { 'Perneta_O285': 'cyan', 'Castro_O284': 'green', 'Mineiro_O283': 'pink' };
  let html = '';
  Object.entries(statsData.birds || {}).forEach(([bird, s]) => {
    html += `
      <div class="bs-card ${colorMap[bird] || ''}">
        <div class="bs-title">
          <span class="dot dot-${colorMap[bird]}"></span>
          ${bird.replace('_', ' ')}
        </div>
        <div class="bs-grid">
          <div class="bs-item"><div class="bs-item-val">${s.total_distance_km} km</div><div class="bs-item-lbl">Distance</div></div>
          <div class="bs-item"><div class="bs-item-val">${s.avg_speed_kmh} km/h</div><div class="bs-item-lbl">Avg Speed</div></div>
          <div class="bs-item"><div class="bs-item-val">${s.max_altitude_m} m</div><div class="bs-item-lbl">Max Alt.</div></div>
          <div class="bs-item"><div class="bs-item-val">${s.stopovers_count}</div><div class="bs-item-lbl">Stop-overs</div></div>
          <div class="bs-item"><div class="bs-item-val">${s.migration_days}d</div><div class="bs-item-lbl">Duration</div></div>
          <div class="bs-item"><div class="bs-item-val">${s.dominant_heading}</div><div class="bs-item-lbl">Heading</div></div>
        </div>
      </div>`;
  });
  el.innerHTML = html || '<div class="info-placeholder"><i class="fa-solid fa-circle-info"></i><p>No stats available.</p></div>';
}

/* ── Timeline ─────────────────────────────────────────────── */
function setupTimeline() {
  const slider = document.getElementById('timeline-slider');
  if (!slider) return;
  slider.min   = 0;
  slider.max   = 1000;
  slider.value = 1000;   // full timeline shown initially
  updateTimeLabel();
}

function onSliderChange(val) {
  const pct = val / 1000;
  currentTs  = Math.round(minTs + pct * (maxTs - minTs));
  updateTimeLabel();
  updateMapLayers();
  if (timelineData) updateCharts(timelineData, visibleBirds, currentTs);
}

function updateTimeLabel() {
  const label = document.getElementById('time-label');
  if (!label) return;
  const d = new Date(currentTs * 1000);
  label.textContent = d.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
}

function togglePlay() {
  isPlaying = !isPlaying;
  const icon = document.getElementById('play-icon');
  if (icon) {
    icon.classList.toggle('fa-play', !isPlaying);
    icon.classList.toggle('fa-pause', isPlaying);
  }
  if (isPlaying) {
    // If slider is at max, reset to start
    if (currentTs >= maxTs) { currentTs = minTs; }
    lastFrameTime = null;
    animFrameId = requestAnimationFrame(animStep);
  } else {
    if (animFrameId) cancelAnimationFrame(animFrameId);
  }
}

function animStep(now) {
  if (!isPlaying) return;
  if (lastFrameTime === null) { lastFrameTime = now; }

  const elapsed     = (now - lastFrameTime) / 1000;   // real seconds elapsed
  const dataSeconds = elapsed * playSpeed * 3600;      // 1 real sec = 1 data-hour at 1× speed
  lastFrameTime     = now;

  currentTs = Math.min(currentTs + dataSeconds, maxTs);

  // Update slider
  const slider = document.getElementById('timeline-slider');
  if (slider && maxTs > minTs) {
    slider.value = Math.round(((currentTs - minTs) / (maxTs - minTs)) * 1000);
  }

  updateTimeLabel();
  updateMapLayers();
  if (timelineData) updateCharts(timelineData, visibleBirds, currentTs);

  if (currentTs >= maxTs) {
    isPlaying = false;
    const icon = document.getElementById('play-icon');
    if (icon) { icon.classList.add('fa-play'); icon.classList.remove('fa-pause'); }
    return;
  }
  animFrameId = requestAnimationFrame(animStep);
}

function resetTimeline() {
  isPlaying = false;
  if (animFrameId) cancelAnimationFrame(animFrameId);
  const icon = document.getElementById('play-icon');
  if (icon) { icon.classList.add('fa-play'); icon.classList.remove('fa-pause'); }
  currentTs = minTs;
  const slider = document.getElementById('timeline-slider');
  if (slider) slider.value = 0;
  updateTimeLabel();
  updateMapLayers();
  if (timelineData) updateCharts(timelineData, visibleBirds, currentTs);
}

function setSpeed(val) {
  playSpeed = parseInt(val, 10);
}

/* ── Fit view ─────────────────────────────────────────────── */
function fitMapToBirds() {
  if (!timelineData || timelineData.length === 0) return;
  const lats = timelineData.map(p => p.lat);
  const lons = timelineData.map(p => p.lon);
  map.fitBounds(
    [[Math.min(...lons) - 0.04, Math.min(...lats) - 0.04],
     [Math.max(...lons) + 0.04, Math.max(...lats) + 0.04]],
    { padding: 60, duration: 1200, maxZoom: 14 }
  );
}
