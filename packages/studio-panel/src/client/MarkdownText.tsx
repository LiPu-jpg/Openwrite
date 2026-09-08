import { MarkdownText as HostMarkdown, type MarkdownLabels } from '@deepseek-ai/dsh-client-ui-primitives'
import type { ComponentProps } from 'react'
const labels: MarkdownLabels = { code: { copyLabel: '复制', copiedLabel: '已复制' }, footnotes: '脚注' }
export function MarkdownText(props: Omit<ComponentProps<typeof HostMarkdown>, 'labels'>) {
  return <HostMarkdown {...props} labels={labels} />
}
