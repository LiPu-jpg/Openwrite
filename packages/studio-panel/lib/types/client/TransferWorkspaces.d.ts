import { type Dispatch, type SetStateAction } from 'react';
import type { OperationsViewProps } from './OperationsView.tsx';
import type { StudioPanelInjected } from './workspace-context.ts';
type TransferT = OperationsViewProps['t'];
type Note = (message: string, bad?: boolean) => void;
interface WorkspaceProps extends Pick<StudioPanelInjected, 'fetchStudioApi' | 'postStudioApi'> {
    t: TransferT;
    busy: string;
    setBusy: Dispatch<SetStateAction<string>>;
    say: Note;
    workspaceReady: boolean;
    tasksEpoch: number;
    workspaceEpoch: number;
}
interface ArchiveWorkspaceProps extends WorkspaceProps, Pick<StudioPanelInjected, 'workspaces'> {
}
export declare function ManuscriptImportWorkspace(props: WorkspaceProps): import("react").JSX.Element;
export declare function ProjectArchiveWorkspace(props: ArchiveWorkspaceProps): import("react").JSX.Element;
export {};
