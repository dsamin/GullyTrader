// Standings & upcoming combined under "Table" tab.

const Standings = ({ rows }) => (
  <>
    <div className="between" style={{ marginBottom: 12 }}>
      <div>
        <div className="eyebrow">Standings</div>
        <div className="display" style={{ fontSize: 22, marginTop: 2 }}>Season '26</div>
      </div>
      <div className="segmented" style={{ transform: 'scale(0.85)', transformOrigin: 'right' }}>
        <div className="seg active">Table</div>
        <div className="seg" onClick={() => window.location.hash = '#/upcoming'}>Upcoming</div>
      </div>
    </div>

    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: '20px 1fr 24px 24px 24px 36px 50px',
        gap: 8, padding: '10px 12px',
        borderBottom: '1px solid var(--hairline)',
        fontFamily: 'JetBrains Mono', fontSize: 9,
        color: 'var(--muted)', letterSpacing: '0.06em'
      }}>
        <span>#</span><span>TEAM</span><span style={{textAlign:'center'}}>P</span>
        <span style={{textAlign:'center'}}>W</span><span style={{textAlign:'center'}}>L</span>
        <span style={{textAlign:'center'}}>NRR</span><span style={{textAlign:'right'}}>FORM</span>
      </div>
      {(rows || []).map((t, i) => {
        const inPlayoff = i < 4;
        return (
          <div key={t.code} style={{
            display: 'grid',
            gridTemplateColumns: '20px 1fr 24px 24px 24px 36px 50px',
            gap: 8, padding: '10px 12px',
            alignItems: 'center',
            borderBottom: i < (rows.length - 1) ? '1px solid var(--hairline)' : 'none',
            background: inPlayoff ? 'rgba(31, 174, 90, 0.04)' : 'transparent'
          }}>
            <span className="mono" style={{
              fontSize: 11,
              color: inPlayoff ? 'var(--pitch)' : 'var(--muted)',
              fontWeight: 700
            }}>{i+1}</span>
            <div className="row" style={{ gap: 8, minWidth: 0 }}>
              <TeamCrest code={t.code} size={22}/>
              <span className="display" style={{ fontSize: 12 }}>{t.code}</span>
            </div>
            <span className="mono" style={{ fontSize: 11, textAlign: 'center' }}>{t.played}</span>
            <span className="mono" style={{ fontSize: 11, textAlign: 'center', color: 'var(--pitch)' }}>{t.wins}</span>
            <span className="mono" style={{ fontSize: 11, textAlign: 'center', color: 'var(--crimson)' }}>{t.losses}</span>
            <span className="mono" style={{ fontSize: 10, textAlign: 'center',
              color: t.nrr.startsWith('+') ? 'var(--pitch)' : 'var(--crimson)' }}>{t.nrr}</span>
            <div className="row" style={{ gap: 2, justifyContent: 'flex-end' }}>
              {(t.last_5 || []).map((r, j) => (
                <div key={j} style={{
                  width: 8, height: 8, borderRadius: 99,
                  background: r === 'W' ? 'var(--pitch)' : 'var(--crimson)'
                }}/>
              ))}
            </div>
          </div>
        );
      })}
    </div>

    <div className="display" style={{ fontSize: 14, marginTop: 16, marginBottom: 8 }}>Playoff probability</div>
    <div className="card" style={{ padding: 14 }}>
      {(rows || []).slice(0, 6).map(t => (
        <div key={t.code} style={{ marginBottom: 10 }}>
          <div className="between" style={{ marginBottom: 4 }}>
            <div className="row" style={{ gap: 6 }}>
              <TeamCrest code={t.code} size={18}/>
              <span className="display" style={{ fontSize: 11 }}>{t.code}</span>
            </div>
            <span className="mono" style={{ fontSize: 11, fontWeight: 700,
              color: t.playoff_probability > 70 ? 'var(--pitch)'
                   : t.playoff_probability > 30 ? 'var(--gold)'
                   : 'var(--crimson)'
            }}>{t.playoff_probability}%</span>
          </div>
          <div className="slider-track">
            <div className="slider-fill" style={{
              width: `${t.playoff_probability}%`,
              background: t.playoff_probability > 70 ? 'var(--pitch)'
                        : t.playoff_probability > 30 ? 'var(--gold)'
                        : 'var(--crimson)'
            }}/>
          </div>
        </div>
      ))}
    </div>
  </>
);

const Upcoming = ({ fixtures }) => (
  <>
    <div className="between" style={{ marginBottom: 12 }}>
      <div>
        <div className="eyebrow">Upcoming</div>
        <div className="display" style={{ fontSize: 22, marginTop: 2 }}>{(fixtures || []).length} fixtures</div>
      </div>
      <div className="segmented" style={{ transform: 'scale(0.85)', transformOrigin: 'right' }}>
        <div className="seg" onClick={() => window.location.hash = '#/standings'}>Table</div>
        <div className="seg active">Upcoming</div>
      </div>
    </div>

    {(fixtures || []).map((f, i) => (
      <div key={i} className="card raised" style={{
        padding: 14, marginBottom: 10,
        position: 'relative', overflow: 'hidden'
      }}>
        {f.is_hot && (
          <div style={{
            position: 'absolute', top: 0, right: 0,
            background: 'var(--saffron)', color: '#0A0E1A',
            padding: '3px 10px', fontSize: 9, fontWeight: 700,
            fontFamily: 'JetBrains Mono', letterSpacing: '0.06em',
            borderBottomLeftRadius: 8
          }}>🔥 HOT</div>
        )}
        <div className="between" style={{ marginBottom: 12 }}>
          <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
            {new Date(f.start_time).toLocaleString(undefined, {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
            })}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 10 }}>
          <div className="col" style={{ alignItems: 'center', gap: 6 }}>
            <TeamCrest code={f.team_a} size={40}/>
            <span className="display" style={{ fontSize: 13, color: TEAMS[f.team_a]?.c1 || 'var(--text)' }}>{f.team_a}</span>
            <span className="mono" style={{ fontSize: 14, fontWeight: 700 }}>{f.expected_yes_a}¢</span>
          </div>
          <div className="display" style={{ fontSize: 13, color: 'var(--muted)' }}>VS</div>
          <div className="col" style={{ alignItems: 'center', gap: 6 }}>
            <TeamCrest code={f.team_b} size={40}/>
            <span className="display" style={{ fontSize: 13, color: TEAMS[f.team_b]?.c1 || 'var(--text)' }}>{f.team_b}</span>
            <span className="mono" style={{ fontSize: 14, fontWeight: 700 }}>{100 - f.expected_yes_a}¢</span>
          </div>
        </div>
        <div className="between" style={{ marginTop: 12 }}>
          <div className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>
            {f.venue} · {f.weather} · H2H {f.head_to_head}
          </div>
        </div>
      </div>
    ))}
  </>
);

Object.assign(window, { Standings, Upcoming });
