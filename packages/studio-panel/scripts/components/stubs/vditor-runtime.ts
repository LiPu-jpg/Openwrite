/** Controllable engine delay; tests exercise the real VditorBody lifecycle. */
export const instances: DeferredVditor[] = []
export const installVditorIcons = () => {}

export default class DeferredVditor {
  readonly element = document.createElement('textarea')
  destroyed = false
  constructor(readonly host: HTMLElement, readonly options: Record<string, unknown>) {
    this.element.setAttribute('aria-label', 'Live asset body')
    this.element.value = String(options['value'] ?? '')
    host.append(this.element)
    instances.push(this)
    queueMicrotask(() => { if (!this.destroyed) (options['after'] as () => void)() })
  }
  getValue() {
    if (!this.host.isConnected) throw new Error('Editor DOM already detached')
    return this.element.value
  }
  getSelection() {
    return this.element.value.slice(this.element.selectionStart, this.element.selectionEnd)
  }
  insertValue(value: string) {
    const start = this.element.selectionStart
    const end = this.element.selectionEnd
    this.element.value = `${this.element.value.slice(0, start)}${value}${this.element.value.slice(end)}`
    const caret = start + value.length
    this.element.setSelectionRange(caret, caret)
    this.deliverInput()
  }
  deliverInput() { (this.options['input'] as (value: string) => void)(this.element.value) }
  setTheme() {}
  destroy() { this.destroyed = true; this.element.remove() }
}
