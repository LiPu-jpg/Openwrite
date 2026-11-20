/**
 * Companion-plugin status: whether the optional integrations (dsh-dog,
 * dsh-ops, dsh-our-free-model) are installed and usable on this host. The
 * section only explains what a companion does here; the one action it offers
 * is writing an OpenWrite model profile that points at the free-model plugin's
 * local gateway.
 *
 * The model profile library is global — Studio keeps it outside every
 * project — so this section reaches it through the context-free global API.
 * The wiring therefore works from the host's settings dialog, with no novel
 * open.
 */
export interface CompanionPluginInfo {
    key: 'dog' | 'ops' | 'freeModel';
    name: string;
    npmPackage: string;
    repo: string;
    url: string;
    roleZh: string;
    roleEn: string;
}
/**
 * The three DSH ecosystem companion plugins OpenWrite natively integrates with.
 * Used in both Settings → Host and the once-per-version release modal.
 */
export declare const COMPANION_PLUGINS: readonly CompanionPluginInfo[];
export interface OpsPlan {
    files: boolean;
    discovery: boolean;
    presentation: string;
    shell: boolean;
    replaceOfficial: boolean;
    residentTools: boolean;
    residentNames: number;
}
export interface CompanionEntry {
    installed: boolean;
    usable: boolean;
    version: string | null;
    reason: string | null;
    /** The resolved dsh-ops integration plan, when the companion exposes one. */
    plan?: OpsPlan | null;
}
export interface CompanionStatus {
    host: string | null;
    dog: CompanionEntry;
    ops: CompanionEntry;
    freeModel: CompanionEntry;
}
export declare function fetchCompanions(signal?: AbortSignal): Promise<CompanionStatus | null>;
/**
 * The route entries that still point somewhere else. Sending only these keys
 * leaves planning/search/research routes exactly as the author set them.
 */
export declare function routeChanges(routes: Record<string, string>, profileId?: string): Record<string, string>;
/** Human-readable current routes, for the pre-write summary. */
export declare function routeSummary(routes: Record<string, string>): string;
export declare function CompanionSection({ status }: {
    status: CompanionStatus | null;
}): JSX.Element | null;
