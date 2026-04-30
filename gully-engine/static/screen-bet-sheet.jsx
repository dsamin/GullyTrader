// Bet placement sheet — modal overlay over match centre.

const { useState: useBetState } = React;

const BetSheet = ({ market, defaultSide = 'yes', onClose, onSubmit }) => {
  const [side, setSide] = useBetState(defaultSide);
  const [size, setSize] = useBetState(50);     // dollars
  const price = side === 'yes' ? market.yes : market.no;
  const contracts = Math.floor((size * 100) / Math.max(1, price));
  const cost = contracts * price;          // cents
  const maxPayout = contracts * 100;       // cents
  const maxLossCents = cost;
  const winPnlCents = maxPayout - cost;
  const winPct = maxLossCents > 0 ? (winPnlCents / maxLossCents) * 100 : 0;

  const submit = () => {
    onSubmit?.({
      ticker: market.ticker,
      side,
      action: 'buy',
      count: contracts,
      limit_price_cents: price,
    });
  };

  return (
    <div style={{
      position: 'fixed', inset: 0,
      background: 'rgba(0,0,0,0.55)',
      backdropFilter: 'blur(2px)',
      zIndex: 100,
      display: 'flex', alignItems: 'flex-end', justifyContent: 'center'
    }} onClick={onClose}>
      <div style={{
        width: '100%', maxWidth: 390,
        background: 'var(--surface)',
        borderTopLeftRadius: 28, borderTopRightRadius: 28,
        padding: '12px 18px 28px',
        border: '1px solid var(--hairline)',
        boxShadow: '0 -20px 60px rgba(0,0,0,0.5)',
        maxHeight: '90vh', overflow: 'auto'
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{
          width: 38, height: 4, borderRadius: 99,
          background: 'var(--hairline-strong)',
          margin: '4px auto 14px'
        }}/>

        <div className="between" style={{ marginBottom: 4 }}>
          <Chip variant="live"><span className="live-dot"/>LIVE</Chip>
          <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
            spread {Math.abs(market.yes + market.no - 100)}¢
          </span>
        </div>

        <div className="display" style={{ fontSize: 18, marginTop: 10, lineHeight: 1.2 }}>
          {market.title}
        </div>
        <div className="mono" style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
          settles end of match
        </div>

        <div className="row" style={{ gap: 8, marginTop: 16 }}>
          <button onClick={() => setSide('yes')} style={{
            flex: 1, padding: '16px',
            background: side === 'yes' ? 'rgba(31, 174, 90, 0.18)' : 'var(--raised)',
            border: side === 'yes' ? '2px solid var(--pitch)' : '1px solid var(--hairline)',
            borderRadius: 14, color: side === 'yes' ? 'var(--pitch)' : 'var(--muted)',
            display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center',
            cursor: 'pointer', fontFamily: 'inherit'
          }}>
            <span className="eyebrow" style={{ color: side === 'yes' ? 'var(--pitch)' : 'var(--muted)', fontSize: 9 }}>BUY YES</span>
            <span className="display" style={{ fontSize: 26 }}>{market.yes}¢</span>
          </button>
          <button onClick={() => setSide('no')} style={{
            flex: 1, padding: '16px',
            background: side === 'no' ? 'rgba(255, 71, 87, 0.18)' : 'var(--raised)',
            border: side === 'no' ? '2px solid var(--crimson)' : '1px solid var(--hairline)',
            borderRadius: 14, color: side === 'no' ? 'var(--crimson)' : 'var(--muted)',
            display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center',
            cursor: 'pointer', fontFamily: 'inherit'
          }}>
            <span className="eyebrow" style={{ color: side === 'no' ? 'var(--crimson)' : 'var(--muted)', fontSize: 9 }}>BUY NO</span>
            <span className="display" style={{ fontSize: 26 }}>{market.no}¢</span>
          </button>
        </div>

        <div style={{ marginTop: 18 }}>
          <div className="between" style={{ marginBottom: 8 }}>
            <div className="eyebrow">Position size</div>
            <div className="row" style={{ gap: 6 }}>
              <span className="mono" style={{ fontSize: 14, fontWeight: 700 }}>${size.toFixed(2)}</span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>· {contracts} ct</span>
            </div>
          </div>
          <input type="range" min={5} max={500} step={5} value={size}
            onChange={(e) => setSize(Number(e.target.value))}
            style={{ width: '100%' }}/>
          <div className="row" style={{ gap: 6, marginTop: 10 }}>
            {[25, 50, 100, 250].map(q => (
              <button key={q} className="btn btn-secondary" style={{
                flex: 1, padding: '7px 0', fontSize: 11,
                background: size === q ? 'var(--saffron)' : 'var(--raised)',
                color: size === q ? '#0A0E1A' : 'var(--text)',
                border: size === q ? 'none' : '1px solid var(--hairline)'
              }} onClick={() => setSize(q)}>${q}</button>
            ))}
          </div>
        </div>

        <div className="card raised" style={{ padding: 12, marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <div>
              <div className="eyebrow">Max payout</div>
              <div className="display" style={{ fontSize: 18, color: 'var(--pitch)', marginTop: 2 }}>
                ${(maxPayout/100).toFixed(0)}
              </div>
            </div>
            <div>
              <div className="eyebrow">Max loss</div>
              <div className="display" style={{ fontSize: 18, color: 'var(--crimson)', marginTop: 2 }}>
                ${(maxLossCents/100).toFixed(0)}
              </div>
            </div>
            <div>
              <div className="eyebrow">Breakeven</div>
              <div className="display" style={{ fontSize: 18, marginTop: 2 }}>{price}¢</div>
            </div>
          </div>
          <div className="divider"/>
          <div className="between">
            <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>
              If {side.toUpperCase()} wins
            </span>
            <span className="mono" style={{ fontSize: 12, color: 'var(--pitch)', fontWeight: 700 }}>
              +${(winPnlCents/100).toFixed(2)} (+{winPct.toFixed(0)}%)
            </span>
          </div>
        </div>

        <div className="row" style={{ gap: 8, marginTop: 16 }}>
          <button className="btn btn-secondary" style={{ flex: 1 }} onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" style={{ flex: 2 }} onClick={submit}>
            Place · {contracts} {side.toUpperCase()} @ {price}¢
          </button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { BetSheet });
