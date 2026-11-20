import type { OperationsViewProps } from './OperationsView.tsx';
type Props = Pick<OperationsViewProps, 'fetchStudioApi' | 'postStudioApi' | 't'> & {
    onSaved: () => void;
};
export declare function ProjectMetadataEditor({ fetchStudioApi, postStudioApi, t, onSaved }: Props): import("react").JSX.Element;
export {};
