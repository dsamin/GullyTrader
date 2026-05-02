// GullyTrader — main app: hash router + shared phone shell.

const { useEffect, useState } = React;

const ROUTES = {
  '#/':           'home',
  '':             'home',
  '#/match':      'match',
  '#/trends':     'trends',
  '#/standings':  'table',
  '#/upcoming':   'table',
  '#/positions':  'you',
};

const SCREEN_FOR = {
  home:       'home',
  match:      'match',
  trends:     'trends',
  standings:  'standings',
  upcoming:   'upcoming',
  positions:  'positions',
};

function getRoute() {
  const h = window.location.hash || '#/';
  if (h === '#/' || h === '') return 'home';
  const slug = h.replace(/^#\//, '');
  return slug || 'home';
}

function App() {
  const [route, setRoute] = useState(getRoute());
  const [theme, setTheme] = useState(() => localStorage.getItem('gully:theme') || 'dark');
  const [bet, setBet] = useState(null);   // { market, side } | null
  const [data, setData] = useState({
    portfolio: null,
    positions: null,
    live: null,
    markets: null,
    fixtures: null,
    standings: null,
    bot: null,
    error: null,
  });

  // Hash routing
  useEffect(() => {
    const onHash = () => setRoute(getRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  // Theme toggle event (dispatched from dashboard moon icon)
  useEffect(() => {
    const onToggle = () => {
      setTheme(t => {
        const next = t === 'dark' ? 'light' : 'dark';
        localStorage.setItem('gully:theme', next);
        return next;
      });
    };
    window.addEventListener('gully:toggle-theme', onToggle);
    return () => window.removeEventListener('gully:toggle-theme', onToggle);
  }, []);

  // Bot toggle event
  useEffect(() => {
    const onBot = async () => {
      if (!data.bot) return;
      try {
        const next = await window.api.toggleBot(!data.bot.active);
        setData(d => ({ ...d, bot: { ...d.bot, active: next.active } }));
      } catch (e) { console.warn('bot toggle failed', e); }
    };
    window.addEventListener('gully:toggle-bot', onBot);
    return () => window.removeEventListener('gully:toggle-bot', onBot);
  }, [data.bot]);

  // Initial fetch
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [portfolio, positions, liveResp, fixtures, standings, bot] = await Promise.all([
          window.api.getPortfolio(),
          window.api.getPositions(),
          window.api.getLiveMatch(),
          window.api.getFixtures(),
          window.api.getStandings(),
          window.api.getBotStatus(),
        ]);
        const live = liveResp?.live || null;
        let markets = null;
        if (live) {
          try {
            const m = await window.api.getMatchMarkets(live.match_id);
            markets = m.markets;
          } catch (e) { /* tolerate */ }
        }
        if (!cancelled) {
          setData({
            portfolio, positions, live, markets,
            fixtures: fixtures.fixtures, standings: standings.rows, bot,
            error: null,
          });
        }
      } catch (e) {
        if (!cancelled) setData(d => ({ ...d, error: String(e) }));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Build live-strip preview from live match + first fixture
  const liveStrip = (() => {
    const out = [];
    if (data.live) {
      out.push({
        a: data.live.team_a, b: data.live.team_b,
        sa: `${data.live.runs_a}/${data.live.wickets_a}`,
        sb: `${data.live.runs_b}/${data.live.wickets_b}`,
        ov: `${data.live.overs_a}`,
        prob: data.live.win_probability_a,
        status: 'LIVE',
      });
    }
    if (data.fixtures && data.fixtures.length) {
      const f = data.fixtures[0];
      out.push({
        a: f.team_a, b: f.team_b, sa: '—', sb: '—',
        ov: new Date(f.start_time).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }),
        prob: null, status: 'TONIGHT',
      });
    }
    return out;
  })();

  const onOpenBet = (market, side) => setBet({ market, side });
  const onCloseBet = () => setBet(null);
  const onSubmitBet = async (order) => {
    try {
      await window.api.placeOrder(order);
      setBet(null);
    } catch (e) {
      console.warn('placeOrder failed', e);
      setBet(null);
    }
  };

  const activeTab = ROUTES[window.location.hash] || 'home';

  let screen = null;
  switch (route) {
    case 'home':
      screen = <Dashboard
        portfolio={data.portfolio}
        positions={data.positions}
        liveStrip={liveStrip}
        bot={data.bot}
      />; break;
    case 'match':
      screen = <MatchCentre
        live={data.live}
        markets={data.markets}
        positions={data.positions}
        onOpenBet={onOpenBet}
      />; break;
    case 'trends':
      screen = <Trends live={data.live}/>; break;
    case 'standings':
      screen = <Standings rows={data.standings}/>; break;
    case 'upcoming':
      screen = <Upcoming fixtures={data.fixtures}/>; break;
    case 'positions':
      screen = <Positions data={data.positions}/>; break;
    default:
      screen = <Dashboard portfolio={data.portfolio} positions={data.positions}
                 liveStrip={liveStrip} bot={data.bot}/>;
  }

  return (
    <>
      <div className="phone" data-theme={theme}>
        <div className="phone-stage">
          <div className="phone-scroll">
            <div className="phone-scroll-inner">
              {data.error && (
                <div style={{
                  background: 'var(--crimson-soft)',
                  border: '1px solid var(--crimson)',
                  color: 'var(--crimson)',
                  padding: 10, borderRadius: 10, marginBottom: 12,
                  fontSize: 12
                }}>
                  Backend error: {data.error}. Showing partial data.
                </div>
              )}
              {!data.portfolio && !data.error && (
                <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)' }}>
                  <div className="display" style={{ fontSize: 18, marginBottom: 6 }}>GullyTrader</div>
                  <div className="mono" style={{ fontSize: 12 }}>Loading…</div>
                </div>
              )}
              {data.portfolio && screen}
            </div>
          </div>
          <TabBar active={activeTab}/>
        </div>
      </div>
      {bet && (
        <BetSheet
          market={bet.market}
          defaultSide={bet.side}
          onClose={onCloseBet}
          onSubmit={onSubmitBet}
        />
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
