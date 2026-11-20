import type { ToolCallViewProps } from '@deepseek-ai/dsh-client-ui-tool/client';
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
export type ToolFamily = 'status' | 'context' | 'manuscript' | 'revision' | 'task' | 'search' | 'asset' | 'outline';
type CardProps = ToolCallViewProps & PropsLocale<'studio-panel'> & {
    family: ToolFamily;
};
export declare function DomainToolCard({ block, callId, toolName, family, openFile, t }: CardProps): import("react").JSX.Element;
export declare function createDomainToolCard(family: ToolFamily): (props: ToolCallViewProps & PropsLocale<"studio-panel">) => import("react").JSX.Element;
export {};
