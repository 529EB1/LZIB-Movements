# Instructions for future changes

- Never commit secrets or expose full Discord webhook URLs in logs, errors, tests, or output.
- Never make live API requests during tests and never deploy without explicit approval.
- Keep all providers replaceable and use provider-independent domain models.
- Keep LZIB Movements completely separate from AstroRemote: no shared files, users, services,
  databases, ports, variables, directories, or virtual environments.
- Preserve the exact aircraft-alert rules unless explicitly instructed otherwise.
- Treat VRS routes as fallible database matches, never official or confirmed destinations.
- Do not scrape JetPhotos or image-search websites.
- Do not claim live operation was verified without real-data and real-credential testing.
- Do not weaken request-budget protections or introduce one-request-per-aircraft polling.
- Run pytest, Ruff lint/format checks, and mypy before completing changes.
