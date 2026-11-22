"""Gunicorn entrypoint that attaches the AI analyst routes to the existing STP app."""
import app as core
from ai_market_analyst import register_ai_routes

register_ai_routes(core)
app = core.app
