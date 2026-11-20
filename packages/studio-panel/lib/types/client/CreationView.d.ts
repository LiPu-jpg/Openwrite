import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import { type StudioApiInjected } from './api.ts';
export type CreationViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>;
/** Native manuscript workbench: chapter rail, local Vditor editor and inspector. */
export declare function CreationView(props: CreationViewProps): import("react").JSX.Element;
