// Match centre — live match command center.

const PlayerCard = ({ name, runs, balls, sr, onStrike, role = "BAT" }) => (
  <div className="card" style={{
    padding: 10, flex: 1,
    border: onStrike ? '1px solid rgba(255, 133, 51, 0.45)' : '1px solid var(--hairline)',
    background: onStrike ? 'rgba(255, 133, 51, 0.06)' : 'var(--surface)'
  }}>
    <div className="between" style={{ marginBottom: 6 }}>
      <div className="row" style={{ gap: 4 }}>
        {onStrike && <span style={{ color: 'var(--saffron)', fontSize: 11 }}>●</span>}
        <span style={{ fontSize: 12, fontWeight: 600 }}>{name}</span>
      </div>
      <span className="mono" style={{ fontSize: 9, color: 'var(--muted)' }}>{role}</span>
    </div>
    <div className="row" style={{ gap: 12, alignItems: 'baseline' }}>
      <div className="display" style={{ fontSize: 20 }}>
        {runs}{balls && <span style={{ color: 'var(--muted)', fontSize: 11 }}> ({balls})</span>}
      </div>
      <div>
        <div className="eyebrow" style={{ fontSize: 8 }}>{role === 'BAT' ? 'SR' : 'ECON'}</div>
        <div className="mono" style={{ fontSize: 11, fontWeight: 600 }}>{sr}</div>
      </div>
    </div>
  </div>
);

const MarketRow = ({ market, onOpenBet }) => (
  <div className="card" style={{ padding: 12, marginBottom: 8 }}>
    <div className="between" style={{ marginBottom: 8 }}>
      <div className="row" style={{ gap: 6 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>{market.title}</span>
        {market.hot && <Chip variant="gold" style={{ fontSize: 9, padding: '2px 6px' }}>HOT</Chip>}
        {market.you_in && <Chip variant="win" style={{ fontSize: 9, padding: '2px 6px' }}>YOU IN</Chip>}
      </div>
    </div>
    <div className="row" style={{ gap: 6 }}>
      <button onClick={() => onOpenBet(market, 'yes')} style={{
        flex: 1, padding: '10px',
        background: 'rgba(31, 174, 90, 0.12)',
        border: '1px solid rgba(31, 174, 90, 0.3)',
        borderRadius: 10, color: 'var(--pitch)',
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        cursor: 'pointer', fontFamily: 'inherit'
      }}>
        <span className="eyebrow" style={{ color: 'var(--pitch)', opacity: 0.8, fontSize: 9 }}>YES</span>
        <span className="mono" style={{ fontSize: 16, fontWeight: 700 }}>{market.yes}¢</span>
      </button>
      <button onClick={() => onOpenBet(market, 'no')} style={{
        flex: 1, padding: '10px',
        background: 'rgba(255, 71, 87, 0.10)',
        border: '1px solid rgba(255, 71, 87, 0.28)',
        borderRadius: 10, color: 'var(--crimson)',
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        cursor: 'pointer', fontFamily: 'inherit'
      }}>
        <span className="eyebrow" style={{ color: 'var(--crimson)', opacity: 0.8, fontSize: 9 }}>NO</span>
        <span className="mono" style={{ fontSize: 16, fontWeight: 700 }}>{market.no}¢</span>
      </button>
    </div>
  </div>
);

const MatchCentre = ({ live, markets, onOpenBet, positions }) => {
  if (!live) {
    return (
      <div style={{ padding: '40px 0', textAlign: 'center' }}>
        <div className="display" style={{ fontSize: 18, marginBottom: 8 }}>No live match</div>
        <div className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
          Check back when an IPL fixture is in progress.
        </div>
        <button className="btn btn-secondary" style={{ marginTop: 18 }}
          onClick={() => window.location.hash = '#/upcoming'}>
          See upcoming fixtures
        </button>
      </div>
    );
  }

  // Reconstruct worm-graph data from live state (best-effort approximation)
  const overs = 20;
  const liveOver = parseFloat(live.overs_a) || 0;
  const liveOverIdx = Math.floor(liveOver) + (liveOver % 1 > 0 ? 1 : 0);
  const mumWorm = Array.from({ length: liveOverIdx + 1 }, (_, i) =>
    Math.round((live.runs_a / Math.max(1, liveOverIdx)) * i));
  const cheWorm = Array.from({ length: overs + 1 }, (_, i) =>
    Math.round((live.runs_b / overs) * i));

  const positionsOnMatch = (positions?.open || []).filter(p =>
    p.match && (p.match.includes(live.team_a) && p.match.includes(live.team_b))
  );
  const matchPnl = positionsOnMatch.reduce((s, p) => s + p.pnl_cents, 0);

  return (
    <>
      <div className="between" style={{ marginBottom: 12 }}>
        <div className="row" style={{ gap: 8 }}>
          <button style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--raised)',
            display: 'grid', placeItems: 'center', border: 'none', color: 'var(--text)', cursor: 'pointer' }}
            onClick={() => window.location.hash = '#/'}>‹</button>
          <div>
            <div className="eyebrow">Match · IPL '26</div>
            <div className="display" style={{ fontSize: 14 }}>
              {(TEAMS[live.team_a]?.name || live.team_a)} v {(TEAMS[live.team_b]?.name || live.team_b)}
            </div>
          </div>
        </div>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--raised)',
          display: 'grid', placeItems: 'center' }}>⋯</div>
      </div>

      <Scoreboard
        teamA={live.team_a} teamB={live.team_b}
        runsA={live.runs_a} wicketsA={live.wickets_a} oversA={live.overs_a}
        runsB={live.runs_b} wicketsB={live.wickets_b} oversB={live.overs_b}
        status={live.status_text}
      />

      <div className="card" style={{ padding: 14, marginTop: 12 }}>
        <div className="between" style={{ marginBottom: 10 }}>
          <div className="display" style={{ fontSize: 12 }}>Win probability</div>
          <span className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>updated 0.4s ago</span>
        </div>
        <WinProbRibbon
          a={live.win_probability_a} b={100 - (live.win_probability_a || 50)}
          codeA={live.team_a} codeB={live.team_b}
          colorA={TEAMS[live.team_a]?.c1 || 'var(--saffron)'}
          colorB={TEAMS[live.team_b]?.c1 || 'var(--gold)'}
        />
      </div>

      <div className="segmented" style={{ marginTop: 14, marginBottom: 12 }}>
        <div className="seg active">Live</div>
        <div className="seg">Markets</div>
        <div className="seg" onClick={() => window.location.hash = '#/trends'}>Trends</div>
      </div>

      <div className="card" style={{ padding: 14, marginBottom: 10 }}>
        <div className="between" style={{ marginBottom: 8 }}>
          <div className="display" style={{ fontSize: 12 }}>Run worm</div>
          <div className="row" style={{ gap: 8, fontSize: 10 }}>
            <span className="row" style={{ gap: 4 }}>
              <span style={{ width: 8, height: 2, background: '#FF8533', display: 'inline-block' }}/>
              <span className="mono" style={{ color: 'var(--muted)' }}>{live.team_a}</span>
            </span>
            <span className="row" style={{ gap: 4 }}>
              <span style={{ width: 8, height: 2, background: '#FFD93D', display: 'inline-block' }}/>
              <span className="mono" style={{ color: 'var(--muted)' }}>{live.team_b}</span>
            </span>
          </div>
        </div>
        <WormGraph teamA={mumWorm} teamB={cheWorm} target={live.target || live.runs_b} overs={20}/>
      </div>

      <div className="card" style={{ padding: 12, marginBottom: 10 }}>
        <div className="between" style={{ marginBottom: 6 }}>
          <div className="eyebrow">This over · {live.overs_a}</div>
          {live.bowler && (
            <span className="mono" style={{ fontSize: 11, color: 'var(--text)' }}>
              {live.bowler.name} → {live.on_strike_batter?.name}
            </span>
          )}
        </div>
        <BallByBall balls={live.last_balls || []}/>
      </div>

      {(live.on_strike_batter || live.non_strike_batter) && (
        <div className="row" style={{ gap: 8, marginBottom: 10 }}>
          {live.on_strike_batter && (
            <PlayerCard {...live.on_strike_batter} onStrike role="BAT"/>
          )}
          {live.non_strike_batter && (
            <PlayerCard {...live.non_strike_batter} role="BAT"/>
          )}
        </div>
      )}
      {live.bowler && (
        <PlayerCard
          name={live.bowler.name}
          runs={`${live.bowler.overs}-0-${live.bowler.runs}-${live.bowler.wickets}`}
          balls=""
          sr={live.bowler.economy}
          role="BOWL"
        />
      )}

      <div className="between" style={{ marginTop: 16, marginBottom: 8 }}>
        <div className="display" style={{ fontSize: 14 }}>
          Live markets <span style={{ color: 'var(--muted)', fontSize: 12 }}>· {markets?.length || 0}</span>
        </div>
      </div>

      {(markets || []).map((m, i) => (
        <MarketRow key={i} market={m} onOpenBet={onOpenBet}/>
      ))}

      {positionsOnMatch.length > 0 && (
        <div className="card raised" style={{
          padding: 14, marginTop: 12,
          background: matchPnl >= 0 ? 'rgba(31, 174, 90, 0.06)' : 'rgba(255, 71, 87, 0.06)',
          border: matchPnl >= 0 ? '1px solid rgba(31, 174, 90, 0.18)' : '1px solid rgba(255, 71, 87, 0.18)'
        }}>
          <div className="between" style={{ marginBottom: 10 }}>
            <div className="display" style={{ fontSize: 13 }}>Your positions on this match</div>
            <Chip variant={matchPnl >= 0 ? 'win' : 'loss'}>
              {matchPnl >= 0 ? '+' : '−'}${Math.abs(matchPnl/100).toFixed(2)}
            </Chip>
          </div>
          {positionsOnMatch.map((p, i) => (
            <React.Fragment key={i}>
              {i > 0 && <div className="divider"/>}
              <div className="between" style={{ fontSize: 12 }}>
                <span>{p.title} · {p.contracts} ct @ {p.entry_cents}¢</span>
                <span className="mono" style={{ color: p.pnl_cents >= 0 ? 'var(--pitch)' : 'var(--crimson)' }}>
                  {p.pnl_cents >= 0 ? '+' : '−'}${Math.abs(p.pnl_cents/100).toFixed(2)}
                </span>
              </div>
            </React.Fragment>
          ))}
        </div>
      )}
    </>
  );
};

Object.assign(window, { MatchCentre });
