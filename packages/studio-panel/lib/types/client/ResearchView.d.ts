import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
export type ResearchViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
    initialReportId?: string;
};
export declare function ResearchView({ fetchStudioApi, postStudioApi, t, initialReportId }: ResearchViewProps): import("react").JSX.Element;
