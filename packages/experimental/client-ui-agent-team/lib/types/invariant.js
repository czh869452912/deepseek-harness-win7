/** Package-owned invariant companion for the Team Web presentation. */
const PACKAGE_NAME = '@deepseek-ai/dsh-experimental-client-ui-agent-team';
/** Cordis companion plugin name. */
export const name = 'client-ui-agent-team-invariant';
/** Invariant registry dependency. */
export const inject = ['invariants'];
/** No runtime invariant: RPC is authoritative and the package owns only one disposable slot registration. */
const install = () => { };
/**
 * Register this package's invariant ownership.
 * @param ctx - Cordis Context carrying the invariant registry.
 * @returns disposer for the package registration.
 */
export const apply = (ctx) => Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install));
//# sourceMappingURL=invariant.js.map