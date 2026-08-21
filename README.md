# tmm-cli

Public thin client for the TMM remote execution service. This is the only
customer-facing executable of the TMM project: it bundles authored inputs,
sends them to the private `tmm-server` over HTTPS, polls run status, and
publishes returned artifacts locally.

## Commands

- `tmm linkage INPUT --output DIR`
- `tmm md INPUT --format A1|A2|A3 --output FILE`
- `tmm render INPUT --output FILE [--scale N | --target-max-side N]`
- `tmm svg INPUT --output FILE [--format svg|png] [render/SVG/PNG options]`
- `tmm kompas INPUT --output FILE`
- `tmm quota`
- `tmm resume UUID --output PATH`
- `tmm cancel UUID`
- `tmm version`

## Environment

- `TMM_API_TOKEN` — required execution token (never passed on argv/URL).
- `TMM_API_URL` — optional base URL override; release builds embed the
  production HTTPS URL. Plain HTTP is accepted only for loopback hosts.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | usage / local input error |
| 3 | auth or quota failure |
| 4 | remote domain failure |
| 5 | resumable transport failure (prints `Run ID:` + `Resume:` lines) |
| 6 | server/worker failure |

## Development

```
go build ./...
go test ./...
```

The client owns no calculation logic; all computation happens server-side.
