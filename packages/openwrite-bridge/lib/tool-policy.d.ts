import type { Context } from '@deepseek-ai/cordis';
import type { ToolExecution } from '@deepseek-ai/dsh-tools';
export type NovelEffect = 'read' | 'write' | 'generate';
/** Unknown and preview operations fail closed: previews can persist confirmation records. */
export declare function novelEffect(name: string, args: unknown): NovelEffect;
export declare function novelPolicyDenial(ctx: Context, execution: Readonly<ToolExecution>): string | undefined;
