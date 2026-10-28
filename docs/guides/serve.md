# Viewer and cheme serve

`cheme serve` serves a plant repository read-only as a JSON API on `127.0.0.1:8765`, and with
`--ui` a built viewer at `/`. The generated
[serve API reference](../reference/serve-api.md) lists every route with its parameters; this
page describes what they return and the rules the server keeps.

<!-- readme: ### serve | body -->

## Serving to the network

By default the server binds `127.0.0.1` and answers only requests whose `Host` header names
`127.0.0.1`, `localhost` or `::1`. Other names are refused with 400. This blocks DNS
rebinding: a web page cannot point its own host name at the server and then read the
repository. The rule still applies with `--host 0.0.0.0` (or `::`), because a wildcard address
names no host. Pass each name or address other machines use to reach the server with
`--allow-host` (repeatable; wildcards are refused). A specific `--host` address is accepted
as well:

```sh
cheme serve --host 0.0.0.0 --allow-host 192.168.1.5 --allow-host box.lan
```

Whoever reaches the port by one of those names can read every file of the repository. On a
non-local address the server also refuses `GET /api/session` and `POST /api/checks/run`
(403), so nobody on the network can run the command checks of `checks/checks.yaml`.
`--allow-remote-checks` turns them back on.

The viewer's pages carry `Content-Security-Policy: frame-ancestors 'self'` and
`X-Frame-Options: SAMEORIGIN`: only the served origin may frame them, so another site cannot
trick a click on "Run now" inside a frame.
