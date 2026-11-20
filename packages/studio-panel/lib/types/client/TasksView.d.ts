import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
export interface NavigationRequest {
    view: 'benchmark' | 'research';
    id: string;
}
export type TasksViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
    onNavigate?: (target: NavigationRequest) => void;
};
export declare function TasksView({ fetchStudioApi, postStudioApi, t, onNavigate }: TasksViewProps): import("react").JSX.Element;
