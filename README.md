# tradeing

A TradingView-signal-driven trading bot for Kraken Spot (BTC/USD, ETH/USD),
built around the `pine/ProScalpv3.7.pine` strategy. Starts in **paper trading
mode by default** — no real orders until you explicitly flip `LIVE_TRADING=true`.

## How it works

```
TradingView (Pine strategy fires alert() on entry)
        |  webhook POST (JSON: side, symbol, price, atr)
        v
bot/webhook_server.py  --> bot/trading.py (sizes + opens the position)
        ^
        |  polls live price every few seconds
bot/monitor.py  --> bot/trading.py (checks stop/target/breakeven/time-stop)
```

TradingView only tells the bot about **entries**. The bot itself manages the
exit bracket (stop-loss, take-profit, breakeven move, time-stop) against
Kraken's live price, using the same ATR multiples the Pine strategy was
backtested with. This is more robust than round-tripping every exit through
another TradingView alert.

## Known limitations / design decisions (read before going live)

- **Long-only.** The strategy signals both long and short trend flips, but
  Kraken Spot can't short. Short signals are logged and ignored
  (`ALLOW_SHORTS=false`). In the backtest, shorts were roughly half of all
  trades — running long-only is a real deviation from the tested strategy,
  not just a config detail.
- **One position at a time, across both symbols.** If BTCUSD and ETHUSD
  signal close together, whichever reaches the webhook first takes the
  trade; the other is skipped until flat again. This matches the Pine
  strategy's own single-slot (`pyramiding=1`) design.
- **Position sizing defaults to 100% of account equity per trade**
  (`POSITION_SIZE_FRACTION=1.0`). The backtest in `pine/ProScalpv3.7.pine`
  was run with a $3,000 position on $25,000 capital — **12%**, not 100%. At
  12% sizing that backtest showed a 31.5% win rate and ~23–25% max drawdown
  over one month; at 100% sizing every one of those losing trades (68% of
  them) is roughly 8x larger relative to the account. Strongly consider
  lowering `POSITION_SIZE_FRACTION` (e.g. to `0.12`) to match what was
  actually tested, especially before ever setting `LIVE_TRADING=true`.
- **No exchange-side stop order as a safety net.** If the bot process or VPS
  goes down while a position is open, the position sits unmanaged until it
  comes back. For real money, consider also placing a real stop-loss order
  on Kraken right after entry as a backstop (not yet implemented here).
- **Live equity tracking is approximate.** The bot tracks equity as
  `PAPER_STARTING_BALANCE` (or your real starting balance) plus realized
  P&L from trades it has made — it does not re-poll your full Kraken wallet
  balance. Manual deposits/withdrawals won't be reflected automatically.
- **The Pine strategy's session filter is stock-market-shaped.** It defaults
  to restricting entries to 09:30–16:00 exchange time — fine for the SPY
  options timing this script was originally built around, but it will
  silently skip most signals on a 24/7 market. Turn **"Restrict entries to
  regular trading hours"** OFF on your BTCUSD/ETHUSD TradingView charts.

## Setup

### 1. TradingView

1. Open `pine/ProScalpv3.7.pine` in the Pine Editor, add it to your BTCUSD
   and ETHUSD charts (as a Strategy).
2. On each chart, turn off **Session Filter → Restrict entries to regular
   trading hours** (see limitation above).
3. Right-click the chart → **Add Alert** → Condition: this script → **"Any
   alert() function call"** → check **Webhook URL** → paste
   `https://<your-vps-host>/webhook/<WEBHOOK_SECRET>` (see step 3 below).
   Expiration: open-ended. Repeat for both BTCUSD and ETHUSD charts.

### 2. Server (VPS)

```bash
git clone <this repo>
cd tradeing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into WEBHOOK_SECRET in .env
```

Run it:

```bash
python -m bot.main
```

Or as a systemd service so it survives reboots:

```ini
# /etc/systemd/system/tradeing-bot.service
[Unit]
Description=tradeing bot
After=network.target

[Service]
WorkingDirectory=/path/to/tradeing
ExecStart=/path/to/tradeing/.venv/bin/python -m bot.main
Restart=on-failure
EnvironmentFile=/path/to/tradeing/.env

[Install]
WantedBy=multi-user.target
```

You'll also need this port reachable from the internet (behind a reverse
proxy with TLS, e.g. Caddy or nginx + Let's Encrypt, since TradingView
webhooks should be sent to `https://`, not plain `http://`).

### 3. Paper trade first

With `LIVE_TRADING=false` (the default), the bot uses real live Kraken
prices but never places real orders — it simulates fills against
`PAPER_STARTING_BALANCE` and logs everything to `trade_log.csv`. Watch
`GET /status` and the trade log for at least a couple of weeks of real
signals before considering live mode.

### 4. Going live

1. Create a Kraken API key with **only** "Query Funds" and "Create & Modify
   Orders" permissions — never "Withdraw Funds".
2. Put the key/secret in `.env` (`KRAKEN_API_KEY` / `KRAKEN_API_SECRET`).
3. Decide on `POSITION_SIZE_FRACTION` deliberately — see the sizing note
   above.
4. Set `LIVE_TRADING=true` and restart the bot.

## Files

- `pine/ProScalpv3.7.pine` — the TradingView strategy, with webhook alerting
  added for bot integration.
- `pine/ORB_930_Retest.pine` — a separate, standalone Pine strategy (not wired
  to the bot below, which is crypto/Kraken-specific): a 9:30 AM opening-range
  breakout + retest scalper for the regular equities/futures cash session.
  Marks the first N minutes' high/low as the day's range, waits for a
  directional close beyond it, then enters on a retest that shows a rejection
  back in the breakout direction, with a risk-based position size and a fixed
  R-multiple target. Meant to be run/backtested on its own chart (1-minute
  recommended).
- `pine/OneCandleRule_TrendScalp.pine` — another standalone Pine strategy
  (same disclaimer: not wired to the bot). A three-step trend-pullback
  scalper: (1) classifies the daily trend from swing structure and skips
  sideways days, (2) on the 1-minute chart, tracks a single trailing
  reference candle - the most recent down-close candle at a new high in an
  uptrend, or up-close candle at a new low in a downtrend - and enters when
  price retests that candle's zone and holds, (3) risk-based sizing with a
  fixed reward multiple and a stop that trails the reference candle as the
  trend continues. Also 1-minute-chart recommended.
- `bot/config.py` — all settings, loaded from `.env`.
- `bot/kraken_client.py` — thin ccxt wrapper (public price data + private orders).
- `bot/broker.py` — `PaperBroker` (simulated fills) / `LiveBroker` (real orders).
- `bot/trading.py` — sizing, entry handling, and the stop/target/breakeven/time-stop bracket.
- `bot/state.py` — JSON-file position/equity state + CSV trade log.
- `bot/monitor.py` — background loop that checks the open position against its bracket.
- `bot/webhook_server.py` — FastAPI app receiving TradingView alerts.
- `bot/main.py` — entrypoint (`python -m bot.main`).
