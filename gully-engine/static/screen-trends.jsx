// Trends & insights screen.

const Trends = ({ live }) => {
  const overs = [8, 12, 4, 16, 9, 18, 7, 11, 14, 6, 10, 13, 17, 9, 8, 12];
  const wickets = [3, 7, 12];
  const teamA = live?.team_a || 'MUM';
  const teamB = live?.team_b || 'CHE';
  const recent = (live?.last_balls || ['1','4','0','6','2','1','0','4','1','2','6','1'])
    .filter(b => /^[0-9W]/.test(b))
    .slice(-12)
    .map(b => b === 'W' ? 0 : parseInt(b, 10) || 0);
  const recentRuns = recent.reduce((s, r) => s + r, 0);
  const recentWkts = (live?.last_balls || []).filter(b => b === 'W').length;

  return (
    <>
      <div className="between" style={{ marginBottom: 12 }}>
        <div>
          <div className="eyebrow">Trends</div>
          <div className="display" style={{ fontSize: 22, marginTop: 2 }}>
            {teamA} vs {teamB}
          </div>
        </div>
        {live && <Chip variant="live"><span className="live-dot"/>LIVE</Chip>}
      </div>

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

      <div className="card" style={{ padding: 14, marginBottom: 10 }}>
        <div className="display" style={{ fontSize: 12, marginBottom: 8 }}>Win-prob thru innings</div>
        <svg width="100%" height="80" viewBox="0 0 320 80" preserveAspectRatio="none">
          <defs>
            <linearGradient id="wp-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#FF8533" stopOpacity="0.4"/>
              <stop offset="100%" stopColor="#FF8533" stopOpacity="0"/>
            </linearGradient>
          </defs>
          <line x1="0" x2="320" y1="40" y2="40" stroke="var(--hairline)" strokeDasharray="2 3"/>
          <text x="6" y="14" fontSize="9" fontFamily="JetBrains Mono" fill="#2E4FFF">{teamA} 100%</text>
          <text x="6" y="78" fontSize="9" fontFamily="JetBrains Mono" fill="#FFD93D">{teamB} 100%</text>
          <path d="M0 50 L40 48 L80 52 L120 45 L160 38 L200 30 L240 25 L280 20 L320 18"
            fill="none" stroke="#FF8533" strokeWidth="2.5"/>
          <path d="M0 50 L40 48 L80 52 L120 45 L160 38 L200 30 L240 25 L280 20 L320 18 L320 80 L0 80 Z"
            fill="url(#wp-fill)" opacity="0.5"/>
          <circle cx="320" cy="18" r="4" fill="#FF8533"/>
        </svg>
      </div>

      <div className="card" style={{ padding: 14, marginBottom: 10 }}>
        <div className="between" style={{ marginBottom: 6 }}>
          <div className="display" style={{ fontSize: 12 }}>Manhattan · {teamA}</div>
          <span className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>● wicket</span>
        </div>
        <Manhattan overs={overs} wickets={wickets}/>
      </div>

      <div className="card" style={{ padding: 14, marginBottom: 10 }}>
        <div className="display" style={{ fontSize: 12, marginBottom: 10 }}>Head-to-head · last 5</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 8, alignItems: 'center' }}>
          <div className="col" style={{ alignItems: 'center', gap: 6 }}>
            <TeamCrest code={teamA} size={32}/>
            <div className="display" style={{ fontSize: 28 }}>3</div>
            <div className="eyebrow">wins</div>
          </div>
          <div className="col" style={{ gap: 4, alignItems: 'center' }}>
            {['2024','2023','2022','2021','2020'].map(y => (
              <span key={y} className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>{y}</span>
            ))}
          </div>
          <div className="col" style={{ alignItems: 'center', gap: 6 }}>
            <TeamCrest code={teamB} size={32}/>
            <div className="display" style={{ fontSize: 28 }}>2</div>
            <div className="eyebrow">wins</div>
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 14, marginBottom: 10 }}>
        <div className="display" style={{ fontSize: 12, marginBottom: 10 }}>Form guide</div>
        {[
          { code: teamA, form: ['W','W','L','W','W'] },
          { code: teamB, form: ['L','W','W','L','W'] },
        ].map(t => (
          <div key={t.code} className="between" style={{ marginBottom: 8 }}>
            <div className="row" style={{ gap: 8 }}>
              <TeamCrest code={t.code} size={26}/>
              <span className="display" style={{ fontSize: 13 }}>{TEAMS[t.code]?.name || t.code}</span>
            </div>
            <div className="row" style={{ gap: 4 }}>
              {t.form.map((r, i) => (
                <div key={i} style={{
                  width: 18, height: 18, borderRadius: 99,
                  background: r === 'W' ? 'var(--pitch)' : 'var(--crimson)',
                  color: '#0A0E1A',
                  display: 'grid', placeItems: 'center',
                  fontSize: 9, fontWeight: 700
                }}>{r}</div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="row" style={{ gap: 8 }}>
        <div className="card" style={{ padding: 12, flex: 1 }}>
          <div className="eyebrow">Pitch</div>
          <div className="display" style={{ fontSize: 16, marginTop: 4 }}>Batting</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>Avg 1st-inn 184</div>
          <div className="row" style={{ gap: 2, marginTop: 8 }}>
            {[1,1,1,1,0].map((on, i) => (
              <div key={i} style={{
                flex: 1, height: 4, borderRadius: 2,
                background: on ? 'var(--saffron)' : 'var(--raised-2)'
              }}/>
            ))}
          </div>
        </div>
        <div className="card" style={{ padding: 12, flex: 1 }}>
          <div className="eyebrow">Weather</div>
          <div className="display" style={{ fontSize: 16, marginTop: 4 }}>28°C</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>Humid · Dew @ 19:00</div>
          <div className="mono" style={{ fontSize: 10, color: 'var(--gold)', marginTop: 8 }}>⚡ Favors chasing side</div>
        </div>
      </div>
    </>
  );
};

Object.assign(window, { Trends });
