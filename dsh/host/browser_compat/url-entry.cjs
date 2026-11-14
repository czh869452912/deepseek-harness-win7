/* Chromium before M130 treats non-special hierarchical URLs as opaque paths.
 * Keep compliant browsers untouched. Use the complete, licensed URL parser,
 * search parameters and matching Fetch/Request integration in older realms.
 * https://groups.google.com/a/chromium.org/g/blink-dev/c/svzicLXbKjw
 */
if (typeof URL === 'function' && new URL('dsh-resource://file/session/s/x').hostname !== 'file') {
  require('core-js/modules/web.url.constructor');
  require('core-js/modules/web.url.can-parse');
  require('core-js/modules/web.url.parse');
}
// The unchanged pinned PDF.js runtime uses these APIs in both document and
// Worker realms. Preserve implementations already supplied by the browser.
if (typeof Promise.try !== 'function') require('core-js/modules/es.promise.try');
if (typeof Math.sumPrecise !== 'function') require('core-js/modules/es.math.sum-precise');
if (typeof Uint8Array.fromBase64 !== 'function') require('core-js/modules/es.uint8-array.from-base64');
if (typeof Uint8Array.prototype.toHex !== 'function') require('core-js/modules/es.uint8-array.to-hex');
if (typeof Uint8Array.prototype.toBase64 !== 'function') require('core-js/modules/es.uint8-array.to-base64');
if (typeof Map.prototype.getOrInsertComputed !== 'function') require('core-js/modules/es.map.get-or-insert-computed');
if (typeof Map.prototype.getOrInsert !== 'function') require('core-js/modules/es.map.get-or-insert');
if (typeof Set.prototype.intersection !== 'function') require('core-js/modules/es.set.intersection.v2');
if (typeof ArrayBuffer.prototype.transferToFixedLength !== 'function') require('core-js/modules/es.array-buffer.transfer-to-fixed-length');
// The 0.2.2 model provider picker sorts a copy while retaining catalog order.
if (typeof Array.prototype.toSorted !== 'function') require('core-js/modules/es.array.to-sorted');
