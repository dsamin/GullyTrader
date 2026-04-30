// Cricket-specific chart components — pure SVG, no deps.

const Sparkline = ({ data, w = 120, h = 36, stroke = "var(--pitch)", fill = true }) => {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const stepX = w / (data.length - 1);
  const pts = data.map((v, i) => [i * stepX, h - ((v - min) / range) * (h - 4) - 2]);
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `${d} L${w} ${h} L0 ${h} Z`;
  const id = `sl-${Math.random().toString(36).slice(2,7)}`;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.35"/>
          <stop offset="100%" stopColor={stroke} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${id})`}/>}
      <path d={d} fill="none" stroke={stroke} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="2.5" fill={stroke}/>
    </svg>
  );
};

const WinProbRibbon = ({ a = 62, b = 38, codeA = "MUM", codeB = "CHE", colorA = "#FF8533", colorB = "#FFD93D" }) => (
  <div>
    <div className="between" style={{ marginBottom: 6, fontSize: 12 }}>
      <div className="row" style={{ gap: 6 }}>
        <span className="display" style={{ color: colorA, fontSize: 13 }}>{codeA}</span>
        <span className="mono" style={{ fontWeight: 700, color: 'var(--text)' }}>{a}%</span>
      </div>
      <div className="row" style={{ gap: 6 }}>
        <span className="mono" style={{ fontWeight: 700, color: 'var(--text)' }}>{b}%</span>
        <span className="display" style={{ color: colorB, fontSize: 13 }}>{codeB}</span>
      </div>
    </div>
    <div className="ribbon" style={{ height: 14 }}>
      <div style={{ width: `${a}%`, background: colorA, boxShadow: `inset 0 -2px 0 rgba(0,0,0,0.15)` }}/>
      <div style={{ width: `${b}%`, background: colorB, boxShadow: `inset 0 -2px 0 rgba(0,0,0,0.15)` }}/>
    </div>
  </div>
);

const WormGraph = ({ teamA, teamB, overs = 20, target = 178, w = 320, h = 160 }) => {
  const padL = 28, padR = 12, padT = 14, padB = 22;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const maxRuns = Math.max(target + 20, ...(teamA||[0]), ...(teamB||[0]));
  const xAt = (o) => padL + (o / overs) * innerW;
  const yAt = (r) => padT + innerH - (r / maxRuns) * innerH;
  const path = (data) => data.map((r, i) =>
    `${i === 0 ? 'M' : 'L'}${xAt(i).toFixed(1)} ${yAt(r).toFixed(1)}`
  ).join(' ');
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      {[0, 0.25, 0.5, 0.75, 1].map(p => (
        <line key={p} x1={padL} x2={w - padR}
          y1={padT + p * innerH} y2={padT + p * innerH}
          stroke="var(--hairline)" strokeDasharray="2 3"/>
      ))}
      {[0, 5, 10, 15, 20].map(o => (
        <text key={o} x={xAt(o)} y={h - 6}
          fontSize="9" fontFamily="JetBrains Mono"
          fill="var(--muted)" textAnchor="middle">{o}</text>
      ))}
      {[0, Math.floor(maxRuns/2), maxRuns].map(r => (
        <text key={r} x={padL - 6} y={yAt(r) + 3}
          fontSize="9" fontFamily="JetBrains Mono"
          fill="var(--muted)" textAnchor="end">{r}</text>
      ))}
      <line x1={padL} x2={w - padR} y1={yAt(target)} y2={yAt(target)}
        stroke="var(--gold)" strokeDasharray="3 3" strokeWidth="1"/>
      <text x={w - padR - 4} y={yAt(target) - 4}
        fontSize="9" fontFamily="JetBrains Mono"
        fill="var(--gold)" textAnchor="end">TGT {target}</text>
      <path d={path(teamB)} fill="none" stroke="#FFD93D" strokeWidth="2"/>
      <path d={path(teamA)} fill="none" stroke="#FF8533" strokeWidth="2.5"/>
      {teamA.length - 1 < overs && (() => {
        const lastIdx = teamA.length - 1;
        const lastRun = teamA[lastIdx];
        const rate = lastRun / Math.max(1, lastIdx);
        const projEnd = lastRun + rate * (overs - lastIdx);
        return (
          <line x1={xAt(lastIdx)} y1={yAt(lastRun)}
            x2={xAt(overs)} y2={yAt(projEnd)}
            stroke="#FF8533" strokeWidth="2" strokeDasharray="4 4" opacity="0.5"/>
        );
      })()}
      {teamA.length > 0 && (
        <circle cx={xAt(teamA.length - 1)} cy={yAt(teamA[teamA.length - 1])}
          r="4" fill="#FF8533" stroke="#0A0E1A" strokeWidth="1.5"/>
      )}
    </svg>
  );
};

const Manhattan = ({ overs, wickets = [], w = 320, h = 130 }) => {
  const padL = 24, padR = 8, padT = 10, padB = 22;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const maxR = Math.max(15, ...overs);
  const barW = innerW / overs.length - 2;
  const colorFor = (r) => {
    if (r >= 12) return "#FF8533";
    if (r >= 8) return "#FFD93D";
    if (r >= 4) return "#1FAE5A";
    return "#5870FF";
  };
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      {[0, 0.5, 1].map(p => (
        <line key={p} x1={padL} x2={w-padR} y1={padT + p*innerH} y2={padT + p*innerH}
          stroke="var(--hairline)" strokeDasharray="2 3"/>
      ))}
      {overs.map((r, i) => {
        const x = padL + i * (innerW / overs.length) + 1;
        const barH = (r / maxR) * innerH;
        const y = padT + innerH - barH;
        return (
          <g key={i}>
            <rect x={x} y={y} width={barW} height={barH} rx="2" fill={colorFor(r)} opacity="0.85"/>
            {wickets.includes(i) && (
              <circle cx={x + barW/2} cy={y - 6} r="3" fill="#FF4757"/>
            )}
            {(i === 0 || i === 4 || i === 9 || i === 14 || i === overs.length - 1) && (
              <text x={x + barW/2} y={h - 7} fontSize="9"
                fontFamily="JetBrains Mono" fill="var(--muted)" textAnchor="middle">{i+1}</text>
            )}
          </g>
        );
      })}
      <rect x={padL} y={padT} width={6 * (innerW / overs.length)} height={innerH}
        fill="var(--saffron)" opacity="0.05" stroke="var(--saffron)" strokeOpacity="0.18" strokeDasharray="2 2"/>
    </svg>
  );
};

const BallByBall = ({ balls = [] }) => {
  const colorFor = (b) => {
    if (b === 'W') return { bg: 'var(--crimson)', fg: '#fff' };
    if (b === '6') return { bg: 'var(--saffron)', fg: '#0A0E1A' };
    if (b === '4') return { bg: '#5870FF', fg: '#fff' };
    if (b === '0' || b === '•') return { bg: 'var(--raised-2)', fg: 'var(--muted)' };
    if (b === 'WD' || b === 'NB' || b === 'LB') return { bg: 'transparent', fg: 'var(--gold)', border: '1px dashed var(--gold)' };
    return { bg: 'var(--raised)', fg: 'var(--text)' };
  };
  return (
    <div style={{ display: 'flex', gap: 6, overflowX: 'auto', padding: '4px 0' }}>
      {balls.map((b, i) => {
        const c = colorFor(b);
        return (
          <div key={i} className="mono" style={{
            minWidth: 26, height: 26, padding: '0 6px',
            borderRadius: 8,
            background: c.bg, color: c.fg, border: c.border || 'none',
            display: 'grid', placeItems: 'center',
            fontSize: 11, fontWeight: 700,
            flexShrink: 0
          }}>{b}</div>
        );
      })}
    </div>
  );
};

const PortfolioRing = ({ roi = 24, win = 68, wagered = 75, size = 130 }) => {
  const r1 = size/2 - 6, r2 = r1 - 12, r3 = r2 - 12;
  const arc = (val, r) => {
    const c = 2 * Math.PI * r;
    return { strokeDasharray: c, strokeDashoffset: c - (val/100) * c };
  };
  const cx = size/2, cy = size/2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {[r1, r2, r3].map((r, i) => (
        <circle key={i} cx={cx} cy={cy} r={r}
          fill="none" stroke="var(--raised-2)" strokeWidth="6"/>
      ))}
      <g transform={`rotate(-90 ${cx} ${cy})`}>
        <circle cx={cx} cy={cy} r={r1} fill="none"
          stroke="var(--saffron)" strokeWidth="6" strokeLinecap="round"
          {...arc(roi, r1)}/>
        <circle cx={cx} cy={cy} r={r2} fill="none"
          stroke="var(--pitch)" strokeWidth="6" strokeLinecap="round"
          {...arc(win, r2)}/>
        <circle cx={cx} cy={cy} r={r3} fill="none"
          stroke="var(--gold)" strokeWidth="6" strokeLinecap="round"
          {...arc(wagered, r3)}/>
      </g>
    </svg>
  );
};

const Scoreboard = ({ teamA = "MUM", teamB = "CHE",
                      runsA = 142, wicketsA = 4, oversA = "15.2",
                      runsB = 178, wicketsB = 6, oversB = "20.0",
                      status = "MUM need 36 in 28",
                      live = true, glow = true,
                      venue = "Wankhede · 19:30 IST",
                      innings = "2nd Innings · T20" }) => {
  const tA = TEAMS[teamA] || TEAMS.MUM;
  const tB = TEAMS[teamB] || TEAMS.CHE;
  return (
    <div className="card raised pitch-noise" style={{ padding: 18, position: 'relative', overflow: 'hidden' }}>
      <div className="pitch-grain" style={{ position: 'absolute', inset: 0, pointerEvents: 'none', opacity: 0.6 }}/>
      <div className="between" style={{ position: 'relative', zIndex: 1 }}>
        <div>
          <div className="eyebrow" style={{ color: 'var(--muted)' }}>{innings}</div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{venue}</div>
        </div>
        {live && <span className="chip chip-live"><span className="live-dot"/>LIVE</span>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', alignItems: 'center', gap: 12, marginTop: 14 }}>
        <div className="col" style={{ alignItems: 'flex-start', gap: 8 }}>
          <TeamCrest code={teamA} size={42}/>
          <div className="display" style={{ fontSize: 14, color: tA.c1 }}>{teamA}</div>
          <div>
            <div className="display" style={{ fontSize: 36, lineHeight: 0.95, letterSpacing: '-0.04em' }}>
              <span className={glow ? 'glow-pitch' : ''}>{runsA}</span>
              <span style={{ color: 'var(--muted)', fontSize: 24 }}>/{wicketsA}</span>
            </div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>({oversA} ov)</div>
          </div>
        </div>
        <div className="display" style={{ fontSize: 13, color: 'var(--muted)', background: 'var(--raised-2)', padding: '3px 7px', borderRadius: 6 }}>VS</div>
        <div className="col" style={{ alignItems: 'flex-end', gap: 8 }}>
          <TeamCrest code={teamB} size={42}/>
          <div className="display" style={{ fontSize: 14, color: tB.c1 }}>{teamB}</div>
          <div style={{ textAlign: 'right' }}>
            <div className="display" style={{ fontSize: 36, lineHeight: 0.95, letterSpacing: '-0.04em' }}>
              <span style={{ color: 'var(--muted)', fontSize: 24 }}>/{wicketsB}</span>
              <span>{runsB}</span>
            </div>
            <div className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>({oversB} ov)</div>
          </div>
        </div>
      </div>
      <div style={{ marginTop: 14, padding: '8px 12px', background: 'var(--raised-2)', borderRadius: 10, textAlign: 'center' }}>
        <span className="mono" style={{ fontSize: 12, color: 'var(--text)', letterSpacing: '0.02em' }}>{status}</span>
      </div>
    </div>
  );
};

Object.assign(window, { Sparkline, WinProbRibbon, WormGraph, Manhattan, BallByBall, PortfolioRing, Scoreboard });
