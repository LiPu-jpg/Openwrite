import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots';
import type { StudioApiInjected } from './api.ts';
import { type StudioPanelInjected } from './workspace-context.ts';
type HeaderProps = PropsRuntime<'conversation.session.header.actions'> & PropsLocale<'studio-panel'>;
type UtilityProps = PropsRuntime<'conversation.session.header.utilities'> & PropsLocale<'studio-panel'> & Pick<StudioApiInjected, 'postStudioApi'>;
type ContextChipProps = PropsRuntime<'conversation.input.left'> & PropsLocale<'studio-panel'> & Pick<StudioPanelInjected, 'postStudioApi' | 'workspaces' | 'sessions'>;
export declare function HeaderProjectStatus({ t }: HeaderProps): import("react").JSX.Element;
export declare function HeaderUtilities({ postStudioApi, t }: UtilityProps): import("react").JSX.Element;
/**
 * Input-bar Workspace chip: reflects the session's dsh Workspace binding and
 * owns binding it into the WorkbenchStore context barrier. When the binding
 * needs action it is a button opening a small popover: an unbound session
 * gets the directory-pick attach flow; a bound-but-uninitialized workspace
 * gets the inline init form (novel id + title, pinned to the canonical
 * path). An initialized workspace renders read-only.
 */
export declare function WorkspaceContextChip(props: ContextChipProps): import("react").JSX.Element;
export {};
