/** Package-owned invariant companion for the Team Web presentation. */
import type { Context } from '@deepseek-ai/cordis';
/** Cordis companion plugin name. */
export declare const name = "client-ui-agent-team-invariant";
/** Invariant registry dependency. */
export declare const inject: string[];
/**
 * Register this package's invariant ownership.
 * @param ctx - Cordis Context carrying the invariant registry.
 * @returns disposer for the package registration.
 */
export declare const apply: (ctx: Context) => Promise<() => void>;
//# sourceMappingURL=invariant.d.ts.map