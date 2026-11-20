import z from '@deepseek-ai/schemastery';
import type { Context } from '@deepseek-ai/cordis';
export declare const name = "@dsh-novel/openwrite-tools";
export declare const inject: string[];
export declare const Config: z<Schemastery.ObjectS<{
    presentation: z<"native" | "ptc" | "both", "native" | "ptc" | "both">;
}>, Schemastery.ObjectT<{
    presentation: z<"native" | "ptc" | "both", "native" | "ptc" | "both">;
}>>;
/** This row belongs in an Agent preset, never in the host bundle. */
export declare function apply(ctx: Context, config?: {
    presentation?: 'native' | 'ptc' | 'both';
}): void;
