// Real vendored Vditor; only callback delivery can be paused to reproduce
// backgrounding before the engine's delayed input reaches the application.
export default class MobileTestVditor extends window.Vditor {
  constructor(host, options) {
    super(host, { ...options, input: value => {
      const deliver = () => options.input?.(value)
      if (window.mobileHoldInput) window.mobilePendingInput.push(deliver)
      else deliver()
    } })
  }
}
export const installVditorIcons = () => {}
