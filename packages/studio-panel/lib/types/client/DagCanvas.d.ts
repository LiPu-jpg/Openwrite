import 'dsh-react-flow-style';
import type { PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
interface ReviewDagViewProps {
    fetchStudioApi: StudioApiInjected['fetchStudioApi'];
    postStudioApi: StudioApiInjected['postStudioApi'];
    kind: 'review' | 'delivery';
    t: PropsLocale<'studio-panel'>['t'];
}
export declare function ReviewDagView({ fetchStudioApi, postStudioApi, kind, t }: ReviewDagViewProps): import("react").JSX.Element;
export {};
