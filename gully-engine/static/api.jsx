// Frontend API client — wraps fetch() against the FastAPI backend.

const api = {
  async _get(path) {
    const r = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  },

  async _post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  },

  getPortfolio: () => api._get('/api/portfolio'),
  getPositions: () => api._get('/api/positions'),
  getLiveMatch: () => api._get('/api/match/live'),
  getMatchMarkets: (matchId) => api._get(`/api/match/${matchId}/markets`),
  getFixtures: () => api._get('/api/fixtures'),
  getStandings: () => api._get('/api/standings'),
  getBotStatus: () => api._get('/api/bot/status'),

  toggleBot: (active) => api._post('/api/bot/toggle', { active }),
  placeOrder: (order) => api._post('/api/orders', order),
};

window.api = api;
