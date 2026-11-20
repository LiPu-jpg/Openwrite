import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
export type LibraryViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>;
/** One native library shell over canon, outline, continuity, research and search. */
export declare function LibraryView(props: LibraryViewProps): import("react").JSX.Element;
