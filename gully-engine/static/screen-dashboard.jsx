// Dashboard home — portfolio command center.

const PortfolioHero_A = ({ value, dayPct, dayAbs, sparkData, ringRoi, ringWin, ringWagered, statRoi, statWin, statWagered }) => (
  <div className="card raised pitch-noise" style={{ padding: 16, position: 'relative', overflow: 'hidden' }}>
    <div className="pitch-grain" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.7 }}/>
    <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, position: 'relative', zIndex: 1 }}>
      <div>
        <div className="eyebrow">Portfolio value</div>
        <div className="huge" style={{ marginTop: 4 }}>
          <span style={{ color: 'var(--muted)', fontSize: 30 }}>$</span>
          <span className="glow-pitch">{value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
        </div>
        <div className="row" style={{ gap: 8, marginTop: 6 }}>
          <Delta v={dayPct}/>
          <span className="mono" style={{ color: 'var(--muted)', fontSize: 12 }}>+${dayAbs.toFixed(2)} today</span>
        </div>
      </div>
      <div style={{ alignSelf: 'center' }}>
        <PortfolioRing roi={ringRoi} win={ringWin} wagered={ringWagered} size={108}/>
      </div>
    </div>
    <div style={{ marginTop: 10 }}>
      <Sparkline data={sparkData} w={342} h={42}/>
    </div>
    <div className="between" style={{ marginTop: 10, position: 'relative', zIndex: 1 }}>
      {[
        { l: 'ROI', v: statRoi, c: 'var(--saffron)' },
        { l: 'Win rate', v: statWin, c: 'var(--pitch)' },
        { l: 'Wagered', v: statWagered, c: 'var(--gold)' },
      ].map(s => (
        <div key={s.l}>
          <div className="eyebrow">{s.l}</div>
          <div className="display" style={{ fontSize: 16, color: s.c, marginTop: 2 }}>{s.v}</div>
        </div>
      ))}
    </div>
  </div>
);

const LiveMatchStrip = ({ matches }) => (
  <div style={{ display: 'flex', gap: 10, overflowX: 'auto', padding: '4px 0' }}>
    {matches.map((m, i) => (
      <button key={i} className="card" style={{
        minWidth: 220, flexShrink: 0,
        padding: 12, textAlign: 'left', cursor: 'pointer',
        border: m.status === 'LIVE' ? '1px solid rgba(255, 71, 87, 0.3)' : '1px solid var(--hairline)',
        background: 'var(--surface)', color: 'var(--text)', fontFamily: 'inherit'
      }} onClick={() => { window.location.hash = '#/match'; }}>
        <div className="between" style={{ marginBottom: 8 }}>
          {m.status === 'LIVE'
            ? <span className="chip chip-live"><span className="live-dot"/>LIVE</span>
            : <span className="chip">{m.status}</span>}
          <span className="mono" style={{ fontSize: 10, color: 'var(--muted)' }}>{m.ov}</span>
        </div>
        <div className="between">
          <div className="row" style={{ gap: 8 }}>
            <TeamCrest code={m.a} size={26}/>
            <div className="display" style={{ fontSize: 13 }}>{m.a}</div>
            <div className="mono" style={{ fontSize: 13, color: 'var(--muted)' }}>{m.sa}</div>
          </div>
        </div>
        <div className="between" style={{ marginTop: 4 }}>
          <div className="row" style={{ gap: 8 }}>
            <TeamCrest code={m.b} size={26}/>
            <div className="display" style={{ fontSize: 13 }}>{m.b}</div>
            <div className="mono" style={{ fontSize: 13, color: 'var(--muted)' }}>{m.sb}</div>
          </div>
        </div>
        {m.prob !== null && m.prob !== undefined && (
          <div style={{ marginTop: 10 }}>
            <div className="ribbon" style={{ height: 6 }}>
              <div style={{ width: `${m.prob}%`, background: TEAMS[m.a]?.c1 || 'var(--saffron)' }}/>
              <div style={{ width: `${100-m.prob}%`, background: TEAMS[m.b]?.c1 || 'var(--gold)' }}/>
            </div>
            <div className="between" style={{ marginTop: 4 }}>
              <span className="mono" style={{ fontSize: 10, color: TEAMS[m.a]?.c1 }}>{m.prob}¢</span>
              <span className="mono" style={{ fontSize: 10, color: TEAMS[m.b]?.c1 }}>{100-m.prob}¢</span>
            </div>
          </div>
        )}
      </button>
    ))}
  </div>
);

const DashPositionRow = ({ market, entry, mark, contracts, pnl, badge }) => {
  const pos = pnl >= 0;
  return (
    <div className="card" style={{ padding: 12, marginBottom: 8 }}>
      <div className="between" style={{ marginBottom: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', flex: 1 }}>{market}</div>
        {badge && <Chip variant={badge.variant}>{badge.text}</Chip>}
      </div>
      <div className="between">
        <div className="row" style={{ gap: 14 }}>
          <div>
            <div className="eyebrow">Entry</div>
            <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{entry}¢</div>
          </div>
          <div>
            <div className="eyebrow">Mark</div>
            <div className="mono" style={{ fontSize: 13, fontWeight: 600,
              color: mark > entry ? 'var(--pitch)' : (mark < entry ? 'var(--crimson)' : 'var(--text)')
            }}>{mark}¢</div>
          </div>
          <div>
            <div className="eyebrow">Size</div>
            <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{contracts}</div>
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="display" style={{ fontSize: 17, color: pos ? 'var(--pitch)' : 'var(--crimson)' }}>
            {pos ? '▲' : '▼'} {pos ? '+' : '−'}${Math.abs(pnl).toFixed(2)}
          </div>
        </div>
      </div>
    </div>
  );
};

const Dashboard = ({ portfolio, positions, liveStrip, bot }) => {
  const sparkData = portfolio?.spark_20d || [];
  const value = (portfolio?.portfolio_value_cents || 0) / 100;
  const dayPct = portfolio?.day_pnl_pct || 0;
  const dayAbs = (portfolio?.day_pnl_abs_cents || 0) / 100;
  const ringRoi = Math.min(100, Math.max(0, portfolio?.roi_pct || 0));
  const ringWin = portfolio?.win_rate_pct || 0;
  const wagered = (portfolio?.wagered_cents || 0) / 100;
  const exposure = (portfolio?.exposure_cents || 0) / 100;
  const ringWagered = Math.min(100, (wagered / Math.max(1, value)) * 100);
  const last10 = portfolio?.streak_last_10 || [];

  return (
    <>
      <div className="between" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 10 }}>
          <Avatar initials="AR"/>
          <div>
            <div style={{ fontSize: 12, color: 'var(--muted)' }}>Welcome back</div>
            <div className="display" style={{ fontSize: 16 }}>Arjun</div>
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button className="btn btn-secondary" style={{ padding: '8px 12px', fontSize: 12 }}>+ Funds</button>
          <button style={{
            width: 36, height: 36, borderRadius: 99,
            background: 'var(--raised)',
            display: 'grid', placeItems: 'center',
            border: '1px solid var(--hairline)',
            color: 'var(--text)', cursor: 'pointer'
          }} onClick={() => window.dispatchEvent(new CustomEvent('gully:toggle-theme'))} aria-label="Toggle theme">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      </div>

      <PortfolioHero_A
        value={value}
        dayPct={dayPct}
        dayAbs={dayAbs}
        sparkData={sparkData}
        ringRoi={ringRoi}
        ringWin={ringWin}
        ringWagered={ringWagered}
        statRoi={`+${(portfolio?.roi_pct || 0).toFixed(1)}%`}
        statWin={`${ringWin}%`}
        statWagered={`$${wagered.toLocaleString('en-US')}`}
      />

      {/* Bot status pill */}
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div className="between">
          <div className="row" style={{ gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: bot?.active ? 'rgba(31, 174, 90, 0.14)' : 'rgba(139, 146, 168, 0.14)',
              display: 'grid', placeItems: 'center'
            }}>
              <span className="live-dot" style={{
                background: bot?.active ? 'var(--pitch)' : 'var(--muted)',
                boxShadow: bot?.active ? '0 0 10px var(--pitch)' : 'none'
              }}/>
            </div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                Autotrader · {bot?.active ? 'Active' : 'Paused'}
                {bot?.mode === 'shadow' && <span style={{ color: 'var(--gold)', marginLeft: 6, fontSize: 11 }}>· shadow</span>}
              </div>
              <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
                {bot?.last_action ? `Last: ${bot.last_action} · ${bot.last_action_seconds_ago}s ago` : 'Waiting for next pass'}
              </div>
            </div>
          </div>
          <div className={`toggle ${bot?.active ? 'on' : ''}`}
               onClick={() => window.dispatchEvent(new CustomEvent('gully:toggle-bot'))}/>
        </div>
      </div>

      {/* Live now strip */}
      <div className="between" style={{ marginTop: 16, marginBottom: 8 }}>
        <div className="display" style={{ fontSize: 14 }}>Live now</div>
        <button className="row" style={{
          gap: 4, background: 'transparent', border: 'none', color: 'var(--muted)', cursor: 'pointer'
        }} onClick={() => window.location.hash = '#/match'}>
          <span className="mono" style={{ fontSize: 11 }}>See all</span>
          <span>›</span>
        </button>
      </div>
      <LiveMatchStrip matches={liveStrip}/>

      {/* Open positions */}
      <div className="between" style={{ marginTop: 16, marginBottom: 8 }}>
        <div className="display" style={{ fontSize: 14 }}>
          Open positions <span style={{ color: 'var(--muted)', fontSize: 12 }}>· {positions?.open?.length || 0}</span>
        </div>
        <button className="row" style={{
          gap: 4, background: 'transparent', border: 'none', color: 'var(--muted)', cursor: 'pointer'
        }} onClick={() => window.location.hash = '#/positions'}>
          <span className="mono" style={{ fontSize: 11 }}>See all</span>
          <span>›</span>
        </button>
      </div>

      {(positions?.open || []).slice(0, 3).map((p, i) => (
        <DashPositionRow
          key={i}
          market={p.title}
          entry={p.entry_cents}
          mark={p.mark_cents}
          contracts={p.contracts}
          pnl={p.pnl_cents / 100}
          badge={{
            variant: p.exit_chip === 'TP near' ? 'win' : p.exit_chip === 'SL hit' ? 'loss' : 'pending',
            text: p.exit_chip
          }}
        />
      ))}

      {/* Streak / health */}
      <div className="card" style={{ padding: 14, marginTop: 12 }}>
        <div className="between" style={{ marginBottom: 10 }}>
          <div className="display" style={{ fontSize: 13 }}>Streak & health</div>
          <Chip variant="gold">🔥 HOT</Chip>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div>
            <div className="eyebrow">Last 10</div>
            <div className="row" style={{ gap: 3, marginTop: 6 }}>
              {last10.map((r, i) => (
                <div key={i} style={{
                  width: 18, height: 18, borderRadius: 4,
                  background: r === 'W' ? 'var(--pitch)' : 'var(--crimson)',
                  color: '#0A0E1A',
                  display: 'grid', placeItems: 'center',
                  fontSize: 9, fontWeight: 700
                }}>{r}</div>
              ))}
            </div>
          </div>
          <div>
            <div className="eyebrow">Exposure</div>
            <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>
              ${exposure.toFixed(0)} <span style={{ fontSize: 11, color: 'var(--muted)' }}>/ {value.toLocaleString('en-US', {maximumFractionDigits:0})}</span>
            </div>
            <div className="slider-track" style={{ marginTop: 6 }}>
              <div className="slider-fill" style={{
                width: `${Math.min(100, (exposure/Math.max(1,value))*100)}%`,
                background: 'var(--pitch)'
              }}/>
            </div>
          </div>
        </div>
      </div>
    </>
  );
};

Object.assign(window, { Dashboard });
