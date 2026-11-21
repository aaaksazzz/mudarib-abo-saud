# AS integration policy

The upstream `trader-broker/ticket.py` is imported only for offline ticket
formatting and decision-log functionality. It is not connected to a broker.
AS must never call a broker endpoint or send an order from this suite.

The default configuration explicitly sets `execution_enabled: false`,
`paper: true`, and disables options, margin, short selling and non-equity
assets in the upstream risk defaults. Do not add API keys to this repository.
Any future broker feature requires a separate explicit user request, security
review, paper-only integration, and a second confirmation before every action.

The upstream tools are standalone command-line utilities at this stage. Their
presence in the repository does not mean they are already wired into the AS
web interface, scheduled, or active in production.
