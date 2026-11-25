// Builds the ranking and the trip log for the 'Drivers and Trips' page
const TRIPS_PER_MONTH = 60;                  // same assumption as in 'trip cost'
const log = global.get('tripLog') || [];

const d = new Date();
const periods = {
  today: new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(),
  week:  Date.now() - 7 * 86400000,
  month: new Date(d.getFullYear(), d.getMonth(), 1).getTime(),
  all:   0
};

const ranking = {};
for (const key of Object.keys(periods)) {
  const by = {};
  log.forEach(t => {
    if (t.end * 1000 < periods[key]) return;
    const v = by[t.vid] = by[t.vid] || { vid: t.vid, trips: 0, scoreSum: 0, km: 0, events: 0, cost: 0 };
    v.trips++; v.scoreSum += t.score; v.km += t.distance; v.events += t.eventCount; v.cost += t.cost;
  });
  ranking[key] = Object.values(by).map(v => {
    const perTrip = v.cost / v.trips;
    return {
      vid: v.vid, trips: v.trips,
      avgScore: Math.round(v.scoreSum / v.trips),
      km: Math.round(v.km * 10) / 10,
      events: v.events,
      cost: Math.round(v.cost * 10) / 10,
      perTrip: Math.round(perTrip * 10) / 10,
      monthly: Math.round(perTrip * TRIPS_PER_MONTH)
    };
  }).sort((a, b) => b.avgScore - a.avgScore);
}

return { payload: { periods: periods, ranking: ranking, log: log.slice(-300).reverse(), total: log.length } };
