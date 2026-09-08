/** Scoped styles for the frame overlay; installed and removed with the client plugin fiber. */

export const DOG_DEBUG_STYLE_ID = '@dsh-external/dsh-dog/debugger'

export const DOG_DEBUG_CSS = String.raw`
.dog-overlay-root,
.dog-overlay-root * { box-sizing: border-box; }
.dog-overlay-root { pointer-events: none; font-family: inherit; }
.dog-dock {
  pointer-events: auto; position: fixed; top: 14px; right: 16px; bottom: 14px; z-index: 380;
  width: min(354px, calc(100vw - 24px)); display: flex; flex-direction: column;
  color: var(--dsw-alias-label-primary); background: color-mix(in srgb, var(--dsw-alias-bg-base) 92%, #7065e9 8%);
  border: 1px solid color-mix(in srgb, #7165e9 35%, var(--dsw-alias-border-l1)); border-radius: 16px;
  box-shadow: 0 16px 48px rgba(12, 16, 29, .22); backdrop-filter: blur(18px) saturate(1.08); overflow: hidden;
}
.dog-overlay-root[data-dog-dock-layout=hidden] .dog-dock { display: none; }
.dog-overlay-root[data-dog-dock-layout=floating] .dog-dock { top: 70px; bottom: auto; max-height: min(346px, calc(100dvh - 84px)); }
.dog-overlay-root[data-dog-dock-layout=collapsed] .dog-dock { top: 50%; right: 10px; bottom: auto; width: 46px; max-height: none; transform: translateY(-50%); border-radius: 14px; }
.dog-dock-rail { width: 100%; min-height: 112px; border: 0; padding: 9px 4px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 9px; color: var(--dsw-alias-label-secondary); background: transparent; cursor: pointer; font: inherit; }
.dog-dock-rail:hover { color: var(--dsw-alias-label-primary); background: color-mix(in srgb, #7165e9 9%, transparent); }
.dog-dock-rail-mark { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; color: #fff; background: linear-gradient(145deg, #8174ff, #4b41ba); box-shadow: 0 5px 13px rgba(92, 78, 203, .22); }
.dog-dock-rail strong { font-size: 10px; line-height: 14px; letter-spacing: .035em; }
.dog-dock[data-collapsed=false] { display: grid; grid-template-columns: 32px minmax(0, 1fr); }
.dog-dock-collapse-slot { min-height: 0; display: flex; align-items: center; justify-content: center; border-right: 1px solid color-mix(in srgb, var(--dsw-alias-border-l2) 72%, transparent); background: color-mix(in srgb, #7165e9 4%, transparent); }
.dog-dock-collapse-handle { width: 24px; height: 64px; border: 1px solid color-mix(in srgb, #7165e9 28%, var(--dsw-alias-border-l2)); border-radius: 8px; display: grid; place-items: center; color: var(--dsw-alias-label-secondary); background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 92%, #7165e9 8%); cursor: pointer; }
.dog-dock-collapse-handle:hover { color: var(--dsw-alias-label-primary); border-color: color-mix(in srgb, #7165e9 48%, var(--dsw-alias-border-l2)); background: color-mix(in srgb, #7165e9 13%, var(--dsw-alias-bg-base)); }
.dog-dock-content { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.dog-dock-header { min-height: 50px; padding: 7px 8px 7px 10px; display: flex; align-items: center; gap: 9px; border-bottom: 1px solid var(--dsw-alias-border-l2); }
.dog-dock-mark { width: 30px; height: 30px; flex: none; border-radius: 10px; display: grid; place-items: center; color: #fff; background: linear-gradient(145deg, #8174ff, #4b41ba); box-shadow: 0 6px 16px rgba(92, 78, 203, .23); }
.dog-dock-heading { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.dog-dock-heading h2 { margin: 0; font-size: 12px; line-height: 17px; font-weight: 680; letter-spacing: -.01em; }
.dog-dock-heading span { color: var(--dsw-alias-label-tertiary); font-size: 9.5px; line-height: 14px; }
.dog-dock-error { padding: 4px 10px; color: #c94a45; background: color-mix(in srgb, #d5534d 7%, transparent); font-size: 8.5px; line-height: 12px; }
.dog-dock-list { min-height: 0; flex: 1; margin: 0; padding: 7px; list-style: none; display: flex; flex-direction: column; gap: 5px; overflow: auto; }
.dog-dock-list li { min-width: 0; }
.dog-dock-card { width: 100%; min-width: 0; border: 1px solid var(--dsw-alias-border-l2); border-radius: 11px; padding: 8px 9px; display: block; color: inherit; background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 92%, #7165e9 3%); cursor: pointer; text-align: left; font: inherit; transition: border-color 120ms ease, background 120ms ease, transform 120ms ease; }
.dog-dock-card:hover { transform: translateY(-1px); border-color: color-mix(in srgb, #7165e9 42%, var(--dsw-alias-border-l2)); background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 88%, #7165e9 7%); }
.dog-dock-card:has(.dog-state-failure), .dog-dock-card:has(.dog-state-needs_replan), .dog-dock-card:has(.dog-state-needs_human) { border-color: color-mix(in srgb, #d18135 34%, var(--dsw-alias-border-l2)); }
.dog-dock-card-head { min-width: 0; display: flex; align-items: flex-start; gap: 7px; }
.dog-dock-title-wrap { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.dog-dock-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 11px; line-height: 16px; font-weight: 630; }
.dog-dock-id { margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--dsw-alias-label-tertiary); font: 8px/12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-dock-progress { height: 3px; margin-top: 7px; display: block; border-radius: 999px; background: color-mix(in srgb, var(--dsw-alias-label-tertiary) 16%, transparent); overflow: hidden; }
.dog-dock-progress > span { display: block; height: 100%; border-radius: inherit; background: #7165e9; transition: width 180ms ease; }
.dog-dock-metrics { min-width: 0; margin-top: 5px; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 5px; color: var(--dsw-alias-label-tertiary); font-size: 8px; line-height: 12px; }
.dog-dock-metrics > span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dog-dock-metrics strong { color: var(--dsw-alias-label-secondary); font-weight: 650; }
.dog-dock-empty { padding: 17px 14px; display: flex; flex-direction: column; align-items: center; gap: 3px; color: var(--dsw-alias-label-tertiary); text-align: center; font-size: 9px; line-height: 14px; }
.dog-dock-empty strong { margin-top: 3px; color: var(--dsw-alias-label-secondary); font-size: 10px; }
.dog-dock-empty-icon { width: 32px; height: 32px; border-radius: 10px; display: grid; place-items: center; color: #7165e9; background: color-mix(in srgb, #7165e9 11%, transparent); }
.dog-dock-footer { padding: 6px 10px 7px; border-top: 1px solid var(--dsw-alias-border-l2); color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); font-size: 8.5px; line-height: 12px; text-align: center; }
.dog-dock-card:focus-visible, .dog-dock-rail:focus-visible, .dog-dock-collapse-handle:focus-visible, .dog-icon-button:focus-visible, .dog-list-button:focus-visible, .dog-node:focus-visible, .dog-agent-row:focus-visible,
.dog-segment-button:focus-visible, .dog-zoom-button:focus-visible, .dog-runtime-session-button:focus-visible { outline: 2px solid #776cf1; outline-offset: 2px; }
.dog-backdrop { pointer-events: auto; position: fixed; inset: 0; z-index: 400; display: block; background: var(--dsw-alias-bg-base); animation: dog-fade-in 120ms ease-out; }
.dog-dialog {
  width: 100vw; height: 100dvh; min-height: 0; display: grid; grid-template-rows: 68px minmax(0, 1fr);
  color: var(--dsw-alias-label-primary); background: var(--dsw-alias-bg-base); overflow: hidden; animation: dog-dialog-in 160ms cubic-bezier(.2,.8,.2,1);
}
.dog-header { min-width: 0; padding: 0 18px 0 20px; display: flex; align-items: center; gap: 14px; border-bottom: 1px solid var(--dsw-alias-border-l2); background: color-mix(in srgb, var(--dsw-alias-bg-base) 94%, #7065e9 6%); }
.dog-brand { min-width: 0; display: flex; align-items: center; gap: 11px; }
.dog-brand-mark { width: 34px; height: 34px; border-radius: 11px; display: grid; place-items: center; color: #fff; background: linear-gradient(145deg, #8174ff, #4b41ba); box-shadow: 0 7px 18px rgba(92, 78, 203, .24); }
.dog-brand-copy { min-width: 0; }
.dog-brand-title { margin: 0; font-size: 15px; line-height: 21px; font-weight: 680; letter-spacing: -.01em; }
.dog-brand-subtitle { margin: 1px 0 0; color: var(--dsw-alias-label-tertiary); font-size: 11px; line-height: 16px; }
.dog-header-divider { width: 1px; height: 28px; margin: 0 2px; background: var(--dsw-alias-border-l2); }
.dog-context { min-width: 0; display: flex; flex: 1; align-items: center; gap: 9px; }
.dog-context-title { min-width: 0; max-width: 420px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 13px; font-weight: 560; }
.dog-revision-chip, .dog-status-chip, .dog-mini-chip { border-radius: 999px; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }
.dog-revision-chip { height: 24px; padding: 0 8px; color: #655acb; background: color-mix(in srgb, #7165e9 13%, transparent); font-size: 10px; font-weight: 650; letter-spacing: .045em; text-transform: uppercase; }
.dog-header-actions { flex: none; display: flex; align-items: center; gap: 7px; }
.dog-sync-copy { margin-right: 3px; color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); font-size: 10px; white-space: nowrap; }
.dog-icon-button, .dog-zoom-button { border: 0; color: var(--dsw-alias-label-secondary); background: transparent; cursor: pointer; font: inherit; display: inline-grid; place-items: center; }
.dog-icon-button { width: 34px; height: 34px; border-radius: 10px; }
.dog-icon-button:hover, .dog-zoom-button:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-interactive-bg-hover); }
.dog-icon-button[aria-busy=true] svg { animation: dog-spin .8s linear infinite; }
.dog-workspace { position: relative; min-width: 0; min-height: 0; display: grid; grid-template-columns: 246px minmax(0, 1fr) 324px; }
.dog-sidebar, .dog-inspector { min-width: 0; min-height: 0; background: color-mix(in srgb, var(--dsw-specific-sidebar-fill, var(--dsw-alias-bg-base)) 82%, var(--dsw-alias-bg-base) 18%); overflow: auto; }
.dog-sidebar { border-right: 1px solid var(--dsw-alias-border-l2); padding: 17px 12px 18px; }
.dog-inspector { border-left: 1px solid var(--dsw-alias-border-l2); padding: 18px 16px 28px; }
.dog-section-label { margin: 0 7px 9px; color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); font-size: 10px; line-height: 16px; font-weight: 700; letter-spacing: .095em; text-transform: uppercase; }
.dog-graph-list, .dog-run-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 4px; }
.dog-sidebar-divider { height: 1px; margin: 17px 7px; background: var(--dsw-alias-border-l2); }
.dog-list-button { width: 100%; border: 1px solid transparent; border-radius: 11px; padding: 9px 9px 8px; color: inherit; background: transparent; cursor: pointer; text-align: left; font: inherit; transition: background 120ms ease, border-color 120ms ease; }
.dog-list-button:hover { background: var(--dsw-alias-interactive-bg-hover); }
.dog-list-button[data-selected=true] { border-color: color-mix(in srgb, #7165e9 30%, var(--dsw-alias-border-l2)); background: color-mix(in srgb, #7165e9 10%, var(--dsw-alias-bg-base)); }
.dog-list-row { min-width: 0; display: flex; align-items: center; gap: 8px; }
.dog-list-title { min-width: 0; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; line-height: 18px; font-weight: 590; }
.dog-list-meta { min-width: 0; margin-top: 4px; padding-left: 16px; display: flex; align-items: center; gap: 6px; overflow: hidden; white-space: nowrap; color: var(--dsw-alias-label-tertiary); font-size: 10px; line-height: 15px; }
.dog-list-meta > :last-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.dog-list-current { color: #6e63dd; font-weight: 650; }
.dog-state-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; background: #8a929c; box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 12%, transparent); }
.dog-empty-small { margin: 0 7px; color: var(--dsw-alias-label-tertiary); font-size: 11px; line-height: 18px; }
.dog-main { min-width: 0; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); background: var(--dsw-alias-bg-base); }
.dog-summary { min-width: 0; padding: 14px 18px 13px; display: grid; grid-template-columns: minmax(190px, 1fr) repeat(4, minmax(82px, 116px)); gap: 10px; border-bottom: 1px solid var(--dsw-alias-border-l2); }
.dog-summary-primary, .dog-metric { min-width: 0; min-height: 55px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 12px; background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 88%, #7065e9 3%); }
.dog-summary-primary { padding: 9px 11px; display: flex; align-items: center; gap: 11px; }
.dog-root-orb { width: 34px; height: 34px; flex: none; border-radius: 50%; display: grid; place-items: center; color: white; }
.dog-summary-copy { min-width: 0; }
.dog-summary-kicker, .dog-metric-label { color: var(--dsw-alias-label-tertiary); font-size: 9px; line-height: 14px; font-weight: 680; letter-spacing: .08em; text-transform: uppercase; }
.dog-summary-value { margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; line-height: 18px; font-weight: 610; }
.dog-metric { padding: 8px 10px; }
.dog-metric-value { margin-top: 1px; font-size: 17px; line-height: 23px; font-weight: 680; letter-spacing: -.025em; }
.dog-canvas-shell { min-width: 0; min-height: 0; display: grid; grid-template-rows: 40px minmax(0, 1fr); }
.dog-canvas-toolbar { padding: 0 15px 0 18px; display: flex; align-items: center; gap: 14px; border-bottom: 1px solid color-mix(in srgb, var(--dsw-alias-border-l2) 70%, transparent); }
.dog-legend { display: flex; align-items: center; gap: 12px; color: var(--dsw-alias-label-tertiary); font-size: 10px; }
.dog-legend-item { display: inline-flex; align-items: center; gap: 5px; }
.dog-legend-line { width: 21px; height: 0; border-top: 1.5px solid #857ce2; }
.dog-legend-line[data-kind=depends] { border-top-style: dashed; border-color: #c07a39; }
.dog-canvas-spacer { flex: 1; }
.dog-zoom { height: 28px; padding: 0 3px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 9px; display: flex; align-items: center; }
.dog-zoom-button { width: 24px; height: 22px; border-radius: 6px; font-size: 15px; }
.dog-zoom-value { width: 39px; text-align: center; color: var(--dsw-alias-label-tertiary); font-size: 10px; }
.dog-canvas-scroll { min-width: 0; min-height: 0; position: relative; overflow: auto; background-color: color-mix(in srgb, var(--dsw-alias-bg-base) 96%, #7065e9 4%); background-image: radial-gradient(color-mix(in srgb, var(--dsw-alias-label-tertiary) 20%, transparent) .7px, transparent .7px); background-size: 20px 20px; }
.dog-canvas-stage-wrap { position: relative; margin: 0 auto; }
.dog-canvas-stage { position: absolute; top: 0; left: 0; transform-origin: top left; }
.dog-edges { position: absolute; inset: 0; overflow: visible; pointer-events: none; }
.dog-edge { fill: none; stroke-width: 1.5; }
.dog-edge[data-kind=contains] { stroke: #857ce2; }
.dog-edge[data-kind=dependsOn] { stroke: #c07a39; stroke-width: 1.35; stroke-dasharray: 6 5; }
.dog-edge[data-muted=true] { opacity: .22; }
.dog-edge[data-highlighted=true] { stroke-width: 2.4; filter: drop-shadow(0 0 3px color-mix(in srgb, currentColor 45%, transparent)); }
.dog-node { position: absolute; border: 1px solid var(--dsw-alias-border-l2); border-radius: 14px; padding: 10px 11px 9px; display: flex; flex-direction: column; color: var(--dsw-alias-label-primary); background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 94%, #7165e9 2%); box-shadow: 0 4px 14px rgba(14, 18, 29, .05); cursor: pointer; text-align: left; font: inherit; transition: border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease; }
.dog-node:hover { transform: translateY(-2px); border-color: color-mix(in srgb, #7165e9 45%, var(--dsw-alias-border-l2)); box-shadow: 0 8px 22px rgba(28, 31, 52, .11); }
.dog-node[data-selected=true] { border-color: #7165e9; box-shadow: 0 0 0 3px color-mix(in srgb, #7165e9 14%, transparent), 0 9px 24px rgba(28,31,52,.12); }
.dog-node[data-root=true] { background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 88%, #7165e9 8%); }
.dog-node-top { display: flex; align-items: center; gap: 7px; }
.dog-node-kind { flex: 1; color: var(--dsw-alias-label-tertiary); font-size: 9px; line-height: 13px; font-weight: 700; letter-spacing: .085em; text-transform: uppercase; }
.dog-node-root { color: #6c61d6; }
.dog-node-title { margin-top: 8px; min-height: 34px; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; font-size: 12px; line-height: 17px; font-weight: 620; }
.dog-node-foot { margin-top: auto; display: flex; align-items: center; justify-content: space-between; gap: 7px; }
.dog-node-id { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); font: 9px/13px ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-status-chip { height: 19px; padding: 0 6px; color: var(--dog-state-color); background: color-mix(in srgb, var(--dog-state-color) 13%, transparent); font-size: 9px; line-height: 14px; font-weight: 700; letter-spacing: .035em; text-transform: uppercase; }
.dog-status-chip:before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: var(--dog-state-color); }
.dog-node[data-agents-expanded=true] { border-color: color-mix(in srgb, #7165e9 62%, var(--dsw-alias-border-l2)); }
.dog-node-agents { flex: none; display: inline-flex; align-items: center; gap: 3px; color: #6b60d4; font-size: 9px; line-height: 13px; font-weight: 650; }
.dog-agent-flyout { position: absolute; z-index: 8; min-height: 116px; display: flex; flex-direction: column; color: var(--dsw-alias-label-primary); background: color-mix(in srgb, var(--dsw-alias-bg-base) 96%, #7165e9 4%); border: 1px solid color-mix(in srgb, #7165e9 35%, var(--dsw-alias-border-l2)); border-radius: 13px; box-shadow: 0 14px 34px rgba(12, 16, 29, .22); overflow: hidden; }
.dog-agent-flyout-head { min-height: 35px; padding: 6px 7px 6px 9px; display: flex; align-items: center; gap: 6px; border-bottom: 1px solid var(--dsw-alias-border-l2); }
.dog-agent-flyout-head > span { min-width: 0; flex: 1; display: inline-flex; align-items: center; gap: 5px; font-size: 9.5px; line-height: 14px; font-weight: 680; }
.dog-agent-flyout-head button { width: 25px; height: 25px; border: 0; border-radius: 7px; display: grid; place-items: center; color: var(--dsw-alias-label-tertiary); background: transparent; cursor: pointer; }
.dog-agent-flyout-head button:hover { color: var(--dsw-alias-label-primary); background: var(--dsw-alias-interactive-bg-hover); }
.dog-agent-list { min-height: 0; margin: 0; padding: 5px; list-style: none; overflow: auto; }
.dog-agent-list li + li { margin-top: 3px; }
.dog-agent-row { width: 100%; min-width: 0; border: 0; border-radius: 8px; padding: 7px 6px; display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 7px; color: inherit; background: transparent; cursor: pointer; text-align: left; font: inherit; }
.dog-agent-row:hover { background: var(--dsw-alias-interactive-bg-hover); }
.dog-agent-row:disabled { cursor: wait; opacity: .66; }
.dog-agent-state { width: 7px; height: 7px; border-radius: 50%; background: var(--dog-state-color); box-shadow: 0 0 0 3px color-mix(in srgb, var(--dog-state-color) 12%, transparent); }
.dog-agent-copy, .dog-agent-metrics { min-width: 0; display: flex; flex-direction: column; }
.dog-agent-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 9.5px; line-height: 14px; font-weight: 630; }
.dog-agent-meta { color: var(--dsw-alias-label-tertiary); font-size: 8px; line-height: 12px; }
.dog-agent-metrics { align-items: flex-end; color: var(--dsw-alias-label-tertiary); font: 8px/12px ui-monospace, SFMono-Regular, Menlo, monospace; white-space: nowrap; }
.dog-agent-empty { margin: auto 0; padding: 13px 10px; color: var(--dsw-alias-label-tertiary); text-align: center; font-size: 9px; line-height: 14px; }
.dog-agent-hint { padding: 5px 8px 6px; border-top: 1px solid var(--dsw-alias-border-l2); color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); text-align: center; font-size: 7.5px; line-height: 11px; }
.dog-agent-error { padding: 5px 8px; color: #c94a45; background: color-mix(in srgb, #d5534d 7%, transparent); font-size: 8px; line-height: 12px; overflow-wrap: anywhere; }
.dog-inspector-head { display: flex; align-items: flex-start; gap: 10px; }
.dog-inspector-title-wrap { min-width: 0; flex: 1; }
.dog-inspector-eyebrow { color: var(--dsw-alias-label-tertiary); font-size: 9px; line-height: 14px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
.dog-inspector-title { margin: 3px 0 0; overflow-wrap: anywhere; font-size: 15px; line-height: 21px; font-weight: 660; }
.dog-inspector-chips { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.dog-mini-chip { height: 21px; padding: 0 7px; color: var(--dsw-alias-label-secondary); background: var(--dsw-alias-interactive-bg-hover); font-size: 9px; font-weight: 650; text-transform: uppercase; letter-spacing: .045em; }
.dog-inspector-section { margin-top: 18px; }
.dog-inspector-section-title { margin: 0 0 8px; color: var(--dsw-alias-label-tertiary); font-size: 9px; line-height: 14px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
.dog-reason { border: 1px solid color-mix(in srgb, var(--dog-state-color) 33%, var(--dsw-alias-border-l2)); border-radius: 10px; padding: 9px 10px; color: var(--dsw-alias-label-secondary); background: color-mix(in srgb, var(--dog-state-color) 7%, transparent); font-size: 11px; line-height: 17px; overflow-wrap: anywhere; }
.dog-definition { margin: 0; display: grid; grid-template-columns: minmax(82px, .7fr) minmax(0, 1.3fr); gap: 7px 9px; font-size: 10px; line-height: 16px; }
.dog-definition dt { color: var(--dsw-alias-label-tertiary); }
.dog-definition dd { min-width: 0; margin: 0; color: var(--dsw-alias-label-secondary); overflow-wrap: anywhere; }
.dog-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 9.5px; }
.dog-evidence { border: 1px solid var(--dsw-alias-border-l2); border-radius: 11px; overflow: hidden; }
.dog-evidence-head { min-height: 35px; padding: 7px 9px; display: flex; align-items: center; gap: 8px; background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 90%, #7165e9 4%); border-bottom: 1px solid var(--dsw-alias-border-l2); }
.dog-evidence-name { min-width: 0; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font: 10px/16px ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-evidence-body { padding: 8px 9px 9px; }
.dog-observation { margin: 0; display: grid; gap: 5px; }
.dog-observation-row { display: grid; grid-template-columns: minmax(76px, .75fr) minmax(0, 1.25fr); gap: 8px; font-size: 10px; line-height: 15px; }
.dog-observation-key { color: var(--dsw-alias-label-tertiary); overflow-wrap: anywhere; }
.dog-observation-value { color: var(--dsw-alias-label-secondary); overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-relation-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.dog-relation { border-left: 2px solid #857ce2; padding-left: 8px; color: var(--dsw-alias-label-secondary); font-size: 10px; line-height: 15px; }
.dog-relation[data-kind=dependsOn] { border-color: #c07a39; }
.dog-relation strong { color: var(--dsw-alias-label-primary); font-weight: 600; }
.dog-raw { border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px; overflow: hidden; }
.dog-raw summary { padding: 7px 9px; color: var(--dsw-alias-label-secondary); cursor: pointer; font-size: 10px; }
.dog-raw pre { max-height: 240px; margin: 0; padding: 9px; border-top: 1px solid var(--dsw-alias-border-l2); color: var(--dsw-alias-label-tertiary); background: color-mix(in srgb, var(--dsw-alias-bg-base) 94%, #000 6%); white-space: pre-wrap; overflow: auto; font: 9px/15px ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-runtime-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.dog-runtime-heading .dog-inspector-section-title { margin-bottom: 8px; }
.dog-runtime-live { display: inline-flex; align-items: center; gap: 5px; color: #3c7fe1; font-size: 9px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.dog-runtime-pulse { width: 6px; height: 6px; border-radius: 50%; background: #3c7fe1; box-shadow: 0 0 0 0 rgba(60,127,225,.35); animation: dog-runtime-pulse 1.5s ease-out infinite; }
.dog-runtime-card { min-width: 0; border: 1px solid color-mix(in srgb, var(--dog-state-color) 25%, var(--dsw-alias-border-l2)); border-radius: 11px; padding: 9px 10px; display: flex; align-items: center; gap: 9px; background: color-mix(in srgb, var(--dog-state-color) 6%, var(--dsw-alias-bg-base)); }
.dog-runtime-orb { width: 10px; height: 10px; flex: none; border-radius: 50%; background: var(--dog-state-color); box-shadow: 0 0 0 4px color-mix(in srgb, var(--dog-state-color) 13%, transparent); }
.dog-runtime-card-copy { min-width: 0; }
.dog-runtime-activity { color: var(--dsw-alias-label-primary); overflow-wrap: anywhere; font-size: 11px; line-height: 16px; font-weight: 620; }
.dog-runtime-meta { margin-top: 2px; color: var(--dsw-alias-label-tertiary); font-size: 9px; line-height: 14px; }
.dog-runtime-warning { margin-top: 7px; border: 1px solid color-mix(in srgb, #d18135 28%, var(--dsw-alias-border-l2)); border-radius: 9px; padding: 7px 8px; color: #b66d28; background: color-mix(in srgb, #d18135 7%, transparent); overflow-wrap: anywhere; font-size: 9.5px; line-height: 15px; }
.dog-runtime-error { margin-top: 8px; border-left: 3px solid var(--dog-state-color); border-radius: 8px; padding: 8px 9px; display: flex; flex-direction: column; gap: 3px; color: var(--dsw-alias-label-secondary); background: color-mix(in srgb, var(--dog-state-color) 8%, transparent); font-size: 9.5px; line-height: 15px; overflow-wrap: anywhere; }
.dog-runtime-error strong { color: var(--dog-state-color); font-size: 9px; letter-spacing: .035em; text-transform: uppercase; }
.dog-runtime-session { margin-top: 8px; border: 1px solid var(--dsw-alias-border-l2); border-radius: 10px; padding: 8px 9px; background: color-mix(in srgb, var(--dsw-alias-bg-layer-3, var(--dsw-alias-bg-base)) 92%, #7165e9 3%); }
.dog-runtime-session-head { margin-bottom: 7px; display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--dsw-alias-label-secondary); font-size: 10px; font-weight: 620; }
.dog-runtime-session-button { flex: none; border: 1px solid color-mix(in srgb, #7165e9 32%, var(--dsw-alias-border-l2)); border-radius: 7px; padding: 4px 7px; color: #655acb; background: color-mix(in srgb, #7165e9 8%, var(--dsw-alias-bg-base)); cursor: pointer; font: 600 9px/13px inherit; }
.dog-runtime-session-button:hover { background: color-mix(in srgb, #7165e9 15%, var(--dsw-alias-bg-base)); }
.dog-runtime-session-button:disabled { cursor: wait; opacity: .62; }
.dog-runtime-session-error { margin-top: 7px; color: #c94a45; font-size: 9px; line-height: 14px; overflow-wrap: anywhere; }
.dog-runtime-empty { margin: 8px 0 0; }
.dog-runtime-timeline { margin: 10px 0 0; padding: 0; list-style: none; }
.dog-runtime-event { --dog-runtime-line: color-mix(in srgb, var(--dog-state-color) 32%, var(--dsw-alias-border-l2)); position: relative; min-width: 0; padding: 0 0 12px 19px; }
.dog-runtime-event:not(:last-child):before { content: ''; position: absolute; left: 4px; top: 10px; bottom: 0; width: 1px; background: var(--dog-runtime-line); }
.dog-runtime-marker { position: absolute; left: 0; top: 4px; width: 9px; height: 9px; border: 2px solid var(--dsw-alias-bg-base); border-radius: 50%; background: var(--dog-state-color); box-shadow: 0 0 0 1px var(--dog-runtime-line); }
.dog-runtime-event-copy { min-width: 0; }
.dog-runtime-event-head { min-width: 0; display: flex; align-items: baseline; justify-content: space-between; gap: 7px; color: var(--dsw-alias-label-secondary); font-size: 9.5px; line-height: 14px; }
.dog-runtime-event-head strong { min-width: 0; overflow-wrap: anywhere; font-weight: 620; }
.dog-runtime-event-head time { flex: none; color: var(--dsw-alias-label-tertiary); font-size: 8.5px; }
.dog-runtime-event-meta { margin-top: 1px; color: var(--dsw-alias-label-caption, var(--dsw-alias-label-tertiary)); font: 8px/12px ui-monospace, SFMono-Regular, Menlo, monospace; }
.dog-runtime-event-detail { margin-top: 3px; color: var(--dsw-alias-label-tertiary); overflow-wrap: anywhere; font-size: 9px; line-height: 14px; }
.dog-runtime-raw { margin-top: 4px; }
.dog-empty { grid-column: 1 / -1; min-height: 320px; display: grid; place-items: center; padding: 40px; text-align: center; }
.dog-empty-card { max-width: 380px; }
.dog-empty-icon { width: 48px; height: 48px; margin: 0 auto 13px; border-radius: 16px; display: grid; place-items: center; color: #7165e9; background: color-mix(in srgb, #7165e9 12%, transparent); }
.dog-empty-title { margin: 0; font-size: 15px; line-height: 22px; font-weight: 650; }
.dog-empty-copy { margin: 6px 0 0; color: var(--dsw-alias-label-tertiary); font-size: 11px; line-height: 18px; }
.dog-error-banner { margin: 12px 18px 0; border: 1px solid color-mix(in srgb, #d5534d 35%, var(--dsw-alias-border-l2)); border-radius: 10px; padding: 8px 10px; color: #c94a45; background: color-mix(in srgb, #d5534d 8%, transparent); font-size: 11px; line-height: 17px; }
.dog-loading { opacity: .65; }
.dog-state-success { --dog-state-color: #1c9a69; }
.dog-state-failure { --dog-state-color: #d5534d; }
.dog-state-needs_human { --dog-state-color: #d18135; }
.dog-state-partial { --dog-state-color: #b88a22; }
.dog-state-blocked, .dog-state-cancelled, .dog-state-invalidated { --dog-state-color: #828b97; }
.dog-state-running { --dog-state-color: #3c7fe1; }
.dog-state-pending, .dog-state-created { --dog-state-color: #8c859f; }
.dog-state-partial_success { --dog-state-color: #b88a22; }
.dog-state-infeasible, .dog-state-needs_replan { --dog-state-color: #d18135; }
.dog-root-orb { background: var(--dog-state-color); box-shadow: 0 7px 18px color-mix(in srgb, var(--dog-state-color) 26%, transparent); }
@keyframes dog-fade-in { from { opacity: 0; } }
@keyframes dog-dialog-in { from { opacity: 0; transform: translateY(8px) scale(.992); } }
@keyframes dog-runtime-pulse { 70%, 100% { box-shadow: 0 0 0 6px rgba(60,127,225,0); } }
@keyframes dog-spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) {
  .dog-workspace { grid-template-columns: 220px minmax(0, 1fr) 292px; }
  .dog-summary { grid-template-columns: minmax(170px, 1fr) repeat(4, minmax(76px, 92px)); gap: 7px; }
}
@media (min-width: 981px) and (max-width: 1080px) {
  .dog-workspace { grid-template-columns: 190px minmax(0, 1fr) 270px; }
  .dog-summary { grid-template-columns: minmax(160px, 1fr) repeat(3, minmax(72px, 84px)); }
  .dog-metric:last-child { display: none; }
}
@media (max-width: 980px) {
  .dog-dialog { width: 100%; height: 100dvh; min-height: 0; }
  .dog-workspace { grid-template-columns: 210px minmax(0, 1fr); }
  .dog-inspector { position: absolute; z-index: 3; top: 0; right: 0; bottom: 0; width: min(330px, 84%); box-shadow: -16px 0 36px rgba(7, 10, 18, .16); }
  .dog-summary { grid-template-columns: minmax(170px, 1fr) repeat(3, minmax(72px, 88px)); }
  .dog-metric:last-child { display: none; }
}
@media (max-width: 720px) {
  .dog-overlay-root[data-dog-dock-layout=floating] .dog-dock { top: 64px; right: 8px; bottom: auto; width: calc(100vw - 16px); max-height: min(286px, calc(100dvh - 72px)); }
  .dog-workspace { grid-template-columns: 1fr; }
  .dog-sidebar { display: none; }
  .dog-header-divider, .dog-brand-subtitle, .dog-sync-copy { display: none; }
  .dog-summary { grid-template-columns: minmax(145px, 1fr) repeat(2, minmax(66px, 76px)); padding-inline: 10px; }
  .dog-metric:nth-of-type(n+4) { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .dog-launcher, .dog-node, .dog-backdrop, .dog-dialog, .dog-runtime-pulse { animation: none; transition: none; }
}
`
