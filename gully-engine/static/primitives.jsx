// GullyTrader — primitive UI atoms (chips, tab bar, crests)

// Abstract monogram crest — shield-like hex with team code
const Crest = ({ code = "MUM", color = "#FF8533", color2 = "#E85D04", size = 36 }) => {
  const id = `crest-${code}-${Math.random().toString(36).slice(2,7)}`;
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-label={code}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={color}/>
          <stop offset="100%" stopColor={color2}/>
        </linearGradient>
      </defs>
      <path d="M20 2 L36 9 L36 24 C36 31 28.5 36.5 20 39 C11.5 36.5 4 31 4 24 L4 9 Z"
            fill={`url(#${id})`} stroke="rgba(255,255,255,0.18)" strokeWidth="1"/>
      <text x="20" y="25" textAnchor="middle"
            fontFamily="Archivo Black, sans-serif" fontSize="13"
            letterSpacing="-0.04em" fill="#0A0E1A">{code}</text>
      <path d="M14 6 L20 11 L26 6" stroke="rgba(255,255,255,0.35)" strokeWidth="1.4" fill="none"/>
    </svg>
  );
};

const TEAMS = {
  MUM: { code: "MUM", name: "Mumbai Marauders",  c1: "#2E4FFF", c2: "#5870FF" },
  CHE: { code: "CHE", name: "Chennai Crowns",     c1: "#FFD93D", c2: "#FFB700" },
  BLR: { code: "BLR", name: "Bengaluru Bolts",    c1: "#FF4757", c2: "#C81E2C" },
  KOL: { code: "KOL", name: "Kolkata Kings",      c1: "#7B3FF2", c2: "#4B1E95" },
  DEL: { code: "DEL", name: "Delhi Daredevils",   c1: "#1FAE5A", c2: "#0E6F38" },
  PUN: { code: "PUN", name: "Punjab Pulse",       c1: "#FF8533", c2: "#E85D04" },
  HYD: { code: "HYD", name: "Hyderabad Hawks",    c1: "#FF8533", c2: "#FF4757" },
  RAJ: { code: "RAJ", name: "Rajasthan Royals",   c1: "#FF6FB5", c2: "#9B2D67" },
};

const TeamCrest = ({ code, size = 36 }) => {
  const t = TEAMS[code] || TEAMS.MUM;
  return <Crest code={code} color={t.c1} color2={t.c2} size={size}/>;
};

const Chip = ({ children, variant = "default", style }) => (
  <span className={`chip ${variant !== "default" ? `chip-${variant}` : ""}`} style={style}>
    {children}
  </span>
);

const LiveChip = () => (
  <span className="chip chip-live">
    <span className="live-dot"/> LIVE
  </span>
);

// Bottom tab bar — clickable. Hash-router driven.
const TabBar = ({ active = "home", onSelect }) => {
  const tabs = [
    { id: "home", label: "Home", route: "#/", icon:
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M3 11l9-8 9 8v9a2 2 0 0 1-2 2h-4v-7H10v7H6a2 2 0 0 1-2-2v-9z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"/></svg> },
    { id: "match", label: "Match", route: "#/match", icon:
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2"/><path d="M5 8c5 3 9 3 14 0M5 16c5-3 9-3 14 0" stroke="currentColor" strokeWidth="2"/></svg> },
    { id: "trends", label: "Trends", route: "#/trends", icon:
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M3 17l6-6 4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/><path d="M14 7h7v7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg> },
    { id: "table", label: "Table", route: "#/standings", icon:
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2"/><path d="M3 10h18M3 16h18M9 4v16" stroke="currentColor" strokeWidth="2"/></svg> },
    { id: "you", label: "You", route: "#/positions", icon:
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2"/><path d="M4 21c1-4.5 4.5-7 8-7s7 2.5 8 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg> },
  ];
  const handle = (t) => {
    if (onSelect) onSelect(t);
    else window.location.hash = t.route;
  };
  return (
    <div className="tab-bar">
      {tabs.map(t => (
        <button key={t.id} className={`tab ${active === t.id ? 'active' : ''}`} onClick={() => handle(t)}>
          <div className="tab-icon">{t.icon}</div>
          <div>{t.label}</div>
        </button>
      ))}
    </div>
  );
};

const Avatar = ({ initials = "DE", color = "#FF8533" }) => (
  <div style={{
    width: 36, height: 36, borderRadius: 99,
    background: `linear-gradient(135deg, ${color}, #2E4FFF)`,
    color: '#0A0E1A',
    fontFamily: 'Archivo Black, sans-serif', fontSize: 13,
    display: 'grid', placeItems: 'center',
    border: '1px solid rgba(255,255,255,0.18)'
  }}>{initials}</div>
);

const Delta = ({ v, suffix = "%" }) => {
  const pos = v >= 0;
  return (
    <span className="mono" style={{
      color: pos ? 'var(--pitch)' : 'var(--crimson)',
      fontWeight: 600, fontSize: 13
    }}>
      <span style={{ marginRight: 3 }}>{pos ? '▲' : '▼'}</span>
      {pos ? '+' : ''}{v.toFixed(2)}{suffix}
    </span>
  );
};

Object.assign(window, { TeamCrest, Crest, TEAMS, Chip, LiveChip, TabBar, Avatar, Delta });
