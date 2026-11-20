import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type StudioPanelInjected } from './workspace-context.ts';
export type OperationsViewProps = ConvViewProps & InjectFace<StudioPanelInjected> & PropsLocale<'studio-panel'>;
/** Background jobs plus the less frequent transfer/maintenance commands. */
export declare function OperationsView(props: OperationsViewProps): import("react").JSX.Element;
