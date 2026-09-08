# DoG provenance

Source: https://github.com/Fun10165/dsh-dog/tree/v1.2.0 (BSD-3-Clause).
The upstream license and copyright notices are retained in LICENSE.

OpenWrite compatibility changes:

- dsh 0.1.2-rc.1 public session, settings and RPC interfaces; Cordis 4.0.2.
- Host SDK modules remain external to the bundle.
- Host engine and debug transport are singletons; tools are registered by the
  OpenWrite preset through the `openwriteDog` service.
- The debugger opens from OpenWrite tasks on `openwrite:dog-open`. No default
  dock, host margin mutation, or idle polling is enabled in this integration.
- Upstream browser capture directories are excluded from the vendored source.
- Browser and host type checking are separate; shared RPC records live in a
  browser-safe contract module. Pending interaction state uses uiSession.
- Programmatic verifier scripts run asynchronously with owned process cleanup
  on cancellation or unload, including Windows process trees. Artifact archiving
  uses the portable tar library instead of a required system tar executable.

The verification engine, graph schema, evidence records and storage keys remain
upstream-compatible. This is a maintained integration, not an upstream release.
