import type { ConversationNodeDefinition } from '@deepseek-ai/dsh-client-ui-conversation/client';
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
export interface NovelMutationItem {
    callId: string;
    tool: string;
    /** For a merged tool: which operation the call asked for. */
    planKind?: string;
    label: string;
    path: string;
    status: 'succeeded' | 'partial' | 'failed' | 'refresh_failed' | 'proposed' | 'rejected';
    errorCode: string;
    historyVersionId: string;
    revision: string;
    sourceRevision: string;
    resultRevision: string;
    changes: readonly NovelEntityChange[];
    previewToken: string;
    undoPreviewToken: string;
    traceId?: string;
    tracePath?: string;
    modelCallCount?: number;
    traceRetentionDays?: number;
}
export interface NovelMutationValue {
    kind: 'missing' | 'text' | 'boolean' | 'number' | 'null' | 'list' | 'object';
    value: unknown;
    preview: string;
    truncated: boolean;
    units: number;
    sha256: string;
}
export interface NovelEntityChange {
    changeId: string;
    entityKind: string;
    entityId: string;
    path: string;
    field: string;
    before: NovelMutationValue;
    after: NovelMutationValue;
    sourceRevision: string;
    resultRevision: string;
    executionStatus: string;
}
export interface NovelMutationSummary {
    items: readonly NovelMutationItem[];
}
interface MutationState {
    turn: number;
    calls: Readonly<Record<string, NovelMutationItem>>;
    items: readonly NovelMutationItem[];
}
declare module '@deepseek-ai/dsh-client-ui-conversation/client' {
    interface ConversationTurnDataMap {
        'dsh-novel-mutations': NovelMutationSummary;
    }
}
/** State-only durable event definition feeding the native Turn-tail summary. */
export declare const novelMutationDefinition: ConversationNodeDefinition<MutationState>;
type TurnSummaryProps = PropsRuntime<'conversation.chat.turnTail'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'> & {
    matched: NovelMutationSummary;
};
/** DSH 0.2 dispatches turnTail as a list; the component owns its selection. */
export declare function TurnMutationSummaryListView(props: Omit<TurnSummaryProps, 'matched'> & {
    turn: {
        data: {
            get(key: 'dsh-novel-mutations'): NovelMutationSummary | undefined;
        };
    };
}): import("react").JSX.Element | null;
export declare function TurnMutationSummaryView({ matched, openFile, postStudioApi, t }: TurnSummaryProps): import("react").JSX.Element;
export {};
