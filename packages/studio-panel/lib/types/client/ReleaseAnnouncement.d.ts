/**
 * Once-per-version-update announcement & open-source support modal for OpenWrite.
 *
 * Displays once in the browser after each OpenWrite version upgrade (tracked in
 * `localStorage` under `openwrite.seenReleaseVersion`) and can also be opened on
 * demand from 「设置 → OpenWrite → 环境」.
 *
 * Features exclusively OpenWrite (`https://github.com/LiPu-jpg/Openwrite`) and
 * privacy-safe feedback links (never novel titles, manuscripts, settings, local
 * paths, or API keys).
 */
import { type StudioPanelKey } from './locales.ts';
/** Canonical GitHub repository URL for OpenWrite. */
export declare const OPENWRITE_REPO_URL = "https://github.com/LiPu-jpg/Openwrite";
/** localStorage key recording the last acknowledged OpenWrite release version. */
export declare const SEEN_RELEASE_VERSION_KEY = "openwrite.seenReleaseVersion";
/** Attribute marking the mounted release announcement scrim in `document.body`. */
export declare const RELEASE_MODAL_MARKER = "data-openwrite-release-modal";
export interface ReleaseAnnouncementOptions {
    t?: (key: StudioPanelKey) => string;
    version?: string;
    issueUrl?: string;
    onClose?: () => void;
    allowWebdriver?: boolean;
}
/**
 * Resolve the current OpenWrite release version stamped at build time.
 */
export declare function resolveOpenWriteVersion(): string;
/**
 * Check whether the user has already seen and dismissed the announcement for `version`.
 */
export declare function hasSeenReleaseAnnouncement(version?: string): boolean;
/**
 * Record that the user has seen the announcement for `version`.
 */
export declare function markReleaseAnnouncementSeen(version?: string): void;
/**
 * Build a default privacy-safe GitHub issue URL containing only the OpenWrite version.
 */
export declare function buildDefaultReleaseIssueUrl(version?: string): string;
/**
 * Render and mount the OpenWrite release announcement modal onto `document.body`.
 * Closing or clicking any action marks `version` as seen in `localStorage`.
 */
export declare function showReleaseAnnouncementModal(options?: ReleaseAnnouncementOptions): HTMLElement | null;
/**
 * Show the OpenWrite release announcement modal automatically if and only if
 * the current release version has not been acknowledged in `localStorage`.
 */
export declare function maybeShowReleaseAnnouncement(options?: ReleaseAnnouncementOptions): HTMLElement | null;
