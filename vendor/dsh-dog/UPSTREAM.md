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

The verification engine, graph schema, evidence records and storage keys remain
upstream-compatible. This is a maintained integration, not an upstream release.
