# Security

Hutch defaults to local development. `hutch serve` binds to `127.0.0.1`,
and the daemon refuses non-loopback hosts unless `HUTCH_TOKEN` is set or
`--unsafe-no-auth` is passed explicitly.

## Daemon token

`HUTCH_TOKEN` is bearer-token authentication for SDK and API clients
that talk directly to the daemon:

```bash
export HUTCH_TOKEN="$(openssl rand -hex 32)"
hutch serve --host 0.0.0.0
```

Clients send it as:

```http
Authorization: Bearer <token>
```

This token is not production-grade browser authentication. Values
exposed through `NEXT_PUBLIC_HUTCH_TOKEN` are intentionally visible to
browser JavaScript, and WebSocket query parameters can appear in local
logs. Use that path only for trusted local development, lab networks,
or demos.

## Hosted dashboards

For a hosted or shared dashboard, put Hutch behind real application
auth:

- A same-origin reverse proxy with SSO or session cookies.
- TLS termination at the proxy.
- Proxy-level protection for `/`, `/runs`, `/events`, `/steering`,
  `/docs`, and `/openapi.json`.
- Short-lived WebSocket or session credentials instead of static
  browser tokens.

The daemon token is still useful for agents and SDK clients behind that
proxy, but it should not be the only user-facing access control.

## LLM importer

`hutch import --llm` sends filenames, metadata, README snippets, and
sample records to the configured LLM provider. Treat that path as a
data-egress boundary. Generated adapters run under constrained Python
execution, not a kernel or container sandbox. Use trusted or staged
inputs unless Hutch is running inside a container or VM with no host
secrets mounted.
