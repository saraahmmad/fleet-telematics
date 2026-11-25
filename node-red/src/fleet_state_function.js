// Keeps the latest state + short history of every vehicle and sends it to the dashboard
const OFFLINE_AFTER_MS = 6000;
const HIST = 120;                    // samples kept per vehicle (about 2 minutes)
let fleet = context.get('fleet') || {};
const p = msg.payload;

function get(vid) {
  return fleet[vid] = fleet[vid] || {
    vid: vid, speed: 0, fuel: 0, temp: 0, ign: 0, lastSeen: 0,
    lastEvent: '-', lastEventTs: 0, events: 0, recent: [],
    scoreSum: 0, trips: 0, lastScore: null, lastTrip: null,
    perTrip: null, monthly: null,
    hSpeed: [], hTemp: [], hFuel: []
  };
}
function push(arr, x) { arr.push(x); if (arr.length > HIST) arr.shift(); }
const pretty = (s) => String(s).replace(/_/g, ' ');

if (Array.isArray(p)) {                      // cost rows from 'trip cost'
  p.forEach(r => { const v = get(r.vid); v.perTrip = r.perTrip; v.monthly = r.monthly; });
} else if (p && typeof p === 'object' && p.vid) {
  const v = get(p.vid);
  if (p.type) {                              // event from 'detect events'
    v.lastEvent = p.type; v.lastEventTs = Date.now(); v.events++;
    v.recent.unshift({ type: p.type, value: p.value, ts: Date.now() });
    if (v.recent.length > 6) v.recent.pop();
  } else if (p.trip_id) {                    // trip summary from 'trip & score'
    v.lastScore = p.score; v.scoreSum += p.score; v.trips++;
    const ev = Object.keys(p.events || {}).map(k => pretty(k) + ' x' + p.events[k]).join(', ');
    v.lastTrip = {
      distance: p.distance_km, duration: p.duration_s, avgSpeed: p.avg_speed,
      maxSpeed: p.max_speed, score: p.score, rating: p.rating, events: ev || 'none'
    };
  } else if (p.speed !== undefined) {        // telemetry
    v.speed = p.speed; v.fuel = p.fuel; v.temp = p.temp; v.ign = p.ign;
    v.lastSeen = Date.now();
    push(v.hSpeed, p.speed); push(v.hTemp, p.temp); push(v.hFuel, p.fuel);
  }
}
context.set('fleet', fleet);

// ---- build the message for the dashboard ----
const now = Date.now();
const clamp = (x) => Math.max(0, Math.min(100, x));
// chart plot area inside an SVG of 320 x 120: x from 40 to 310, y from 10 (top) to 100 (bottom)
const X0 = 40, PW = 270, Y0 = 10, PH = 90;
function yOf(val, lo, hi) {
  return Y0 + PH - ((Math.max(lo, Math.min(hi, val)) - lo) / (hi - lo)) * PH;
}
function pts(arr, lo, hi) {                  // SVG polyline points, newest sample on the right
  return arr.map((y, i) => {
    const x = X0 + ((i + (HIST - arr.length)) / (HIST - 1)) * PW;
    return x.toFixed(1) + ',' + yOf(y, lo, hi).toFixed(1);
  }).join(' ');
}

const rows = Object.values(fleet).map(v => ({
  vid: v.vid,
  online: (now - v.lastSeen) < OFFLINE_AFTER_MS,
  ign: v.ign,
  speed: Math.round(v.speed),
  speedPct: clamp(v.speed / 120 * 100),
  fuel: Math.round(v.fuel),
  fuelPct: clamp(v.fuel),
  temp: Math.round(v.temp),
  lastEvent: v.lastEvent,
  eventAgoS: v.lastEventTs ? Math.round((now - v.lastEventTs) / 1000) : null,
  events: v.events,
  recent: v.recent.map(e => ({
    type: pretty(e.type),
    value: (typeof e.value === 'number') ? Math.round(e.value * 100) / 100 : e.value,
    agoS: Math.round((now - e.ts) / 1000)
  })),
  lastTrip: v.lastTrip,
  lastScore: v.lastScore,
  avgScore: v.trips ? Math.round(v.scoreSum / v.trips) : null,
  trips: v.trips,
  perTrip: v.perTrip,
  monthly: v.monthly,
  speedPts: pts(v.hSpeed, 0, 120),
  tempPts: pts(v.hTemp, 40, 130),
  fuelPts: pts(v.hFuel, 0, 100),
  tempLimitY: yOf(105, 40, 130).toFixed(1)
}));
rows.sort((a, b) => a.vid.localeCompare(b.vid));

const scored = rows.filter(r => r.avgScore !== null);
const summary = {
  total: rows.length,
  online: rows.filter(r => r.online).length,
  fleetAvg: scored.length ? Math.round(scored.reduce((s, r) => s + r.avgScore, 0) / scored.length) : null,
  atRisk: scored.filter(r => r.avgScore < 70).length
};
return { payload: { vehicles: rows, summary: summary } };
