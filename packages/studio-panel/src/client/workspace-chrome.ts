/**
 * Browser chrome the OpenWrite workbench owns inside the host conversation shell.
 *
 * The host parks its composer in a seat element (`[data-composer-seat]`) inside
 * the conversation scroller (`[data-conversation-scroll]`). The seat is what
 * pushed the workbench's bottom edge up: the host reserved the seat's band out
 * of the content area, so our panel stopped short of the viewport bottom and
 * left a bare white slab under the composer — a flat white strip, not a
 * composer floating over the workbench.
 *
 * The OpenWrite workbench is a full-screen surface, not a chat transcript: it
 * has its own navigation, its own panes and its own scrolling. A centered
 * composer card floating over that layout covers real content (the outline
 * card was cut in half by it). So the seat is hidden while one of our views is
 * mounted and the workbench takes the whole content area.
 *
 * The host exposes no slot for "hide the composer". `conversation.composer` is
 * a chain, but a chain selector can only read session state, not the active
 * view, and it runs before the view mounts — so it cannot answer "is this our
 * view?" at the moment it is asked. A `:has()` rule over the host's own stable
 * data attributes is the one hook that reacts to the mounted view, and it is
 * scoped to our pages: the host's Chat and Trajectory views keep their
 * composer because they never carry the marker.
 */

/** Marker attribute carried by the root element of every OpenWrite workbench view. */
export const WORKSPACE_MARKER_ATTRIBUTE = 'data-openwrite-workspace'

/**
 * The rule that hides the host composer seat while an OpenWrite view is mounted.
 *
 * `:has()` matches the scroller that *contains* a workbench marker, and the
 * direct-child combinator pins the rule to that scroller's own seat, so a seat
 * belonging to some other scroller is never touched.
 */
export const WORKSPACE_CHROME_CSS = `[data-conversation-scroll]:has([${WORKSPACE_MARKER_ATTRIBUTE}]) > [data-composer-seat] { display: none; }`

/** Id of the injected `<style>` element, so the injection stays idempotent. */
const STYLE_ELEMENT_ID = 'openwrite-workspace-chrome'

/**
 * Install the workbench chrome stylesheet once per document.
 *
 * Safe to call from every client activation: the second call finds the
 * existing element and returns.
 */
export function installWorkspaceChromeStyles(): void {
  if (typeof document === 'undefined') return
  if (document.getElementById(STYLE_ELEMENT_ID) !== null) return
  const style = document.createElement('style')
  style.id = STYLE_ELEMENT_ID
  style.textContent = WORKSPACE_CHROME_CSS
  document.head.append(style)
}
