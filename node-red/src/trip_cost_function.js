// Replaces the code of the existing 'trip cost' node.
// For every finished trip: computes the extra cost, saves the trip in a log, and
// sends per-vehicle averages (all trips) to 'fleet state'.
const p = msg.payload;
if (!p || !p.trip_id) return null;

// ===== ASSUMPTIONS: replace with sourced values and cite them in the report =====
const FUEL_PRICE = 20.5;          // EGP per liter (diesel, Oct 2026: see report references)
const IDLE_L_PER_MIN = 0.015;     // liters per minute of idling (example)
const COST = { HARSH_BRAKING: 3, HARSH_ACCELERATION: 2, SHARP_CORNERING: 1.5, ENGINE_OVERHEAT: 50 }; // EGP per event (example)
const OVERSPEED_EGP_PER_MIN = 1.0; // extra fuel while speeding (example)
const TRIPS_PER_MONTH = 60;       // trips per vehicle per month (example)
const MAX_LOG = 5000;             // trips kept in the log

const e = p.events || {};
let cost = 0, eventCount = 0;
for (const k in COST) cost += (e[k] || 0) * COST[k];
for (const k in e) eventCount += e[k];
cost += (p.overspeed_min || 0) * OVERSPEED_EGP_PER_MIN;
cost += (p.idle_min || 0) * IDLE_L_PER_MIN * FUEL_PRICE;

const endSec = (p.end > 1.7e9) ? p.end : Math.round(Date.now() / 1000);
const entry = {
  vid: p.vid, end: endSec, duration: p.duration_s, distance: p.distance_km,
  avgSpeed: p.avg_speed, maxSpeed: p.max_speed, score: p.score, rating: p.rating,
  events: Object.keys(e).map(k => k.replace(/_/g, ' ') + ' x' + e[k]).join(', ') || 'none',
  eventCount: eventCount,
  cost: Math.round(cost * 10) / 10
};

let log = global.get('tripLog') || [];
log.push(entry);
if (log.length > MAX_LOG) log = log.slice(-MAX_LOG);
global.set('tripLog', log);

// averages per vehicle over the whole log
const by = {};
log.forEach(t => {
  const v = by[t.vid] = by[t.vid] || { vid: t.vid, cost: 0, trips: 0 };
  v.cost += t.cost; v.trips++;
});
const rows = Object.values(by).map(v => {
  const perTrip = v.cost / v.trips;
  return { vid: v.vid, perTrip: Math.round(perTrip * 10) / 10,
           monthly: Math.round(perTrip * TRIPS_PER_MONTH), trips: v.trips };
});
rows.sort((a, b) => b.perTrip - a.perTrip);
return { payload: rows };
