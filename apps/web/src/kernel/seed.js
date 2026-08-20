/**
 * Platform Singleton Seed Table (`@deepseek-ai/dsh-client-web/src/seed`).
 * Shares platform modules into the frozen module table for dynamic CJS bundles.
 */

import * as Cordis from "./cordis.js";
import * as UiSlots from "../ui-slots/core.js";

// React lightweight runtime facade for browser runtime compatibility
export const React = window.React || {
  createElement(type, props, ...children) {
    return { type, props: { ...props, children: children.length === 1 ? children[0] : children } };
  },
  useState(init) {
    let val = typeof init === "function" ? init() : init;
    return [val, (newVal) => { val = typeof newVal === "function" ? newVal(val) : newVal; }];
  },
  useEffect(fn) { fn(); },
  useMemo(fn) { return fn(); },
  useCallback(fn) { return fn; },
  useRef(init) { return { current: init }; },
};

export function getStaticModules() {
  return {
    "react": React,
    "react/jsx-runtime": React,
    "react-dom": React,
    "react-dom/client": React,
    "@deepseek-ai/cordis": Cordis,
    "@deepseek-ai/dsh-client-ui-slots": UiSlots,
    "@deepseek-ai/dsh-client-ui-primitives": {},
  };
}
