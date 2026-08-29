"""FastAPI app that receives TradingView's webhook alerts.

TradingView can't send custom headers, so the shared secret is embedded in
the URL path itself: POST /webhook/<WEBHOOK_SECRET>. Point TradingView's
alert "Webhook URL" field at that full URL.
"""
import logging

from fastapi import FastAPI, HTTPException, Request

from bot import config, state, trading

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("webhook")

app = FastAPI()


@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    if not config.WEBHOOK_SECRET:
        raise HTTPException(500, "WEBHOOK_SECRET is not configured on the server")
    if secret != config.WEBHOOK_SECRET:
        raise HTTPException(403, "invalid secret")

    body = await request.body()
    try:
        import json
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(400, "body is not valid JSON")

    log.info("Received alert: %s", payload)

    if payload.get("event") != "entry":
        return {"status": "ignored", "reason": f"unknown event '{payload.get('event')}'"}

    result = trading.handle_entry_signal(payload)
    return result


@app.get("/status")
async def status():
    current_state = state.load()
    return {
        "live_trading": config.LIVE_TRADING,
        "equity": current_state["equity"],
        "position": current_state["position"],
    }
