# GullyTrader — Open Tasks

## Now

- [ ] Wire real Kalshi API credentials to `kalshi_client.py` (currently returns mock data)
- [ ] Pick a cricket data provider (CricBuzz vs SportMonks) and implement `cricket_data.py`
- [ ] Implement scanner: filter Kalshi events by IPL prefix and parlay-spam patterns
- [ ] Implement researcher: pull live ball-by-ball context from cricket feed
- [ ] Implement decision agent: stake sizing (Kelly fraction or fixed %)
- [ ] Implement portfolio_exit agent (with shadow mode default)
- [ ] Persist closed-market cache for restart resilience
- [ ] Add agent_logs TTL rotation (default 7 days)

## Later

- [ ] Add 8-screen visual regression tests (Playwright)
- [ ] Backfill the test bench to KalshiTrader-equivalent rigor (170+ tests)
- [ ] Wire confetti micro-animation on a winning settlement
- [ ] Add pull-to-refresh on home + match centre
- [ ] Long-press on position cards for quick close/alert actions
- [ ] Reduced-motion media query support

## Done

- [x] Project skeleton + README + CLAUDE.md (2026-04-30)
- [x] Backend module stubs ported from KalshiTrader (2026-04-30)
- [x] Frontend lifted from claude.ai/design bundle, routed via hash router (2026-04-30)
- [x] P&L paired-position correction test (2026-04-30)
