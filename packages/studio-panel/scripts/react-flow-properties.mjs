/** Keep the minimap overlay's CSS definitions and JS references in sync.
 * This only renames CSS custom properties; it never rewrites credential data.
 */
export function normalizeMinimapProperties(source) {
  return source.replaceAll('--xy-minimap-mask-', '--xy-minimap-overlay-')
}
