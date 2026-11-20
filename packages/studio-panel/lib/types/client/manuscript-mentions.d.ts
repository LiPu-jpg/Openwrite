/** Registered people/places that can become 提及 in the open chapter. */
export type MentionAsset = {
    kind: string;
    id: string;
    name: string;
    summary: string;
    aliases: string[];
};
export type MentionSpan = {
    start: number;
    end: number;
    text: string;
    candidates: MentionAsset[];
};
export declare function isPersonOrPlaceKind(kind: string): boolean;
export declare function isCharacterKind(kind: string): boolean;
/** Characters for marker insert. Homonyms stay distinct by id. */
export declare function characterChoices(assets: readonly MentionAsset[]): MentionAsset[];
export declare function characterMatches(assets: readonly MentionAsset[], label: string): MentionAsset[];
/** Homonyms require an explicit id; a unique match may be used without one. */
export declare function resolveCharacterChoice(assets: readonly MentionAsset[], selectedId: string, label?: string): MentionAsset | null;
/** Unwrap Studio GET /assets into character and location summaries. */
export declare function parseMentionAssets(value: unknown): MentionAsset[];
/** One chip per unambiguous asset, or per conflicting label/candidate set. */
export declare function uniqueMentionAssets(spans: readonly MentionSpan[]): MentionSpan[];
/**
 * Non-overlapping name/alias hits in manuscript order.
 * Longer labels win; identical labels retain every candidate without guessing identity.
 */
export declare function findManuscriptMentions(text: string, assets: readonly MentionAsset[]): MentionSpan[];
