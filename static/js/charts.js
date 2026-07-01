/**
 * charts.js — Chart.js line graphs for speed and altitude over time.
 * Exported as module-level objects so app.js can call updateCharts().
 */

const BIRD_COLORS_HEX = {
  'Perneta_O285': '#111111',
  'Castro_O284':  '#555555',
  'Mineiro_O283': '#999999',
};

let speedChart   = null;
let altitudeChart = null;

/** Build a shared Chart.js options object for line graphs. */
function chartDefaults(title) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: { color: '#555555', font: { size: 10 }, boxWidth: 8, padding: 12 }
      },
      tooltip: {
        backgroundColor: '#ffffff',
        titleColor: '#111111',
        bodyColor: '#555555',
        borderColor: '#d8d8d8',
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        ticks: { color: '#888888', font: { size: 9 }, maxTicksLimit: 5 },
        grid:  { color: '#eeeeee' },
      },
      y: {
        ticks: { color: '#888888', font: { size: 9 } },
        grid:  { color: '#eeeeee' },
      },
    },
  };
}

/**
 * Initialise speed and altitude Chart.js instances.
 * @param {Array} timelineData  – all GPS points from /api/timeline
 * @param {Object} visibleBirds – { bird_id: true/false }
 */
function initCharts(timelineData, visibleBirds) {
  const speedCtx   = document.getElementById('speed-chart');
  const altCtx     = document.getElementById('altitude-chart');
  if (!speedCtx || !altCtx) return;

  const { speedDatasets, altDatasets, labels } = buildDatasets(timelineData, visibleBirds);

  speedChart = new Chart(speedCtx, {
    type: 'line',
    data: { labels, datasets: speedDatasets },
    options: chartDefaults('Speed'),
  });

  altitudeChart = new Chart(altCtx, {
    type: 'line',
    data: { labels, datasets: altDatasets },
    options: chartDefaults('Altitude'),
  });
}

/**
 * Rebuild chart datasets when bird visibility toggles or time filter changes.
 * @param {Array}  timelineData
 * @param {Object} visibleBirds
 * @param {number} [upToTimestamp]  – only show points up to this Unix timestamp
 */
function updateCharts(timelineData, visibleBirds, upToTimestamp) {
  if (!speedChart || !altitudeChart) return;

  const filtered = upToTimestamp != null
    ? timelineData.filter(p => p.timestamp <= upToTimestamp)
    : timelineData;

  const { speedDatasets, altDatasets, labels } = buildDatasets(filtered, visibleBirds);

  speedChart.data.labels   = labels;
  altitudeChart.data.labels = labels;
  speedChart.data.datasets   = speedDatasets;
  altitudeChart.data.datasets = altDatasets;
  speedChart.update('none');
  altitudeChart.update('none');
}

function buildDatasets(points, visibleBirds) {
  // Group by bird
  const byBird = {};
  points.forEach(p => {
    if (!byBird[p.bird_id]) byBird[p.bird_id] = [];
    byBird[p.bird_id].push(p);
  });

  // Shared labels: every unique ts_label in chronological order
  const labelSet = [...new Set(points.map(p => p.ts_label))].sort();

  const speedDatasets = [];
  const altDatasets   = [];

  Object.keys(BIRD_COLORS_HEX).forEach(bird => {
    if (!visibleBirds[bird]) return;
    const bPoints = byBird[bird] || [];

    // Map each label to a value (null if no data at that time for this bird)
    const bByLabel = {};
    bPoints.forEach(p => { bByLabel[p.ts_label] = p; });

    const speedVals = labelSet.map(l => bByLabel[l] ? bByLabel[l].speed_kmh : null);
    const altVals   = labelSet.map(l => bByLabel[l] ? bByLabel[l].altitude_m : null);
    const color     = BIRD_COLORS_HEX[bird];

    speedDatasets.push({
      label: bird.replace('_', ' '),
      data: speedVals,
      borderColor: color,
      backgroundColor: color + '18',
      borderWidth: 1.5,
      pointRadius: 2,
      tension: 0.3,
      spanGaps: true,
    });

    altDatasets.push({
      label: bird.replace('_', ' '),
      data: altVals,
      borderColor: color,
      backgroundColor: color + '18',
      borderWidth: 1.5,
      pointRadius: 2,
      tension: 0.3,
      fill: true,
      spanGaps: true,
    });
  });

  return { speedDatasets, altDatasets, labels: labelSet };
}
