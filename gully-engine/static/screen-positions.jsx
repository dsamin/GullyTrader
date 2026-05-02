// Positions / history.

const Positions = ({ data }) => {
  const open = data?.open || [];
  const settled = data?.settled || [];
  const totals = data?.totals || { active_dollars: 0, today_pnl_cents: 0 };

  return (
    <>
      <div className="between" style={{ marginBottom: 12 }}>
        <div>
          <div className="eyebrow">Positions</div>
          <div className="display" style={{ fontSize: 22, marginTop: 2 }}>
            ${totals.active_dollars.toLocaleString('en-US', {maximumFractionDigits:0})} active
          </div>
        </div>
        <Chip variant={totals.today_pnl_cents >= 0 ? 'win' : 'loss'}>
          {totals.today_pnl_cents >= 0 ? '+' : '−'}${Math.abs(totals.today_pnl_cents/100).toFixed(2)}
        </Chip>
      </div>

      <div className="segmented" style={{ marginBottom: 12 }}>
        <div className="seg active">Open · {open.length}</div>
        <div className="seg">Settled · {settled.length}</div>
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 12, overflowX: 'auto' }}>
        {(() => {
          const matches = Array.from(new Set(open.map(p => p.match).filter(m => m && m !== '—')));
          const filters = ['All matches', ...matches, 'This week'];
          return filters.map((f, i) => (
            <span key={f} className="chip" style={{
              background: i === 0 ? 'var(--saffron)' : 'var(--raised)',
              color: i === 0 ? '#0A0E1A' : 'var(--text)',
              borderColor: i === 0 ? 'var(--saffron)' : 'var(--hairline)',
              flexShrink: 0
            }}>{f}</span>
          ));
        })()}
      </div>

      {open.map((p, i) => (
        <div key={i} className="card" style={{ padding: 14, marginBottom: 10 }}>
          <div className="between" style={{ marginBottom: 10 }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{p.title}</div>
              <div className="mono" style={{ fontSize: 10, color: 'var(--muted)', marginTop: 2 }}>{p.match}</div>
            </div>
            <Chip variant={p.exit_chip === 'TP near' ? 'win' : p.exit_chip === 'SL hit' ? 'loss' : 'pending'}>
              {p.exit_chip}
            </Chip>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginBottom: 10 }}>
            {[
              { l: 'Entry', v: `${p.entry_cents}¢` },
              { l: 'Mark', v: `${p.mark_cents}¢`,
                c: p.mark_cents > p.entry_cents ? 'var(--pitch)' : 'var(--crimson)' },
              { l: 'Size', v: `${p.contracts}` },
              { l: 'P&L', v: `${p.pnl_cents >= 0 ? '+' : '−'}$${Math.abs(p.pnl_cents/100).toFixed(2)}`,
                c: p.pnl_cents >= 0 ? 'var(--pitch)' : 'var(--crimson)' },
            ].map(s => (
              <div key={s.l}>
                <div className="eyebrow" style={{ fontSize: 8 }}>{s.l}</div>
                <div className="mono" style={{ fontSize: 13, fontWeight: 700, color: s.c || 'var(--text)' }}>{s.v}</div>
              </div>
            ))}
          </div>
          <div className="slider-track" style={{ height: 4 }}>
            <div style={{
              height: '100%', borderRadius: 99,
              width: `${p.mark_cents}%`,
              background: p.mark_cents > p.entry_cents ? 'var(--pitch)' : 'var(--crimson)'
            }}/>
          </div>
          <div className="between" style={{ marginTop: 6 }}>
            <span className="mono" style={{ fontSize: 9, color: 'var(--muted)' }}>0¢</span>
            <span className="mono" style={{ fontSize: 9, color: 'var(--saffron)' }}>↑ entry {p.entry_cents}¢</span>
            <span className="mono" style={{ fontSize: 9, color: 'var(--muted)' }}>100¢</span>
          </div>
        </div>
      ))}

      <div className="display" style={{ fontSize: 12, marginTop: 18, marginBottom: 8 }}>Recently settled</div>
      {settled.map((p, i) => (
        <div key={i} className="card" style={{ padding: 12, marginBottom: 8, opacity: 0.85 }}>
          <div className="between" style={{ marginBottom: 6 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{p.title}</div>
            <Chip variant={p.win ? 'win' : 'loss'}>{p.win ? '▲ WIN' : '▼ LOSS'}</Chip>
          </div>
          <div className="between">
            <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
              {p.entry_cents}¢ → {p.exit_cents}¢ · {p.contracts} ct · {p.reason}
            </div>
            <div className="display" style={{
              fontSize: 14,
              color: p.win ? 'var(--pitch)' : 'var(--crimson)'
            }}>
              {p.win ? '+' : '−'}${Math.abs(p.pnl_cents/100).toFixed(2)}
            </div>
          </div>
        </div>
      ))}
    </>
  );
};

Object.assign(window, { Positions });
