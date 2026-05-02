// Trends & insights screen.
//
// Honest-dashboard rules: panels render only when backed by real data.
// Removed in Phase 5: hardcoded over-by-over runs/wickets, fake last-balls
// fallback, fake "win-prob through innings" SVG (both teams hardcoded
// at 100%), fake head-to-head "3 vs 2 wins", fake form guide W/L,
// fake pitch & weather text. To bring any of these back, build the
// matching /api endpoint first.

const Trends = ({ live }) => {
  const teamA = live?.team_a || '';
  const teamB = live?.team_b || '';

  const lastBalls = Array.isArray(live?.last_balls) ? live.last_balls : [];
  const recent = lastBalls
    .filter(b => /^[0-9W]/.test(b))
    .slice(-12)
    .map(b => b === 'W' ? 0 : parseInt(b, 10) || 0);
  const recentRuns = recent.reduce((s, r) => s + r, 0);
  const recentWkts = lastBalls.filter(b => b === 'W').length;

  const overs = Array.isArray(live?.over_runs) ? live.over_runs : [];
  const wicketOvers = Array.isArray(live?.wicket_overs) ? live.wicket_overs : [];

  if (!live) {
    return (
      <div className="card" style={{ padding: 20, textAlign: 'center' }}>
        <div className="display" style={{ fontSize: 14, marginBottom: 6 }}>No live match</div>
        <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
          Trends populate when a match is live.
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="between" style={{ marginBottom: 12 }}>
        <div>
          <div className="eyebrow">Trends</div>
          <div className="display" style={{ fontSize: 22, marginTop: 2 }}>
            {teamA} vs {teamB}
          </div>
        </div>
        <Chip variant="live"><span className="live-dot"/>LIVE</Chip>
      </div>

      {recent.length > 0 && (
        <div className="card raised" style={{ padding: 14, marginBottom: 10 }}>
          <div className="between" style={{ marginBottom: 8 }}>
            <div className="display" style={{ fontSize: 12 }}>Momentum (last 12 balls)</div>
            <span className="mono" style={{ fontSize: 11, color: 'var(--saffron)' }}>
              +{recentRuns} runs · {recentWkts} wkts
            </span>
          </div>
          <div className="row" style={{ gap: 3 }}>
            {recent.map((r, i) => {
              const h = 8 + r * 4;
              return (
                <div key={i} style={{ flex: 1, height: 48, display: 'flex', alignItems: 'flex-end' }}>
                  <div style={{
                    width: '100%', height: h,
                    background: r >= 4 ? 'var(--saffron)' : r >= 1 ? 'var(--pitch)' : 'var(--raised-2)',
                    borderRadius: 3
                  }}/>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {overs.length > 0 && (
        <div className="card" style={{ padding: 14, marginBottom: 10 }}>
          <div className="between" style={{ marginBottom: 6 }}>
            <div className="display" style={{ fontSize: 12 }}>Manhattan · {teamA}</div>
            <span className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>● wicket</span>
          </div>
          <Manhattan overs={overs} wickets={wicketOvers}/>
        </div>
      )}
    </>
  );
};

Object.assign(window, { Trends });
