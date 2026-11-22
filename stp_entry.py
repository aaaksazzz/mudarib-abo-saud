"""Gunicorn entrypoint that attaches the AI analyst routes to the existing STP app."""
import app as core
from ai_market_analyst import register_ai_routes

register_ai_routes(core)
app = core.app

from site_autopilot import install as install_site_autopilot

install_site_autopilot(core)

from ai_company import install as install_ai_company

install_ai_company(core)
