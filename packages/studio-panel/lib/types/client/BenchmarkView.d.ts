import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
type BenchmarkViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'> & {
    initialRunId?: string;
    refreshEpoch?: number;
};
export declare function BenchmarkView({ fetchStudioApi, postStudioApi, t, initialRunId, refreshEpoch }: BenchmarkViewProps): import("react").JSX.Element;
export {};
