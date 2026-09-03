import { jsx as _jsx } from "react/jsx-runtime";
import css from './ConnectionBanner.module.css';
/**
 * Render the reconnecting banner.
 * @param props.reconnecting - true while the connection is in backoff/retry.
 * @param props.label - banner text; the owner passes localized copy (this
 * package is cordis-free, so copy arrives via props).
 * @returns the banner, or null when connected.
 */
export function ConnectionBanner({ reconnecting, label }) {
    if (!reconnecting)
        return null;
    return _jsx("div", { className: css.banner, children: label });
}
//# sourceMappingURL=ConnectionBanner.js.map