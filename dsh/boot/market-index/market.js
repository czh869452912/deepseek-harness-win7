var __marketIndex = (() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __esm = (fn, res, err) => function __init() {
    if (err) throw err[0];
    try {
      return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
    } catch (e) {
      throw err = [e], e;
    }
  };
  var __commonJS = (cb, mod) => function __require() {
    try {
      return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
    } catch (e) {
      throw mod = 0, e;
    }
  };
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/constants.js
  var require_constants = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/constants.js"(exports, module) {
      "use strict";
      var SEMVER_SPEC_VERSION = "2.0.0";
      var MAX_LENGTH = 256;
      var MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER || /* istanbul ignore next */
      9007199254740991;
      var MAX_SAFE_COMPONENT_LENGTH = 16;
      var MAX_SAFE_BUILD_LENGTH = MAX_LENGTH - 6;
      var RELEASE_TYPES = [
        "major",
        "premajor",
        "minor",
        "preminor",
        "patch",
        "prepatch",
        "prerelease"
      ];
      module.exports = {
        MAX_LENGTH,
        MAX_SAFE_COMPONENT_LENGTH,
        MAX_SAFE_BUILD_LENGTH,
        MAX_SAFE_INTEGER,
        RELEASE_TYPES,
        SEMVER_SPEC_VERSION,
        FLAG_INCLUDE_PRERELEASE: 1,
        FLAG_LOOSE: 2
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/debug.js
  var require_debug = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/debug.js"(exports, module) {
      "use strict";
      var debug = typeof process === "object" && process.env && process.env.NODE_DEBUG && /\bsemver\b/i.test(process.env.NODE_DEBUG) ? (...args) => console.error("SEMVER", ...args) : () => {
      };
      module.exports = debug;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/re.js
  var require_re = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/re.js"(exports, module) {
      "use strict";
      var {
        MAX_SAFE_COMPONENT_LENGTH,
        MAX_SAFE_BUILD_LENGTH,
        MAX_LENGTH
      } = require_constants();
      var debug = require_debug();
      exports = module.exports = {};
      var re = exports.re = [];
      var safeRe = exports.safeRe = [];
      var src = exports.src = [];
      var safeSrc = exports.safeSrc = [];
      var t = exports.t = {};
      var R = 0;
      var LETTERDASHNUMBER = "[a-zA-Z0-9-]";
      var safeRegexReplacements = [
        ["\\s", 1],
        ["\\d", MAX_LENGTH],
        [LETTERDASHNUMBER, MAX_SAFE_BUILD_LENGTH]
      ];
      var makeSafeRegex = (value) => {
        for (const [token, max] of safeRegexReplacements) {
          value = value.split(`${token}*`).join(`${token}{0,${max}}`).split(`${token}+`).join(`${token}{1,${max}}`);
        }
        return value;
      };
      var createToken = (name, value, isGlobal) => {
        const safe = makeSafeRegex(value);
        const index = R++;
        debug(name, index, value);
        t[name] = index;
        src[index] = value;
        safeSrc[index] = safe;
        re[index] = new RegExp(value, isGlobal ? "g" : void 0);
        safeRe[index] = new RegExp(safe, isGlobal ? "g" : void 0);
      };
      createToken("NUMERICIDENTIFIER", "0|[1-9]\\d*");
      createToken("NUMERICIDENTIFIERLOOSE", "\\d+");
      createToken("NONNUMERICIDENTIFIER", `\\d*[a-zA-Z-]${LETTERDASHNUMBER}*`);
      createToken("MAINVERSION", `(${src[t.NUMERICIDENTIFIER]})\\.(${src[t.NUMERICIDENTIFIER]})\\.(${src[t.NUMERICIDENTIFIER]})`);
      createToken("MAINVERSIONLOOSE", `(${src[t.NUMERICIDENTIFIERLOOSE]})\\.(${src[t.NUMERICIDENTIFIERLOOSE]})\\.(${src[t.NUMERICIDENTIFIERLOOSE]})`);
      createToken("PRERELEASEIDENTIFIER", `(?:${src[t.NONNUMERICIDENTIFIER]}|${src[t.NUMERICIDENTIFIER]})`);
      createToken("PRERELEASEIDENTIFIERLOOSE", `(?:${src[t.NONNUMERICIDENTIFIER]}|${src[t.NUMERICIDENTIFIERLOOSE]})`);
      createToken("PRERELEASE", `(?:-(${src[t.PRERELEASEIDENTIFIER]}(?:\\.${src[t.PRERELEASEIDENTIFIER]})*))`);
      createToken("PRERELEASELOOSE", `(?:-?(${src[t.PRERELEASEIDENTIFIERLOOSE]}(?:\\.${src[t.PRERELEASEIDENTIFIERLOOSE]})*))`);
      createToken("BUILDIDENTIFIER", `${LETTERDASHNUMBER}+`);
      createToken("BUILD", `(?:\\+(${src[t.BUILDIDENTIFIER]}(?:\\.${src[t.BUILDIDENTIFIER]})*))`);
      createToken("FULLPLAIN", `v?${src[t.MAINVERSION]}${src[t.PRERELEASE]}?${src[t.BUILD]}?`);
      createToken("FULL", `^${src[t.FULLPLAIN]}$`);
      createToken("LOOSEPLAIN", `[v=\\s]*${src[t.MAINVERSIONLOOSE]}${src[t.PRERELEASELOOSE]}?${src[t.BUILD]}?`);
      createToken("LOOSE", `^${src[t.LOOSEPLAIN]}$`);
      createToken("GTLT", "((?:<|>)?=?)");
      createToken("XRANGEIDENTIFIERLOOSE", `${src[t.NUMERICIDENTIFIERLOOSE]}|x|X|\\*`);
      createToken("XRANGEIDENTIFIER", `${src[t.NUMERICIDENTIFIER]}|x|X|\\*`);
      createToken("XRANGEPLAIN", `[v=\\s]*(${src[t.XRANGEIDENTIFIER]})(?:\\.(${src[t.XRANGEIDENTIFIER]})(?:\\.(${src[t.XRANGEIDENTIFIER]})(?:${src[t.PRERELEASE]})?${src[t.BUILD]}?)?)?`);
      createToken("XRANGEPLAINLOOSE", `[v=\\s]*(${src[t.XRANGEIDENTIFIERLOOSE]})(?:\\.(${src[t.XRANGEIDENTIFIERLOOSE]})(?:\\.(${src[t.XRANGEIDENTIFIERLOOSE]})(?:${src[t.PRERELEASELOOSE]})?${src[t.BUILD]}?)?)?`);
      createToken("XRANGE", `^${src[t.GTLT]}\\s*${src[t.XRANGEPLAIN]}$`);
      createToken("XRANGELOOSE", `^${src[t.GTLT]}\\s*${src[t.XRANGEPLAINLOOSE]}$`);
      createToken("COERCEPLAIN", `${"(^|[^\\d])(\\d{1,"}${MAX_SAFE_COMPONENT_LENGTH}})(?:\\.(\\d{1,${MAX_SAFE_COMPONENT_LENGTH}}))?(?:\\.(\\d{1,${MAX_SAFE_COMPONENT_LENGTH}}))?`);
      createToken("COERCE", `${src[t.COERCEPLAIN]}(?:$|[^\\d])`);
      createToken("COERCEFULL", src[t.COERCEPLAIN] + `(?:${src[t.PRERELEASE]})?(?:${src[t.BUILD]})?(?:$|[^\\d])`);
      createToken("COERCERTL", src[t.COERCE], true);
      createToken("COERCERTLFULL", src[t.COERCEFULL], true);
      createToken("LONETILDE", "(?:~>?)");
      createToken("TILDETRIM", `(\\s*)${src[t.LONETILDE]}\\s+`, true);
      exports.tildeTrimReplace = "$1~";
      createToken("TILDE", `^${src[t.LONETILDE]}${src[t.XRANGEPLAIN]}$`);
      createToken("TILDELOOSE", `^${src[t.LONETILDE]}${src[t.XRANGEPLAINLOOSE]}$`);
      createToken("LONECARET", "(?:\\^)");
      createToken("CARETTRIM", `(\\s*)${src[t.LONECARET]}\\s+`, true);
      exports.caretTrimReplace = "$1^";
      createToken("CARET", `^${src[t.LONECARET]}${src[t.XRANGEPLAIN]}$`);
      createToken("CARETLOOSE", `^${src[t.LONECARET]}${src[t.XRANGEPLAINLOOSE]}$`);
      createToken("COMPARATORLOOSE", `^${src[t.GTLT]}\\s*(${src[t.LOOSEPLAIN]})$|^$`);
      createToken("COMPARATOR", `^${src[t.GTLT]}\\s*(${src[t.FULLPLAIN]})$|^$`);
      createToken("COMPARATORTRIM", `(\\s*)${src[t.GTLT]}\\s*(${src[t.LOOSEPLAIN]}|${src[t.XRANGEPLAIN]})`, true);
      exports.comparatorTrimReplace = "$1$2$3";
      createToken("HYPHENRANGE", `^\\s*(${src[t.XRANGEPLAIN]})\\s+-\\s+(${src[t.XRANGEPLAIN]})\\s*$`);
      createToken("HYPHENRANGELOOSE", `^\\s*(${src[t.XRANGEPLAINLOOSE]})\\s+-\\s+(${src[t.XRANGEPLAINLOOSE]})\\s*$`);
      createToken("STAR", "(<|>)?=?\\s*\\*");
      createToken("GTE0", "^\\s*>=\\s*0\\.0\\.0\\s*$");
      createToken("GTE0PRE", "^\\s*>=\\s*0\\.0\\.0-0\\s*$");
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/parse-options.js
  var require_parse_options = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/parse-options.js"(exports, module) {
      "use strict";
      var looseOption = Object.freeze({ loose: true });
      var emptyOpts = Object.freeze({});
      var parseOptions = (options) => {
        if (!options) {
          return emptyOpts;
        }
        if (typeof options !== "object") {
          return looseOption;
        }
        return options;
      };
      module.exports = parseOptions;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/identifiers.js
  var require_identifiers = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/identifiers.js"(exports, module) {
      "use strict";
      var numeric = /^[0-9]+$/;
      var compareIdentifiers = (a, b) => {
        if (typeof a === "number" && typeof b === "number") {
          return a === b ? 0 : a < b ? -1 : 1;
        }
        const anum = numeric.test(a);
        const bnum = numeric.test(b);
        if (anum && bnum) {
          a = +a;
          b = +b;
        }
        return a === b ? 0 : anum && !bnum ? -1 : bnum && !anum ? 1 : a < b ? -1 : 1;
      };
      var rcompareIdentifiers = (a, b) => compareIdentifiers(b, a);
      module.exports = {
        compareIdentifiers,
        rcompareIdentifiers
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/semver.js
  var require_semver = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/semver.js"(exports, module) {
      "use strict";
      var debug = require_debug();
      var { MAX_LENGTH, MAX_SAFE_INTEGER } = require_constants();
      var { safeRe: re, t } = require_re();
      var parseOptions = require_parse_options();
      var { compareIdentifiers } = require_identifiers();
      var isPrereleaseIdentifier = (prerelease, identifier) => {
        const identifiers = identifier.split(".");
        if (identifiers.length > prerelease.length) {
          return false;
        }
        for (let i = 0; i < identifiers.length; i++) {
          if (compareIdentifiers(prerelease[i], identifiers[i]) !== 0) {
            return false;
          }
        }
        return true;
      };
      var SemVer = class _SemVer {
        constructor(version, options) {
          options = parseOptions(options);
          if (version instanceof _SemVer) {
            if (version.loose === !!options.loose && version.includePrerelease === !!options.includePrerelease) {
              return version;
            } else {
              version = version.version;
            }
          } else if (typeof version !== "string") {
            throw new TypeError(`Invalid version. Must be a string. Got type "${typeof version}".`);
          }
          if (version.length > MAX_LENGTH) {
            throw new TypeError(
              `version is longer than ${MAX_LENGTH} characters`
            );
          }
          debug("SemVer", version, options);
          this.options = options;
          this.loose = !!options.loose;
          this.includePrerelease = !!options.includePrerelease;
          const m = version.trim().match(options.loose ? re[t.LOOSE] : re[t.FULL]);
          if (!m) {
            throw new TypeError(`Invalid Version: ${version}`);
          }
          this.raw = version;
          this.major = +m[1];
          this.minor = +m[2];
          this.patch = +m[3];
          if (this.major > MAX_SAFE_INTEGER || this.major < 0) {
            throw new TypeError("Invalid major version");
          }
          if (this.minor > MAX_SAFE_INTEGER || this.minor < 0) {
            throw new TypeError("Invalid minor version");
          }
          if (this.patch > MAX_SAFE_INTEGER || this.patch < 0) {
            throw new TypeError("Invalid patch version");
          }
          if (!m[4]) {
            this.prerelease = [];
          } else {
            this.prerelease = m[4].split(".").map((id) => {
              if (/^[0-9]+$/.test(id)) {
                const num = +id;
                if (num >= 0 && num < MAX_SAFE_INTEGER) {
                  return num;
                }
              }
              return id;
            });
          }
          this.build = m[5] ? m[5].split(".") : [];
          this.format();
        }
        format() {
          this.version = `${this.major}.${this.minor}.${this.patch}`;
          if (this.prerelease.length) {
            this.version += `-${this.prerelease.join(".")}`;
          }
          return this.version;
        }
        toString() {
          return this.version;
        }
        compare(other) {
          debug("SemVer.compare", this.version, this.options, other);
          if (!(other instanceof _SemVer)) {
            if (typeof other === "string" && other === this.version) {
              return 0;
            }
            other = new _SemVer(other, this.options);
          }
          if (other.version === this.version) {
            return 0;
          }
          return this.compareMain(other) || this.comparePre(other);
        }
        compareMain(other) {
          if (!(other instanceof _SemVer)) {
            other = new _SemVer(other, this.options);
          }
          if (this.major < other.major) {
            return -1;
          }
          if (this.major > other.major) {
            return 1;
          }
          if (this.minor < other.minor) {
            return -1;
          }
          if (this.minor > other.minor) {
            return 1;
          }
          if (this.patch < other.patch) {
            return -1;
          }
          if (this.patch > other.patch) {
            return 1;
          }
          return 0;
        }
        comparePre(other) {
          if (!(other instanceof _SemVer)) {
            other = new _SemVer(other, this.options);
          }
          if (this.prerelease.length && !other.prerelease.length) {
            return -1;
          } else if (!this.prerelease.length && other.prerelease.length) {
            return 1;
          } else if (!this.prerelease.length && !other.prerelease.length) {
            return 0;
          }
          let i = 0;
          do {
            const a = this.prerelease[i];
            const b = other.prerelease[i];
            debug("prerelease compare", i, a, b);
            if (a === void 0 && b === void 0) {
              return 0;
            } else if (b === void 0) {
              return 1;
            } else if (a === void 0) {
              return -1;
            } else if (a === b) {
              continue;
            } else {
              return compareIdentifiers(a, b);
            }
          } while (++i);
        }
        compareBuild(other) {
          if (!(other instanceof _SemVer)) {
            other = new _SemVer(other, this.options);
          }
          let i = 0;
          do {
            const a = this.build[i];
            const b = other.build[i];
            debug("build compare", i, a, b);
            if (a === void 0 && b === void 0) {
              return 0;
            } else if (b === void 0) {
              return 1;
            } else if (a === void 0) {
              return -1;
            } else if (a === b) {
              continue;
            } else {
              return compareIdentifiers(a, b);
            }
          } while (++i);
        }
        // preminor will bump the version up to the next minor release, and immediately
        // down to pre-release. premajor and prepatch work the same way.
        inc(release, identifier, identifierBase) {
          if (release.startsWith("pre")) {
            if (!identifier && identifierBase === false) {
              throw new Error("invalid increment argument: identifier is empty");
            }
            if (identifier) {
              const match = `-${identifier}`.match(this.options.loose ? re[t.PRERELEASELOOSE] : re[t.PRERELEASE]);
              if (!match || match[1] !== identifier) {
                throw new Error(`invalid identifier: ${identifier}`);
              }
            }
          }
          switch (release) {
            case "premajor":
              this.prerelease.length = 0;
              this.patch = 0;
              this.minor = 0;
              this.major++;
              this.inc("pre", identifier, identifierBase);
              break;
            case "preminor":
              this.prerelease.length = 0;
              this.patch = 0;
              this.minor++;
              this.inc("pre", identifier, identifierBase);
              break;
            case "prepatch":
              this.prerelease.length = 0;
              this.inc("patch", identifier, identifierBase);
              this.inc("pre", identifier, identifierBase);
              break;
            // If the input is a non-prerelease version, this acts the same as
            // prepatch.
            case "prerelease":
              if (this.prerelease.length === 0) {
                this.inc("patch", identifier, identifierBase);
              }
              this.inc("pre", identifier, identifierBase);
              break;
            case "release":
              if (this.prerelease.length === 0) {
                throw new Error(`version ${this.raw} is not a prerelease`);
              }
              this.prerelease.length = 0;
              break;
            case "major":
              if (this.minor !== 0 || this.patch !== 0 || this.prerelease.length === 0) {
                this.major++;
              }
              this.minor = 0;
              this.patch = 0;
              this.prerelease = [];
              break;
            case "minor":
              if (this.patch !== 0 || this.prerelease.length === 0) {
                this.minor++;
              }
              this.patch = 0;
              this.prerelease = [];
              break;
            case "patch":
              if (this.prerelease.length === 0) {
                this.patch++;
              }
              this.prerelease = [];
              break;
            // This probably shouldn't be used publicly.
            // 1.0.0 'pre' would become 1.0.0-0 which is the wrong direction.
            case "pre": {
              const base = Number(identifierBase) ? 1 : 0;
              if (this.prerelease.length === 0) {
                this.prerelease = [base];
              } else {
                let i = this.prerelease.length;
                while (--i >= 0) {
                  if (typeof this.prerelease[i] === "number") {
                    this.prerelease[i]++;
                    i = -2;
                  }
                }
                if (i === -1) {
                  if (identifier === this.prerelease.join(".") && identifierBase === false) {
                    throw new Error("invalid increment argument: identifier already exists");
                  }
                  this.prerelease.push(base);
                }
              }
              if (identifier) {
                let prerelease = [identifier, base];
                if (identifierBase === false) {
                  prerelease = [identifier];
                }
                if (isPrereleaseIdentifier(this.prerelease, identifier)) {
                  const prereleaseBase = this.prerelease[identifier.split(".").length];
                  if (isNaN(prereleaseBase)) {
                    this.prerelease = prerelease;
                  }
                } else {
                  this.prerelease = prerelease;
                }
              }
              break;
            }
            default:
              throw new Error(`invalid increment argument: ${release}`);
          }
          this.raw = this.format();
          if (this.build.length) {
            this.raw += `+${this.build.join(".")}`;
          }
          return this;
        }
      };
      module.exports = SemVer;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/parse.js
  var require_parse = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/parse.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var parse = (version, options, throwErrors = false) => {
        if (version instanceof SemVer) {
          return version;
        }
        try {
          return new SemVer(version, options);
        } catch (er) {
          if (!throwErrors) {
            return null;
          }
          throw er;
        }
      };
      module.exports = parse;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/valid.js
  var require_valid = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/valid.js"(exports, module) {
      "use strict";
      var parse = require_parse();
      var valid = (version, options) => {
        const v = parse(version, options);
        return v ? v.version : null;
      };
      module.exports = valid;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/clean.js
  var require_clean = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/clean.js"(exports, module) {
      "use strict";
      var parse = require_parse();
      var clean = (version, options) => {
        const s = parse(version.trim().replace(/^[=v]+/, ""), options);
        return s ? s.version : null;
      };
      module.exports = clean;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/inc.js
  var require_inc = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/inc.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var inc = (version, release, options, identifier, identifierBase) => {
        if (typeof options === "string") {
          identifierBase = identifier;
          identifier = options;
          options = void 0;
        }
        try {
          return new SemVer(
            version instanceof SemVer ? version.version : version,
            options
          ).inc(release, identifier, identifierBase).version;
        } catch (er) {
          return null;
        }
      };
      module.exports = inc;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/diff.js
  var require_diff = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/diff.js"(exports, module) {
      "use strict";
      var parse = require_parse();
      var diff = (version1, version2) => {
        const v1 = parse(version1, null, true);
        const v2 = parse(version2, null, true);
        const comparison = v1.compare(v2);
        if (comparison === 0) {
          return null;
        }
        const v1Higher = comparison > 0;
        const highVersion = v1Higher ? v1 : v2;
        const lowVersion = v1Higher ? v2 : v1;
        const highHasPre = !!highVersion.prerelease.length;
        const lowHasPre = !!lowVersion.prerelease.length;
        if (lowHasPre && !highHasPre) {
          if (!lowVersion.patch && !lowVersion.minor) {
            return "major";
          }
          if (lowVersion.compareMain(highVersion) === 0) {
            if (lowVersion.minor && !lowVersion.patch) {
              return "minor";
            }
            return "patch";
          }
        }
        const prefix = highHasPre ? "pre" : "";
        if (v1.major !== v2.major) {
          return prefix + "major";
        }
        if (v1.minor !== v2.minor) {
          return prefix + "minor";
        }
        if (v1.patch !== v2.patch) {
          return prefix + "patch";
        }
        return "prerelease";
      };
      module.exports = diff;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/major.js
  var require_major = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/major.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var major = (a, loose) => new SemVer(a, loose).major;
      module.exports = major;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/minor.js
  var require_minor = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/minor.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var minor = (a, loose) => new SemVer(a, loose).minor;
      module.exports = minor;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/patch.js
  var require_patch = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/patch.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var patch = (a, loose) => new SemVer(a, loose).patch;
      module.exports = patch;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/prerelease.js
  var require_prerelease = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/prerelease.js"(exports, module) {
      "use strict";
      var parse = require_parse();
      var prerelease = (version, options) => {
        const parsed = parse(version, options);
        return parsed && parsed.prerelease.length ? parsed.prerelease : null;
      };
      module.exports = prerelease;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare.js
  var require_compare = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var compare = (a, b, loose) => new SemVer(a, loose).compare(new SemVer(b, loose));
      module.exports = compare;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/rcompare.js
  var require_rcompare = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/rcompare.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var rcompare = (a, b, loose) => compare(b, a, loose);
      module.exports = rcompare;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare-loose.js
  var require_compare_loose = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare-loose.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var compareLoose = (a, b) => compare(a, b, true);
      module.exports = compareLoose;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare-build.js
  var require_compare_build = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/compare-build.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var compareBuild = (a, b, loose) => {
        const versionA = new SemVer(a, loose);
        const versionB = new SemVer(b, loose);
        return versionA.compare(versionB) || versionA.compareBuild(versionB);
      };
      module.exports = compareBuild;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/sort.js
  var require_sort = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/sort.js"(exports, module) {
      "use strict";
      var compareBuild = require_compare_build();
      var sort = (list, loose) => list.sort((a, b) => compareBuild(a, b, loose));
      module.exports = sort;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/rsort.js
  var require_rsort = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/rsort.js"(exports, module) {
      "use strict";
      var compareBuild = require_compare_build();
      var rsort = (list, loose) => list.sort((a, b) => compareBuild(b, a, loose));
      module.exports = rsort;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/gt.js
  var require_gt = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/gt.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var gt = (a, b, loose) => compare(a, b, loose) > 0;
      module.exports = gt;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/lt.js
  var require_lt = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/lt.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var lt = (a, b, loose) => compare(a, b, loose) < 0;
      module.exports = lt;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/eq.js
  var require_eq = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/eq.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var eq = (a, b, loose) => compare(a, b, loose) === 0;
      module.exports = eq;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/neq.js
  var require_neq = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/neq.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var neq = (a, b, loose) => compare(a, b, loose) !== 0;
      module.exports = neq;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/gte.js
  var require_gte = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/gte.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var gte = (a, b, loose) => compare(a, b, loose) >= 0;
      module.exports = gte;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/lte.js
  var require_lte = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/lte.js"(exports, module) {
      "use strict";
      var compare = require_compare();
      var lte = (a, b, loose) => compare(a, b, loose) <= 0;
      module.exports = lte;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/cmp.js
  var require_cmp = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/cmp.js"(exports, module) {
      "use strict";
      var eq = require_eq();
      var neq = require_neq();
      var gt = require_gt();
      var gte = require_gte();
      var lt = require_lt();
      var lte = require_lte();
      var cmp = (a, op, b, loose) => {
        switch (op) {
          case "===":
            if (typeof a === "object") {
              a = a.version;
            }
            if (typeof b === "object") {
              b = b.version;
            }
            return a === b;
          case "!==":
            if (typeof a === "object") {
              a = a.version;
            }
            if (typeof b === "object") {
              b = b.version;
            }
            return a !== b;
          case "":
          case "=":
          case "==":
            return eq(a, b, loose);
          case "!=":
            return neq(a, b, loose);
          case ">":
            return gt(a, b, loose);
          case ">=":
            return gte(a, b, loose);
          case "<":
            return lt(a, b, loose);
          case "<=":
            return lte(a, b, loose);
          default:
            throw new TypeError(`Invalid operator: ${op}`);
        }
      };
      module.exports = cmp;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/coerce.js
  var require_coerce = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/coerce.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var parse = require_parse();
      var { safeRe: re, t } = require_re();
      var coerce = (version, options) => {
        if (version instanceof SemVer) {
          return version;
        }
        if (typeof version === "number") {
          version = String(version);
        }
        if (typeof version !== "string") {
          return null;
        }
        options = options || {};
        let match = null;
        if (!options.rtl) {
          match = version.match(options.includePrerelease ? re[t.COERCEFULL] : re[t.COERCE]);
        } else {
          const coerceRtlRegex = options.includePrerelease ? re[t.COERCERTLFULL] : re[t.COERCERTL];
          let next;
          while ((next = coerceRtlRegex.exec(version)) && (!match || match.index + match[0].length !== version.length)) {
            if (!match || next.index + next[0].length !== match.index + match[0].length) {
              match = next;
            }
            coerceRtlRegex.lastIndex = next.index + next[1].length + next[2].length;
          }
          coerceRtlRegex.lastIndex = -1;
        }
        if (match === null) {
          return null;
        }
        const major = match[2];
        const minor = match[3] || "0";
        const patch = match[4] || "0";
        const prerelease = options.includePrerelease && match[5] ? `-${match[5]}` : "";
        const build = options.includePrerelease && match[6] ? `+${match[6]}` : "";
        return parse(`${major}.${minor}.${patch}${prerelease}${build}`, options);
      };
      module.exports = coerce;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/truncate.js
  var require_truncate = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/truncate.js"(exports, module) {
      "use strict";
      var parse = require_parse();
      var constants = require_constants();
      var SemVer = require_semver();
      var truncate = (version, truncation, options) => {
        if (!constants.RELEASE_TYPES.includes(truncation)) {
          return null;
        }
        const clonedVersion = cloneInputVersion(version, options);
        return clonedVersion && doTruncation(clonedVersion, truncation);
      };
      var cloneInputVersion = (version, options) => {
        const versionStringToParse = version instanceof SemVer ? version.version : version;
        return parse(versionStringToParse, options);
      };
      var doTruncation = (version, truncation) => {
        if (isPrerelease(truncation)) {
          return version.version;
        }
        version.prerelease = [];
        switch (truncation) {
          case "major":
            version.minor = 0;
            version.patch = 0;
            break;
          case "minor":
            version.patch = 0;
            break;
        }
        return version.format();
      };
      var isPrerelease = (type) => {
        return type.startsWith("pre");
      };
      module.exports = truncate;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/lrucache.js
  var require_lrucache = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/internal/lrucache.js"(exports, module) {
      "use strict";
      var LRUCache = class {
        constructor() {
          this.max = 1e3;
          this.map = /* @__PURE__ */ new Map();
        }
        get(key) {
          const value = this.map.get(key);
          if (value === void 0) {
            return void 0;
          } else {
            this.map.delete(key);
            this.map.set(key, value);
            return value;
          }
        }
        delete(key) {
          return this.map.delete(key);
        }
        set(key, value) {
          const deleted = this.delete(key);
          if (!deleted && value !== void 0) {
            if (this.map.size >= this.max) {
              const firstKey = this.map.keys().next().value;
              this.delete(firstKey);
            }
            this.map.set(key, value);
          }
          return this;
        }
      };
      module.exports = LRUCache;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/range.js
  var require_range = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/range.js"(exports, module) {
      "use strict";
      var SPACE_CHARACTERS = /\s+/g;
      var Range = class _Range {
        constructor(range, options) {
          options = parseOptions(options);
          if (range instanceof _Range) {
            if (range.loose === !!options.loose && range.includePrerelease === !!options.includePrerelease) {
              return range;
            } else {
              return new _Range(range.raw, options);
            }
          }
          if (range instanceof Comparator) {
            this.raw = range.value;
            this.set = [[range]];
            this.formatted = void 0;
            return this;
          }
          this.options = options;
          this.loose = !!options.loose;
          this.includePrerelease = !!options.includePrerelease;
          this.raw = range.trim().replace(SPACE_CHARACTERS, " ");
          this.set = this.raw.split("||").map((r) => this.parseRange(r.trim())).filter((c) => c.length);
          if (!this.set.length) {
            throw new TypeError(`Invalid SemVer Range: ${this.raw}`);
          }
          if (this.set.length > 1) {
            const first = this.set[0];
            this.set = this.set.filter((c) => !isNullSet(c[0]));
            if (this.set.length === 0) {
              this.set = [first];
            } else if (this.set.length > 1) {
              for (const c of this.set) {
                if (c.length === 1 && isAny(c[0])) {
                  this.set = [c];
                  break;
                }
              }
            }
          }
          this.formatted = void 0;
        }
        get range() {
          if (this.formatted === void 0) {
            this.formatted = "";
            for (let i = 0; i < this.set.length; i++) {
              if (i > 0) {
                this.formatted += "||";
              }
              const comps = this.set[i];
              for (let k = 0; k < comps.length; k++) {
                if (k > 0) {
                  this.formatted += " ";
                }
                this.formatted += comps[k].toString().trim();
              }
            }
          }
          return this.formatted;
        }
        format() {
          return this.range;
        }
        toString() {
          return this.range;
        }
        parseRange(range) {
          range = range.replace(BUILDSTRIPRE, "");
          const memoOpts = (this.options.includePrerelease && FLAG_INCLUDE_PRERELEASE) | (this.options.loose && FLAG_LOOSE);
          const memoKey = memoOpts + ":" + range;
          const cached = cache.get(memoKey);
          if (cached) {
            return cached;
          }
          const loose = this.options.loose;
          const hr = loose ? re[t.HYPHENRANGELOOSE] : re[t.HYPHENRANGE];
          range = range.replace(hr, hyphenReplace(this.options.includePrerelease));
          debug("hyphen replace", range);
          range = range.replace(re[t.COMPARATORTRIM], comparatorTrimReplace);
          debug("comparator trim", range);
          range = range.replace(re[t.TILDETRIM], tildeTrimReplace);
          debug("tilde trim", range);
          range = range.replace(re[t.CARETTRIM], caretTrimReplace);
          debug("caret trim", range);
          let rangeList = range.split(" ").map((comp) => parseComparator(comp, this.options)).join(" ").split(/\s+/).map((comp) => replaceGTE0(comp, this.options));
          if (loose) {
            rangeList = rangeList.filter((comp) => {
              debug("loose invalid filter", comp, this.options);
              return !!comp.match(re[t.COMPARATORLOOSE]);
            });
          }
          debug("range list", rangeList);
          const rangeMap = /* @__PURE__ */ new Map();
          const comparators = rangeList.map((comp) => new Comparator(comp, this.options));
          for (const comp of comparators) {
            if (isNullSet(comp)) {
              return [comp];
            }
            rangeMap.set(comp.value, comp);
          }
          if (rangeMap.size > 1 && rangeMap.has("")) {
            rangeMap.delete("");
          }
          const result = [...rangeMap.values()];
          cache.set(memoKey, result);
          return result;
        }
        intersects(range, options) {
          if (!(range instanceof _Range)) {
            throw new TypeError("a Range is required");
          }
          return this.set.some((thisComparators) => {
            return isSatisfiable(thisComparators, options) && range.set.some((rangeComparators) => {
              return isSatisfiable(rangeComparators, options) && thisComparators.every((thisComparator) => {
                return rangeComparators.every((rangeComparator) => {
                  return thisComparator.intersects(rangeComparator, options);
                });
              });
            });
          });
        }
        // if ANY of the sets match ALL of its comparators, then pass
        test(version) {
          if (!version) {
            return false;
          }
          if (typeof version === "string") {
            try {
              version = new SemVer(version, this.options);
            } catch (er) {
              return false;
            }
          }
          for (let i = 0; i < this.set.length; i++) {
            if (testSet(this.set[i], version, this.options)) {
              return true;
            }
          }
          return false;
        }
      };
      module.exports = Range;
      var LRU = require_lrucache();
      var cache = new LRU();
      var parseOptions = require_parse_options();
      var Comparator = require_comparator();
      var debug = require_debug();
      var SemVer = require_semver();
      var {
        safeRe: re,
        src,
        t,
        comparatorTrimReplace,
        tildeTrimReplace,
        caretTrimReplace
      } = require_re();
      var { FLAG_INCLUDE_PRERELEASE, FLAG_LOOSE } = require_constants();
      var BUILDSTRIPRE = new RegExp(src[t.BUILD], "g");
      var isNullSet = (c) => c.value === "<0.0.0-0";
      var isAny = (c) => c.value === "";
      var isSatisfiable = (comparators, options) => {
        let result = true;
        const remainingComparators = comparators.slice();
        let testComparator = remainingComparators.pop();
        while (result && remainingComparators.length) {
          result = remainingComparators.every((otherComparator) => {
            return testComparator.intersects(otherComparator, options);
          });
          testComparator = remainingComparators.pop();
        }
        return result;
      };
      var parseComparator = (comp, options) => {
        comp = comp.replace(re[t.BUILD], "");
        debug("comp", comp, options);
        comp = replaceCarets(comp, options);
        debug("caret", comp);
        comp = replaceTildes(comp, options);
        debug("tildes", comp);
        comp = replaceXRanges(comp, options);
        debug("xrange", comp);
        comp = replaceStars(comp, options);
        debug("stars", comp);
        return comp;
      };
      var isX = (id) => !id || id.toLowerCase() === "x" || id === "*";
      var invalidXRangeOrder = (M, m, p) => isX(M) && !isX(m) || isX(m) && p && !isX(p);
      var replaceTildes = (comp, options) => {
        return comp.trim().split(/\s+/).map((c) => replaceTilde(c, options)).join(" ");
      };
      var replaceTilde = (comp, options) => {
        const r = options.loose ? re[t.TILDELOOSE] : re[t.TILDE];
        const z = options.includePrerelease ? "-0" : "";
        return comp.replace(r, (_, M, m, p, pr) => {
          debug("tilde", comp, _, M, m, p, pr);
          let ret;
          if (isX(M)) {
            ret = "";
          } else if (isX(m)) {
            ret = `>=${M}.0.0${z} <${+M + 1}.0.0-0`;
          } else if (isX(p)) {
            ret = `>=${M}.${m}.0${z} <${M}.${+m + 1}.0-0`;
          } else if (pr) {
            debug("replaceTilde pr", pr);
            ret = `>=${M}.${m}.${p}-${pr} <${M}.${+m + 1}.0-0`;
          } else {
            ret = `>=${M}.${m}.${p} <${M}.${+m + 1}.0-0`;
          }
          debug("tilde return", ret);
          return ret;
        });
      };
      var replaceCarets = (comp, options) => {
        return comp.trim().split(/\s+/).map((c) => replaceCaret(c, options)).join(" ");
      };
      var replaceCaret = (comp, options) => {
        debug("caret", comp, options);
        const r = options.loose ? re[t.CARETLOOSE] : re[t.CARET];
        const z = options.includePrerelease ? "-0" : "";
        return comp.replace(r, (_, M, m, p, pr) => {
          debug("caret", comp, _, M, m, p, pr);
          let ret;
          if (isX(M)) {
            ret = "";
          } else if (isX(m)) {
            ret = `>=${M}.0.0${z} <${+M + 1}.0.0-0`;
          } else if (isX(p)) {
            if (M === "0") {
              ret = `>=${M}.${m}.0${z} <${M}.${+m + 1}.0-0`;
            } else {
              ret = `>=${M}.${m}.0${z} <${+M + 1}.0.0-0`;
            }
          } else if (pr) {
            debug("replaceCaret pr", pr);
            if (M === "0") {
              if (m === "0") {
                ret = `>=${M}.${m}.${p}-${pr} <${M}.${m}.${+p + 1}-0`;
              } else {
                ret = `>=${M}.${m}.${p}-${pr} <${M}.${+m + 1}.0-0`;
              }
            } else {
              ret = `>=${M}.${m}.${p}-${pr} <${+M + 1}.0.0-0`;
            }
          } else {
            debug("no pr");
            if (M === "0") {
              if (m === "0") {
                ret = `>=${M}.${m}.${p} <${M}.${m}.${+p + 1}-0`;
              } else {
                ret = `>=${M}.${m}.${p} <${M}.${+m + 1}.0-0`;
              }
            } else {
              ret = `>=${M}.${m}.${p} <${+M + 1}.0.0-0`;
            }
          }
          debug("caret return", ret);
          return ret;
        });
      };
      var replaceXRanges = (comp, options) => {
        debug("replaceXRanges", comp, options);
        return comp.split(/\s+/).map((c) => replaceXRange(c, options)).join(" ");
      };
      var replaceXRange = (comp, options) => {
        comp = comp.trim();
        const r = options.loose ? re[t.XRANGELOOSE] : re[t.XRANGE];
        return comp.replace(r, (ret, gtlt, M, m, p, pr) => {
          debug("xRange", comp, ret, gtlt, M, m, p, pr);
          if (invalidXRangeOrder(M, m, p)) {
            return comp;
          }
          const xM = isX(M);
          const xm = xM || isX(m);
          const xp = xm || isX(p);
          const anyX = xp;
          if (gtlt === "=" && anyX) {
            gtlt = "";
          }
          pr = options.includePrerelease ? "-0" : "";
          if (xM) {
            if (gtlt === ">" || gtlt === "<") {
              ret = "<0.0.0-0";
            } else {
              ret = "*";
            }
          } else if (gtlt && anyX) {
            if (xm) {
              m = 0;
            }
            p = 0;
            if (gtlt === ">") {
              gtlt = ">=";
              if (xm) {
                M = +M + 1;
                m = 0;
                p = 0;
              } else {
                m = +m + 1;
                p = 0;
              }
            } else if (gtlt === "<=") {
              gtlt = "<";
              if (xm) {
                M = +M + 1;
              } else {
                m = +m + 1;
              }
            }
            if (gtlt === "<") {
              pr = "-0";
            }
            ret = `${gtlt + M}.${m}.${p}${pr}`;
          } else if (xm) {
            ret = `>=${M}.0.0${pr} <${+M + 1}.0.0-0`;
          } else if (xp) {
            ret = `>=${M}.${m}.0${pr} <${M}.${+m + 1}.0-0`;
          }
          debug("xRange return", ret);
          return ret;
        });
      };
      var replaceStars = (comp, options) => {
        debug("replaceStars", comp, options);
        return comp.trim().replace(re[t.STAR], "");
      };
      var replaceGTE0 = (comp, options) => {
        debug("replaceGTE0", comp, options);
        return comp.trim().replace(re[options.includePrerelease ? t.GTE0PRE : t.GTE0], "");
      };
      var hyphenReplace = (incPr) => ($0, from, fM, fm, fp, fpr, fb, to, tM, tm, tp, tpr) => {
        if (isX(fM)) {
          from = "";
        } else if (isX(fm)) {
          from = `>=${fM}.0.0${incPr ? "-0" : ""}`;
        } else if (isX(fp)) {
          from = `>=${fM}.${fm}.0${incPr ? "-0" : ""}`;
        } else if (fpr) {
          from = `>=${from}`;
        } else {
          from = `>=${from}${incPr ? "-0" : ""}`;
        }
        if (isX(tM)) {
          to = "";
        } else if (isX(tm)) {
          to = `<${+tM + 1}.0.0-0`;
        } else if (isX(tp)) {
          to = `<${tM}.${+tm + 1}.0-0`;
        } else if (tpr) {
          to = `<=${tM}.${tm}.${tp}-${tpr}`;
        } else if (incPr) {
          to = `<${tM}.${tm}.${+tp + 1}-0`;
        } else {
          to = `<=${to}`;
        }
        return `${from} ${to}`.trim();
      };
      var testSet = (set, version, options) => {
        for (let i = 0; i < set.length; i++) {
          if (!set[i].test(version)) {
            return false;
          }
        }
        if (version.prerelease.length && !options.includePrerelease) {
          for (let i = 0; i < set.length; i++) {
            debug(set[i].semver);
            if (set[i].semver === Comparator.ANY) {
              continue;
            }
            if (set[i].semver.prerelease.length > 0) {
              const allowed = set[i].semver;
              if (allowed.major === version.major && allowed.minor === version.minor && allowed.patch === version.patch) {
                return true;
              }
            }
          }
          return false;
        }
        return true;
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/comparator.js
  var require_comparator = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/classes/comparator.js"(exports, module) {
      "use strict";
      var ANY = /* @__PURE__ */ Symbol("SemVer ANY");
      var Comparator = class _Comparator {
        static get ANY() {
          return ANY;
        }
        constructor(comp, options) {
          options = parseOptions(options);
          if (comp instanceof _Comparator) {
            if (comp.loose === !!options.loose) {
              return comp;
            } else {
              comp = comp.value;
            }
          }
          comp = comp.trim().split(/\s+/).join(" ");
          debug("comparator", comp, options);
          this.options = options;
          this.loose = !!options.loose;
          this.parse(comp);
          if (this.semver === ANY) {
            this.value = "";
          } else {
            this.value = this.operator + this.semver.version;
          }
          debug("comp", this);
        }
        parse(comp) {
          const r = this.options.loose ? re[t.COMPARATORLOOSE] : re[t.COMPARATOR];
          const m = comp.match(r);
          if (!m) {
            throw new TypeError(`Invalid comparator: ${comp}`);
          }
          this.operator = m[1] !== void 0 ? m[1] : "";
          if (this.operator === "=") {
            this.operator = "";
          }
          if (!m[2]) {
            this.semver = ANY;
          } else {
            this.semver = new SemVer(m[2], this.options.loose);
          }
        }
        toString() {
          return this.value;
        }
        test(version) {
          debug("Comparator.test", version, this.options.loose);
          if (this.semver === ANY || version === ANY) {
            return true;
          }
          if (typeof version === "string") {
            try {
              version = new SemVer(version, this.options);
            } catch (er) {
              return false;
            }
          }
          return cmp(version, this.operator, this.semver, this.options);
        }
        intersects(comp, options) {
          if (!(comp instanceof _Comparator)) {
            throw new TypeError("a Comparator is required");
          }
          if (this.operator === "") {
            if (this.value === "") {
              return true;
            }
            return new Range(comp.value, options).test(this.value);
          } else if (comp.operator === "") {
            if (comp.value === "") {
              return true;
            }
            return new Range(this.value, options).test(comp.semver);
          }
          options = parseOptions(options);
          if (options.includePrerelease && (this.value === "<0.0.0-0" || comp.value === "<0.0.0-0")) {
            return false;
          }
          if (!options.includePrerelease && (this.value.startsWith("<0.0.0") || comp.value.startsWith("<0.0.0"))) {
            return false;
          }
          if (this.operator.startsWith(">") && comp.operator.startsWith(">")) {
            return true;
          }
          if (this.operator.startsWith("<") && comp.operator.startsWith("<")) {
            return true;
          }
          if (this.semver.version === comp.semver.version && this.operator.includes("=") && comp.operator.includes("=")) {
            return true;
          }
          if (cmp(this.semver, "<", comp.semver, options) && this.operator.startsWith(">") && comp.operator.startsWith("<")) {
            return true;
          }
          if (cmp(this.semver, ">", comp.semver, options) && this.operator.startsWith("<") && comp.operator.startsWith(">")) {
            return true;
          }
          return false;
        }
      };
      module.exports = Comparator;
      var parseOptions = require_parse_options();
      var { safeRe: re, t } = require_re();
      var cmp = require_cmp();
      var debug = require_debug();
      var SemVer = require_semver();
      var Range = require_range();
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/satisfies.js
  var require_satisfies = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/functions/satisfies.js"(exports, module) {
      "use strict";
      var Range = require_range();
      var satisfies = (version, range, options) => {
        try {
          range = new Range(range, options);
        } catch (er) {
          return false;
        }
        return range.test(version);
      };
      module.exports = satisfies;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/to-comparators.js
  var require_to_comparators = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/to-comparators.js"(exports, module) {
      "use strict";
      var Range = require_range();
      var toComparators = (range, options) => new Range(range, options).set.map((comp) => comp.map((c) => c.value).join(" ").trim().split(" "));
      module.exports = toComparators;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/max-satisfying.js
  var require_max_satisfying = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/max-satisfying.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var Range = require_range();
      var maxSatisfying = (versions2, range, options) => {
        let max = null;
        let maxSV = null;
        let rangeObj = null;
        try {
          rangeObj = new Range(range, options);
        } catch (er) {
          return null;
        }
        versions2.forEach((v) => {
          if (rangeObj.test(v)) {
            if (!max || maxSV.compare(v) === -1) {
              max = v;
              maxSV = new SemVer(max, options);
            }
          }
        });
        return max;
      };
      module.exports = maxSatisfying;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/min-satisfying.js
  var require_min_satisfying = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/min-satisfying.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var Range = require_range();
      var minSatisfying = (versions2, range, options) => {
        let min = null;
        let minSV = null;
        let rangeObj = null;
        try {
          rangeObj = new Range(range, options);
        } catch (er) {
          return null;
        }
        versions2.forEach((v) => {
          if (rangeObj.test(v)) {
            if (!min || minSV.compare(v) === 1) {
              min = v;
              minSV = new SemVer(min, options);
            }
          }
        });
        return min;
      };
      module.exports = minSatisfying;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/min-version.js
  var require_min_version = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/min-version.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var Range = require_range();
      var gt = require_gt();
      var minVersion = (range, loose) => {
        range = new Range(range, loose);
        let minver = new SemVer("0.0.0");
        if (range.test(minver)) {
          return minver;
        }
        minver = new SemVer("0.0.0-0");
        if (range.test(minver)) {
          return minver;
        }
        minver = null;
        for (let i = 0; i < range.set.length; ++i) {
          const comparators = range.set[i];
          let setMin = null;
          comparators.forEach((comparator) => {
            const compver = new SemVer(comparator.semver.version);
            switch (comparator.operator) {
              case ">":
                if (compver.prerelease.length === 0) {
                  compver.patch++;
                } else {
                  compver.prerelease.push(0);
                }
                compver.raw = compver.format();
              /* fallthrough */
              case "":
              case ">=":
                if (!setMin || gt(compver, setMin)) {
                  setMin = compver;
                }
                break;
              case "<":
              case "<=":
                break;
              /* istanbul ignore next */
              default:
                throw new Error(`Unexpected operation: ${comparator.operator}`);
            }
          });
          if (setMin && (!minver || gt(minver, setMin))) {
            minver = setMin;
          }
        }
        if (minver && range.test(minver)) {
          return minver;
        }
        return null;
      };
      module.exports = minVersion;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/valid.js
  var require_valid2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/valid.js"(exports, module) {
      "use strict";
      var Range = require_range();
      var validRange = (range, options) => {
        try {
          return new Range(range, options).range || "*";
        } catch (er) {
          return null;
        }
      };
      module.exports = validRange;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/outside.js
  var require_outside = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/outside.js"(exports, module) {
      "use strict";
      var SemVer = require_semver();
      var Comparator = require_comparator();
      var { ANY } = Comparator;
      var Range = require_range();
      var satisfies = require_satisfies();
      var gt = require_gt();
      var lt = require_lt();
      var lte = require_lte();
      var gte = require_gte();
      var outside = (version, range, hilo, options) => {
        version = new SemVer(version, options);
        range = new Range(range, options);
        let gtfn, ltefn, ltfn, comp, ecomp;
        switch (hilo) {
          case ">":
            gtfn = gt;
            ltefn = lte;
            ltfn = lt;
            comp = ">";
            ecomp = ">=";
            break;
          case "<":
            gtfn = lt;
            ltefn = gte;
            ltfn = gt;
            comp = "<";
            ecomp = "<=";
            break;
          default:
            throw new TypeError('Must provide a hilo val of "<" or ">"');
        }
        if (satisfies(version, range, options)) {
          return false;
        }
        for (let i = 0; i < range.set.length; ++i) {
          const comparators = range.set[i];
          let high = null;
          let low = null;
          comparators.forEach((comparator) => {
            if (comparator.semver === ANY) {
              comparator = new Comparator(">=0.0.0");
            }
            high = high || comparator;
            low = low || comparator;
            if (gtfn(comparator.semver, high.semver, options)) {
              high = comparator;
            } else if (ltfn(comparator.semver, low.semver, options)) {
              low = comparator;
            }
          });
          if (high.operator === comp || high.operator === ecomp) {
            return false;
          }
          if ((!low.operator || low.operator === comp) && ltefn(version, low.semver)) {
            return false;
          } else if (low.operator === ecomp && ltfn(version, low.semver)) {
            return false;
          }
        }
        return true;
      };
      module.exports = outside;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/gtr.js
  var require_gtr = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/gtr.js"(exports, module) {
      "use strict";
      var outside = require_outside();
      var gtr = (version, range, options) => outside(version, range, ">", options);
      module.exports = gtr;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/ltr.js
  var require_ltr = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/ltr.js"(exports, module) {
      "use strict";
      var outside = require_outside();
      var ltr = (version, range, options) => outside(version, range, "<", options);
      module.exports = ltr;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/intersects.js
  var require_intersects = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/intersects.js"(exports, module) {
      "use strict";
      var Range = require_range();
      var intersects = (r1, r2, options) => {
        r1 = new Range(r1, options);
        r2 = new Range(r2, options);
        return r1.intersects(r2, options);
      };
      module.exports = intersects;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/simplify.js
  var require_simplify = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/simplify.js"(exports, module) {
      "use strict";
      var satisfies = require_satisfies();
      var compare = require_compare();
      module.exports = (versions2, range, options) => {
        const set = [];
        let first = null;
        let prev = null;
        const v = versions2.sort((a, b) => compare(a, b, options));
        for (const version of v) {
          const included = satisfies(version, range, options);
          if (included) {
            prev = version;
            if (!first) {
              first = version;
            }
          } else {
            if (prev) {
              set.push([first, prev]);
            }
            prev = null;
            first = null;
          }
        }
        if (first) {
          set.push([first, null]);
        }
        const ranges = [];
        for (const [min, max] of set) {
          if (min === max) {
            ranges.push(min);
          } else if (!max && min === v[0]) {
            ranges.push("*");
          } else if (!max) {
            ranges.push(`>=${min}`);
          } else if (min === v[0]) {
            ranges.push(`<=${max}`);
          } else {
            ranges.push(`${min} - ${max}`);
          }
        }
        const simplified = ranges.join(" || ");
        const original = typeof range.raw === "string" ? range.raw : String(range);
        return simplified.length < original.length ? simplified : range;
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/subset.js
  var require_subset = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/ranges/subset.js"(exports, module) {
      "use strict";
      var Range = require_range();
      var Comparator = require_comparator();
      var { ANY } = Comparator;
      var satisfies = require_satisfies();
      var compare = require_compare();
      var subset = (sub, dom, options = {}) => {
        if (sub === dom) {
          return true;
        }
        sub = new Range(sub, options);
        dom = new Range(dom, options);
        let sawNonNull = false;
        OUTER: for (const simpleSub of sub.set) {
          for (const simpleDom of dom.set) {
            const isSub = simpleSubset(simpleSub, simpleDom, options);
            sawNonNull = sawNonNull || isSub !== null;
            if (isSub) {
              continue OUTER;
            }
          }
          if (sawNonNull) {
            return false;
          }
        }
        return true;
      };
      var minimumVersionWithPreRelease = [new Comparator(">=0.0.0-0")];
      var minimumVersion = [new Comparator(">=0.0.0")];
      var simpleSubset = (sub, dom, options) => {
        if (sub === dom) {
          return true;
        }
        if (sub.length === 1 && sub[0].semver === ANY) {
          if (dom.length === 1 && dom[0].semver === ANY) {
            return true;
          } else if (options.includePrerelease) {
            sub = minimumVersionWithPreRelease;
          } else {
            sub = minimumVersion;
          }
        }
        if (dom.length === 1 && dom[0].semver === ANY) {
          if (options.includePrerelease) {
            return true;
          } else {
            dom = minimumVersion;
          }
        }
        const eqSet = /* @__PURE__ */ new Set();
        let gt, lt;
        for (const c of sub) {
          if (c.operator === ">" || c.operator === ">=") {
            gt = higherGT(gt, c, options);
          } else if (c.operator === "<" || c.operator === "<=") {
            lt = lowerLT(lt, c, options);
          } else {
            eqSet.add(c.semver);
          }
        }
        if (eqSet.size > 1) {
          return null;
        }
        let gtltComp;
        if (gt && lt) {
          gtltComp = compare(gt.semver, lt.semver, options);
          if (gtltComp > 0) {
            return null;
          } else if (gtltComp === 0 && (gt.operator !== ">=" || lt.operator !== "<=")) {
            return null;
          }
        }
        for (const eq of eqSet) {
          if (gt && !satisfies(eq, String(gt), options)) {
            return null;
          }
          if (lt && !satisfies(eq, String(lt), options)) {
            return null;
          }
          for (const c of dom) {
            if (!satisfies(eq, String(c), options)) {
              return false;
            }
          }
          return true;
        }
        let higher, lower;
        let hasDomLT, hasDomGT;
        let needDomLTPre = lt && !options.includePrerelease && lt.semver.prerelease.length ? lt.semver : false;
        let needDomGTPre = gt && !options.includePrerelease && gt.semver.prerelease.length ? gt.semver : false;
        if (needDomLTPre && needDomLTPre.prerelease.length === 1 && lt.operator === "<" && needDomLTPre.prerelease[0] === 0) {
          needDomLTPre = false;
        }
        for (const c of dom) {
          hasDomGT = hasDomGT || c.operator === ">" || c.operator === ">=";
          hasDomLT = hasDomLT || c.operator === "<" || c.operator === "<=";
          if (gt) {
            if (needDomGTPre) {
              if (c.semver.prerelease && c.semver.prerelease.length && c.semver.major === needDomGTPre.major && c.semver.minor === needDomGTPre.minor && c.semver.patch === needDomGTPre.patch) {
                needDomGTPre = false;
              }
            }
            if (c.operator === ">" || c.operator === ">=") {
              higher = higherGT(gt, c, options);
              if (higher === c && higher !== gt) {
                return false;
              }
            } else if (gt.operator === ">=" && !c.test(gt.semver)) {
              return false;
            }
          }
          if (lt) {
            if (needDomLTPre) {
              if (c.semver.prerelease && c.semver.prerelease.length && c.semver.major === needDomLTPre.major && c.semver.minor === needDomLTPre.minor && c.semver.patch === needDomLTPre.patch) {
                needDomLTPre = false;
              }
            }
            if (c.operator === "<" || c.operator === "<=") {
              lower = lowerLT(lt, c, options);
              if (lower === c && lower !== lt) {
                return false;
              }
            } else if (lt.operator === "<=" && !c.test(lt.semver)) {
              return false;
            }
          }
          if (!c.operator && (lt || gt) && gtltComp !== 0) {
            return false;
          }
        }
        if (gt && hasDomLT && !lt && gtltComp !== 0) {
          return false;
        }
        if (lt && hasDomGT && !gt && gtltComp !== 0) {
          return false;
        }
        if (needDomGTPre || needDomLTPre) {
          return false;
        }
        return true;
      };
      var higherGT = (a, b, options) => {
        if (!a) {
          return b;
        }
        const comp = compare(a.semver, b.semver, options);
        return comp > 0 ? a : comp < 0 ? b : b.operator === ">" && a.operator === ">=" ? b : a;
      };
      var lowerLT = (a, b, options) => {
        if (!a) {
          return b;
        }
        const comp = compare(a.semver, b.semver, options);
        return comp < 0 ? a : comp > 0 ? b : b.operator === "<" && a.operator === "<=" ? b : a;
      };
      module.exports = subset;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/index.js
  var require_semver2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/semver@7.8.5/node_modules/semver/index.js"(exports, module) {
      "use strict";
      var internalRe = require_re();
      var constants = require_constants();
      var SemVer = require_semver();
      var identifiers = require_identifiers();
      var parse = require_parse();
      var valid = require_valid();
      var clean = require_clean();
      var inc = require_inc();
      var diff = require_diff();
      var major = require_major();
      var minor = require_minor();
      var patch = require_patch();
      var prerelease = require_prerelease();
      var compare = require_compare();
      var rcompare = require_rcompare();
      var compareLoose = require_compare_loose();
      var compareBuild = require_compare_build();
      var sort = require_sort();
      var rsort = require_rsort();
      var gt = require_gt();
      var lt = require_lt();
      var eq = require_eq();
      var neq = require_neq();
      var gte = require_gte();
      var lte = require_lte();
      var cmp = require_cmp();
      var coerce = require_coerce();
      var truncate = require_truncate();
      var Comparator = require_comparator();
      var Range = require_range();
      var satisfies = require_satisfies();
      var toComparators = require_to_comparators();
      var maxSatisfying = require_max_satisfying();
      var minSatisfying = require_min_satisfying();
      var minVersion = require_min_version();
      var validRange = require_valid2();
      var outside = require_outside();
      var gtr = require_gtr();
      var ltr = require_ltr();
      var intersects = require_intersects();
      var simplifyRange = require_simplify();
      var subset = require_subset();
      module.exports = {
        parse,
        valid,
        clean,
        inc,
        diff,
        major,
        minor,
        patch,
        prerelease,
        compare,
        rcompare,
        compareLoose,
        compareBuild,
        sort,
        rsort,
        gt,
        lt,
        eq,
        neq,
        gte,
        lte,
        cmp,
        coerce,
        truncate,
        Comparator,
        Range,
        satisfies,
        toComparators,
        maxSatisfying,
        minSatisfying,
        minVersion,
        validRange,
        outside,
        gtr,
        ltr,
        intersects,
        simplifyRange,
        subset,
        SemVer,
        re: internalRe.re,
        src: internalRe.src,
        tokens: internalRe.t,
        SEMVER_SPEC_VERSION: constants.SEMVER_SPEC_VERSION,
        RELEASE_TYPES: constants.RELEASE_TYPES,
        compareIdentifiers: identifiers.compareIdentifiers,
        rcompareIdentifiers: identifiers.rcompareIdentifiers
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/lru-cache@11.5.1/node_modules/lru-cache/dist/commonjs/index.min.js
  var require_index_min = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/lru-cache@11.5.1/node_modules/lru-cache/dist/commonjs/index.min.js"(exports) {
      "use strict";
      var j = (c, t) => () => (t || c((t = { exports: {} }).exports, t), t.exports);
      var I = j((O) => {
        "use strict";
        Object.defineProperty(O, "__esModule", { value: true });
        O.tracing = O.metrics = void 0;
        var U = { hasSubscribers: false };
        O.metrics = U;
        O.tracing = U;
      });
      var P = j((D) => {
        "use strict";
        Object.defineProperty(D, "__esModule", { value: true });
        D.defaultPerf = void 0;
        D.defaultPerf = typeof performance == "object" && performance && typeof performance.now == "function" ? performance : Date;
      });
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.LRUCache = void 0;
      var g = I();
      var N = P();
      var x = () => g.metrics.hasSubscribers || g.tracing.hasSubscribers;
      var k = /* @__PURE__ */ new Set();
      var G = typeof process == "object" && process ? process : {};
      var V = (c, t, e, i) => {
        typeof G.emitWarning == "function" ? G.emitWarning(c, t, e, i) : console.error(`[${e}] ${t}: ${c}`);
      };
      var B = (c) => !k.has(c);
      var T = (c) => !!c && c === Math.floor(c) && c > 0 && isFinite(c);
      var H = (c) => T(c) ? c <= Math.pow(2, 8) ? Uint8Array : c <= Math.pow(2, 16) ? Uint16Array : c <= Math.pow(2, 32) ? Uint32Array : c <= Number.MAX_SAFE_INTEGER ? W : null : null;
      var W = class extends Array {
        constructor(t) {
          super(t), this.fill(0);
        }
      };
      var C = class c {
        heap;
        length;
        static #o = false;
        static create(t) {
          let e = H(t);
          if (!e) return [];
          c.#o = true;
          let i = new c(t, e);
          return c.#o = false, i;
        }
        constructor(t, e) {
          if (!c.#o) throw new TypeError("instantiate Stack using Stack.create(n)");
          this.heap = new e(t), this.length = 0;
        }
        push(t) {
          this.heap[this.length++] = t;
        }
        pop() {
          return this.heap[--this.length];
        }
      };
      var L = class c {
        #o;
        #c;
        #m;
        #W;
        #S;
        #M;
        #j;
        #w;
        get perf() {
          return this.#w;
        }
        ttl;
        ttlResolution;
        ttlAutopurge;
        updateAgeOnGet;
        updateAgeOnHas;
        allowStale;
        noDisposeOnSet;
        noUpdateTTL;
        maxEntrySize;
        sizeCalculation;
        noDeleteOnFetchRejection;
        noDeleteOnStaleGet;
        allowStaleOnFetchAbort;
        allowStaleOnFetchRejection;
        ignoreFetchAbort;
        backgroundFetchSize;
        #n;
        #b;
        #s;
        #i;
        #t;
        #l;
        #u;
        #a;
        #h;
        #y;
        #r;
        #_;
        #F;
        #d;
        #g;
        #T;
        #U;
        #f;
        #D;
        static unsafeExposeInternals(t) {
          return { starts: t.#F, ttls: t.#d, autopurgeTimers: t.#g, sizes: t.#_, keyMap: t.#s, keyList: t.#i, valList: t.#t, next: t.#l, prev: t.#u, get head() {
            return t.#a;
          }, get tail() {
            return t.#h;
          }, free: t.#y, isBackgroundFetch: (e) => t.#e(e), backgroundFetch: (e, i, s, n) => t.#G(e, i, s, n), moveToTail: (e) => t.#L(e), indexes: (e) => t.#A(e), rindexes: (e) => t.#z(e), isStale: (e) => t.#p(e) };
        }
        get max() {
          return this.#o;
        }
        get maxSize() {
          return this.#c;
        }
        get calculatedSize() {
          return this.#b;
        }
        get size() {
          return this.#n;
        }
        get fetchMethod() {
          return this.#M;
        }
        get memoMethod() {
          return this.#j;
        }
        get dispose() {
          return this.#m;
        }
        get onInsert() {
          return this.#W;
        }
        get disposeAfter() {
          return this.#S;
        }
        constructor(t) {
          let { max: e = 0, ttl: i, ttlResolution: s = 1, ttlAutopurge: n, updateAgeOnGet: r, updateAgeOnHas: h, allowStale: a, dispose: o, onInsert: d, disposeAfter: y, noDisposeOnSet: _, noUpdateTTL: u, maxSize: p = 0, maxEntrySize: f = 0, sizeCalculation: b, fetchMethod: l, memoMethod: S, noDeleteOnFetchRejection: F, noDeleteOnStaleGet: w, allowStaleOnFetchRejection: m, allowStaleOnFetchAbort: A, ignoreFetchAbort: z, backgroundFetchSize: M = 1, perf: v } = t;
          if (this.backgroundFetchSize = M, v !== void 0 && typeof v?.now != "function") throw new TypeError("perf option must have a now() method if specified");
          if (this.#w = v ?? N.defaultPerf, e !== 0 && !T(e)) throw new TypeError("max option must be a nonnegative integer");
          let E = e ? H(e) : Array;
          if (!E) throw new Error("invalid max value: " + e);
          if (this.#o = e, this.#c = p, this.maxEntrySize = f || this.#c, this.sizeCalculation = b, this.sizeCalculation) {
            if (!this.#c && !this.maxEntrySize) throw new TypeError("cannot set sizeCalculation without setting maxSize or maxEntrySize");
            if (typeof this.sizeCalculation != "function") throw new TypeError("sizeCalculation set to non-function");
          }
          if (S !== void 0 && typeof S != "function") throw new TypeError("memoMethod must be a function if defined");
          if (this.#j = S, l !== void 0 && typeof l != "function") throw new TypeError("fetchMethod must be a function if specified");
          if (this.#M = l, this.#U = !!l, this.#s = /* @__PURE__ */ new Map(), this.#i = Array.from({ length: e }).fill(void 0), this.#t = Array.from({ length: e }).fill(void 0), this.#l = new E(e), this.#u = new E(e), this.#a = 0, this.#h = 0, this.#y = C.create(e), this.#n = 0, this.#b = 0, typeof o == "function" && (this.#m = o), typeof d == "function" && (this.#W = d), typeof y == "function" ? (this.#S = y, this.#r = []) : (this.#S = void 0, this.#r = void 0), this.#T = !!this.#m, this.#D = !!this.#W, this.#f = !!this.#S, this.noDisposeOnSet = !!_, this.noUpdateTTL = !!u, this.noDeleteOnFetchRejection = !!F, this.allowStaleOnFetchRejection = !!m, this.allowStaleOnFetchAbort = !!A, this.ignoreFetchAbort = !!z, this.maxEntrySize !== 0) {
            if (this.#c !== 0 && !T(this.#c)) throw new TypeError("maxSize must be a positive integer if specified");
            if (!T(this.maxEntrySize)) throw new TypeError("maxEntrySize must be a positive integer if specified");
            this.#X();
          }
          if (this.allowStale = !!a, this.noDeleteOnStaleGet = !!w, this.updateAgeOnGet = !!r, this.updateAgeOnHas = !!h, this.ttlResolution = T(s) || s === 0 ? s : 1, this.ttlAutopurge = !!n, this.ttl = i || 0, this.ttl) {
            if (!T(this.ttl)) throw new TypeError("ttl must be a positive integer if specified");
            this.#k();
          }
          if (this.#o === 0 && this.ttl === 0 && this.#c === 0) throw new TypeError("At least one of max, maxSize, or ttl is required");
          if (!this.ttlAutopurge && !this.#o && !this.#c) {
            let R = "LRU_CACHE_UNBOUNDED";
            B(R) && (k.add(R), V("TTL caching without ttlAutopurge, max, or maxSize can result in unbounded memory consumption.", "UnboundedCacheWarning", R, c));
          }
        }
        getRemainingTTL(t) {
          return this.#s.has(t) ? 1 / 0 : 0;
        }
        #k() {
          let t = new W(this.#o), e = new W(this.#o);
          this.#d = t, this.#F = e;
          let i = this.ttlAutopurge ? Array.from({ length: this.#o }) : void 0;
          this.#g = i, this.#H = (h, a, o = this.#w.now()) => {
            e[h] = a !== 0 ? o : 0, t[h] = a, s(h, a);
          }, this.#R = (h) => {
            e[h] = t[h] !== 0 ? this.#w.now() : 0, s(h, t[h]);
          };
          let s = this.ttlAutopurge ? (h, a) => {
            if (i?.[h] && (clearTimeout(i[h]), i[h] = void 0), a && a !== 0 && i) {
              let o = setTimeout(() => {
                this.#p(h) && this.#v(this.#i[h], "expire");
              }, a + 1);
              o.unref && o.unref(), i[h] = o;
            }
          } : () => {
          };
          this.#E = (h, a) => {
            if (t[a]) {
              let o = t[a], d = e[a];
              if (!o || !d) return;
              h.ttl = o, h.start = d, h.now = n || r();
              let y = h.now - d;
              h.remainingTTL = o - y;
            }
          };
          let n = 0, r = () => {
            let h = this.#w.now();
            if (this.ttlResolution > 0) {
              n = h;
              let a = setTimeout(() => n = 0, this.ttlResolution);
              a.unref && a.unref();
            }
            return h;
          };
          this.getRemainingTTL = (h) => {
            let a = this.#s.get(h);
            if (a === void 0) return 0;
            let o = t[a], d = e[a];
            if (!o || !d) return 1 / 0;
            let y = (n || r()) - d;
            return o - y;
          }, this.#p = (h) => {
            let a = e[h], o = t[h];
            return !!o && !!a && (n || r()) - a > o;
          };
        }
        #R = () => {
        };
        #E = () => {
        };
        #H = () => {
        };
        #p = () => false;
        #X() {
          let t = new W(this.#o);
          this.#b = 0, this.#_ = t, this.#x = (e) => {
            this.#b -= t[e], t[e] = 0;
          }, this.#N = (e, i, s, n) => {
            if (!T(s)) {
              if (this.#e(i)) return this.backgroundFetchSize;
              if (n) {
                if (typeof n != "function") throw new TypeError("sizeCalculation must be a function");
                if (s = n(i, e), !T(s)) throw new TypeError("sizeCalculation return invalid (expect positive integer)");
              } else throw new TypeError("invalid size value (must be positive integer). When maxSize or maxEntrySize is used, sizeCalculation or size must be set.");
            }
            return s;
          }, this.#I = (e, i, s) => {
            if (t[e] = i, this.#c) {
              let n = this.#c - t[e];
              for (; this.#b > n; ) this.#P(true);
            }
            this.#b += t[e], s && (s.entrySize = i, s.totalCalculatedSize = this.#b);
          };
        }
        #x = (t) => {
        };
        #I = (t, e, i) => {
        };
        #N = (t, e, i, s) => {
          if (i || s) throw new TypeError("cannot set size without setting maxSize or maxEntrySize on cache");
          return 0;
        };
        *#A({ allowStale: t = this.allowStale } = {}) {
          if (this.#n) for (let e = this.#h; this.#V(e) && ((t || !this.#p(e)) && (yield e), e !== this.#a); ) e = this.#u[e];
        }
        *#z({ allowStale: t = this.allowStale } = {}) {
          if (this.#n) for (let e = this.#a; this.#V(e) && ((t || !this.#p(e)) && (yield e), e !== this.#h); ) e = this.#l[e];
        }
        #V(t) {
          return t !== void 0 && this.#s.get(this.#i[t]) === t;
        }
        *entries() {
          for (let t of this.#A()) this.#t[t] !== void 0 && this.#i[t] !== void 0 && !this.#e(this.#t[t]) && (yield [this.#i[t], this.#t[t]]);
        }
        *rentries() {
          for (let t of this.#z()) this.#t[t] !== void 0 && this.#i[t] !== void 0 && !this.#e(this.#t[t]) && (yield [this.#i[t], this.#t[t]]);
        }
        *keys() {
          for (let t of this.#A()) {
            let e = this.#i[t];
            e !== void 0 && !this.#e(this.#t[t]) && (yield e);
          }
        }
        *rkeys() {
          for (let t of this.#z()) {
            let e = this.#i[t];
            e !== void 0 && !this.#e(this.#t[t]) && (yield e);
          }
        }
        *values() {
          for (let t of this.#A()) this.#t[t] !== void 0 && !this.#e(this.#t[t]) && (yield this.#t[t]);
        }
        *rvalues() {
          for (let t of this.#z()) this.#t[t] !== void 0 && !this.#e(this.#t[t]) && (yield this.#t[t]);
        }
        [Symbol.iterator]() {
          return this.entries();
        }
        [Symbol.toStringTag] = "LRUCache";
        find(t, e = {}) {
          for (let i of this.#A()) {
            let s = this.#t[i], n = this.#e(s) ? s.__staleWhileFetching : s;
            if (n !== void 0 && t(n, this.#i[i], this)) return this.#C(this.#i[i], e);
          }
        }
        forEach(t, e = this) {
          for (let i of this.#A()) {
            let s = this.#t[i], n = this.#e(s) ? s.__staleWhileFetching : s;
            n !== void 0 && t.call(e, n, this.#i[i], this);
          }
        }
        rforEach(t, e = this) {
          for (let i of this.#z()) {
            let s = this.#t[i], n = this.#e(s) ? s.__staleWhileFetching : s;
            n !== void 0 && t.call(e, n, this.#i[i], this);
          }
        }
        purgeStale() {
          let t = false;
          for (let e of this.#z({ allowStale: true })) this.#p(e) && (this.#v(this.#i[e], "expire"), t = true);
          return t;
        }
        info(t) {
          let e = this.#s.get(t);
          if (e === void 0) return;
          let i = this.#t[e], s = this.#e(i) ? i.__staleWhileFetching : i;
          if (s === void 0) return;
          let n = { value: s };
          if (this.#d && this.#F) {
            let r = this.#d[e], h = this.#F[e];
            if (r && h) {
              let a = r - (this.#w.now() - h);
              n.ttl = a, n.start = Date.now();
            }
          }
          return this.#_ && (n.size = this.#_[e]), n;
        }
        dump() {
          let t = [];
          for (let e of this.#A({ allowStale: true })) {
            let i = this.#i[e], s = this.#t[e], n = this.#e(s) ? s.__staleWhileFetching : s;
            if (n === void 0 || i === void 0) continue;
            let r = { value: n };
            if (this.#d && this.#F) {
              r.ttl = this.#d[e];
              let h = this.#w.now() - this.#F[e];
              r.start = Math.floor(Date.now() - h);
            }
            this.#_ && (r.size = this.#_[e]), t.unshift([i, r]);
          }
          return t;
        }
        load(t) {
          this.clear();
          for (let [e, i] of t) {
            if (i.start) {
              let s = Date.now() - i.start;
              i.start = this.#w.now() - s;
            }
            this.#O(e, i.value, i);
          }
        }
        set(t, e, i = {}) {
          let { status: s = g.metrics.hasSubscribers ? {} : void 0 } = i;
          i.status = s, s && (s.op = "set", s.key = t, e !== void 0 && (s.value = e), s.cache = this);
          let n = this.#O(t, e, i);
          return s && g.metrics.hasSubscribers && g.metrics.publish(s), n;
        }
        #O(t, e, i, s) {
          let { ttl: n = this.ttl, start: r, noDisposeOnSet: h = this.noDisposeOnSet, sizeCalculation: a = this.sizeCalculation, status: o } = i, d = this.#e(e);
          if (e === void 0) return o && (o.set = "deleted"), this.delete(t), this;
          let { noUpdateTTL: y = this.noUpdateTTL } = i;
          o && !d && (o.value = e);
          let _ = this.#N(t, e, i.size || 0, a, o);
          if (this.maxEntrySize && _ > this.maxEntrySize) return this.#v(t, "set"), o && (o.set = "miss", o.maxEntrySizeExceeded = true), this;
          let u = this.#n === 0 ? void 0 : this.#s.get(t);
          if (u === void 0) u = this.#n === 0 ? this.#h : this.#y.length !== 0 ? this.#y.pop() : this.#n === this.#o ? this.#P(false) : this.#n, this.#i[u] = t, this.#t[u] = e, this.#s.set(t, u), this.#l[this.#h] = u, this.#u[u] = this.#h, this.#h = u, this.#n++, this.#I(u, _, o), o && (o.set = "add"), y = false, this.#D && !d && this.#W?.(e, t, "add");
          else {
            this.#L(u);
            let p = this.#t[u];
            if (e !== p) {
              if (!h) if (this.#e(p)) {
                p !== s && p.__abortController.abort(new Error("replaced"));
                let { __staleWhileFetching: f } = p;
                f !== void 0 && f !== e && (this.#T && this.#m?.(f, t, "set"), this.#f && this.#r?.push([f, t, "set"]));
              } else this.#T && this.#m?.(p, t, "set"), this.#f && this.#r?.push([p, t, "set"]);
              if (this.#x(u), this.#I(u, _, o), this.#t[u] = e, !d) {
                let f = p && this.#e(p) ? p.__staleWhileFetching : p, b = f === void 0 ? "add" : e !== f ? "replace" : "update";
                o && (o.set = b, f !== void 0 && (o.oldValue = f)), this.#D && this.onInsert?.(e, t, b);
              }
            } else d || (o && (o.set = "update"), this.#D && this.onInsert?.(e, t, "update"));
          }
          if (n !== 0 && !this.#d && this.#k(), this.#d && (y || this.#H(u, n, r), o && this.#E(o, u)), !h && this.#f && this.#r) {
            let p = this.#r, f;
            for (; f = p?.shift(); ) this.#S?.(...f);
          }
          return this;
        }
        pop() {
          try {
            for (; this.#n; ) {
              let t = this.#t[this.#a];
              if (this.#P(true), this.#e(t)) {
                if (t.__staleWhileFetching) return t.__staleWhileFetching;
              } else if (t !== void 0) return t;
            }
          } finally {
            if (this.#f && this.#r) {
              let t = this.#r, e;
              for (; e = t?.shift(); ) this.#S?.(...e);
            }
          }
        }
        #P(t) {
          let e = this.#a, i = this.#i[e], s = this.#t[e], n = this.#e(s);
          n && s.__abortController.abort(new Error("evicted"));
          let r = n ? s.__staleWhileFetching : s;
          return (this.#T || this.#f) && r !== void 0 && (this.#T && this.#m?.(r, i, "evict"), this.#f && this.#r?.push([r, i, "evict"])), this.#x(e), this.#g?.[e] && (clearTimeout(this.#g[e]), this.#g[e] = void 0), t && (this.#i[e] = void 0, this.#t[e] = void 0, this.#y.push(e)), this.#n === 1 ? (this.#a = this.#h = 0, this.#y.length = 0) : this.#a = this.#l[e], this.#s.delete(i), this.#n--, e;
        }
        has(t, e = {}) {
          let { status: i = g.metrics.hasSubscribers ? {} : void 0 } = e;
          e.status = i, i && (i.op = "has", i.key = t, i.cache = this);
          let s = this.#Y(t, e);
          return g.metrics.hasSubscribers && g.metrics.publish(i), s;
        }
        #Y(t, e = {}) {
          let { updateAgeOnHas: i = this.updateAgeOnHas, status: s } = e, n = this.#s.get(t);
          if (n !== void 0) {
            let r = this.#t[n];
            if (this.#e(r) && r.__staleWhileFetching === void 0) return false;
            if (this.#p(n)) s && (s.has = "stale", this.#E(s, n));
            else return i && this.#R(n), s && (s.has = "hit", this.#E(s, n)), true;
          } else s && (s.has = "miss");
          return false;
        }
        peek(t, e = {}) {
          let { status: i = x() ? {} : void 0 } = e;
          i && (i.op = "peek", i.key = t, i.cache = this), e.status = i;
          let s = this.#J(t, e);
          return g.metrics.hasSubscribers && g.metrics.publish(i), s;
        }
        #J(t, e) {
          let { status: i, allowStale: s = this.allowStale } = e, n = this.#s.get(t);
          if (n === void 0 || !s && this.#p(n)) {
            i && (i.peek = n === void 0 ? "miss" : "stale");
            return;
          }
          let r = this.#t[n], h = this.#e(r) ? r.__staleWhileFetching : r;
          return i && (h !== void 0 ? (i.peek = "hit", i.value = h) : i.peek = "miss"), h;
        }
        #G(t, e, i, s) {
          let n = e === void 0 ? void 0 : this.#t[e];
          if (this.#e(n)) return n;
          let r = new AbortController(), { signal: h } = i;
          h?.addEventListener("abort", () => r.abort(h.reason), { signal: r.signal });
          let a = { signal: r.signal, options: i, context: s }, o = (f, b = false) => {
            let { aborted: l } = r.signal, S = i.ignoreFetchAbort && f !== void 0, F = i.ignoreFetchAbort || !!(i.allowStaleOnFetchAbort && f !== void 0);
            if (i.status && (l && !b ? (i.status.fetchAborted = true, i.status.fetchError = r.signal.reason, S && (i.status.fetchAbortIgnored = true)) : i.status.fetchResolved = true), l && !S && !b) return y(r.signal.reason, F);
            let w = u, m = this.#t[e];
            return (m === u || m === void 0 && S && b) && (f === void 0 ? w.__staleWhileFetching !== void 0 ? this.#t[e] = w.__staleWhileFetching : this.#v(t, "fetch") : (i.status && (i.status.fetchUpdated = true), this.#O(t, f, a.options, w))), f;
          }, d = (f) => (i.status && (i.status.fetchRejected = true, i.status.fetchError = f), y(f, false)), y = (f, b) => {
            let { aborted: l } = r.signal, S = l && i.allowStaleOnFetchAbort, F = S || i.allowStaleOnFetchRejection, w = F || i.noDeleteOnFetchRejection, m = u;
            if (this.#t[e] === u && (!w || !b && m.__staleWhileFetching === void 0 ? this.#v(t, "fetch") : S || (this.#t[e] = m.__staleWhileFetching)), F) return i.status && m.__staleWhileFetching !== void 0 && (i.status.returnedStale = true), m.__staleWhileFetching;
            if (m.__returned === m) throw f;
          }, _ = (f, b) => {
            let l = this.#M?.(t, n, a);
            r.signal.addEventListener("abort", () => {
              (!i.ignoreFetchAbort || i.allowStaleOnFetchAbort) && (f(void 0), i.allowStaleOnFetchAbort && (f = (S) => o(S, true)));
            }), l && l instanceof Promise ? l.then((S) => f(S === void 0 ? void 0 : S), b) : l !== void 0 && f(l);
          };
          i.status && (i.status.fetchDispatched = true);
          let u = new Promise(_).then(o, d), p = Object.assign(u, { __abortController: r, __staleWhileFetching: n, __returned: void 0 });
          return e === void 0 ? (this.#O(t, p, { ...a.options, status: void 0 }), e = this.#s.get(t)) : this.#t[e] = p, p;
        }
        #e(t) {
          if (!this.#U) return false;
          let e = t;
          return !!e && e instanceof Promise && e.hasOwnProperty("__staleWhileFetching") && e.__abortController instanceof AbortController;
        }
        fetch(t, e = {}) {
          let i = g.tracing.hasSubscribers, { status: s = x() ? {} : void 0 } = e;
          e.status = s, s && e.context && (s.context = e.context);
          let n = this.#B(t, e);
          return s && i && (s.trace = true, g.tracing.tracePromise(() => n, s).catch(() => {
          })), n;
        }
        async #B(t, e = {}) {
          let { allowStale: i = this.allowStale, updateAgeOnGet: s = this.updateAgeOnGet, noDeleteOnStaleGet: n = this.noDeleteOnStaleGet, ttl: r = this.ttl, noDisposeOnSet: h = this.noDisposeOnSet, size: a = 0, sizeCalculation: o = this.sizeCalculation, noUpdateTTL: d = this.noUpdateTTL, noDeleteOnFetchRejection: y = this.noDeleteOnFetchRejection, allowStaleOnFetchRejection: _ = this.allowStaleOnFetchRejection, ignoreFetchAbort: u = this.ignoreFetchAbort, allowStaleOnFetchAbort: p = this.allowStaleOnFetchAbort, context: f, forceRefresh: b = false, status: l, signal: S } = e;
          if (l && (l.op = "fetch", l.key = t, b && (l.forceRefresh = true), l.cache = this), !this.#U) return l && (l.fetch = "get"), this.#C(t, { allowStale: i, updateAgeOnGet: s, noDeleteOnStaleGet: n, status: l });
          let F = { allowStale: i, updateAgeOnGet: s, noDeleteOnStaleGet: n, ttl: r, noDisposeOnSet: h, size: a, sizeCalculation: o, noUpdateTTL: d, noDeleteOnFetchRejection: y, allowStaleOnFetchRejection: _, allowStaleOnFetchAbort: p, ignoreFetchAbort: u, status: l, signal: S }, w = this.#s.get(t);
          if (w === void 0) {
            l && (l.fetch = "miss");
            let m = this.#G(t, w, F, f);
            return m.__returned = m;
          } else {
            let m = this.#t[w];
            if (this.#e(m)) {
              let E = i && m.__staleWhileFetching !== void 0;
              return l && (l.fetch = "inflight", E && (l.returnedStale = true)), E ? m.__staleWhileFetching : m.__returned = m;
            }
            let A = this.#p(w);
            if (!b && !A) return l && (l.fetch = "hit"), this.#L(w), s && this.#R(w), l && this.#E(l, w), m;
            let z = this.#G(t, w, F, f), v = z.__staleWhileFetching !== void 0 && i;
            return l && (l.fetch = A ? "stale" : "refresh", v && A && (l.returnedStale = true)), v ? z.__staleWhileFetching : z.__returned = z;
          }
        }
        forceFetch(t, e = {}) {
          let i = g.tracing.hasSubscribers, { status: s = x() ? {} : void 0 } = e;
          e.status = s, s && e.context && (s.context = e.context);
          let n = this.#K(t, e);
          return s && i && (s.trace = true, g.tracing.tracePromise(() => n, s).catch(() => {
          })), n;
        }
        async #K(t, e = {}) {
          let i = await this.#B(t, e);
          if (i === void 0) throw new Error("fetch() returned undefined");
          return i;
        }
        memo(t, e = {}) {
          let { status: i = g.metrics.hasSubscribers ? {} : void 0 } = e;
          e.status = i, i && (i.op = "memo", i.key = t, e.context && (i.context = e.context), i.cache = this);
          let s = this.#Q(t, e);
          return i && (i.value = s), g.metrics.hasSubscribers && g.metrics.publish(i), s;
        }
        #Q(t, e = {}) {
          let i = this.#j;
          if (!i) throw new Error("no memoMethod provided to constructor");
          let { context: s, status: n, forceRefresh: r, ...h } = e;
          n && r && (n.forceRefresh = true);
          let a = this.#C(t, h), o = r || a === void 0;
          if (n && (n.memo = o ? "miss" : "hit", o || (n.value = a)), !o) return a;
          let d = i(t, a, { options: h, context: s });
          return n && (n.value = d), this.#O(t, d, h), d;
        }
        get(t, e = {}) {
          let { status: i = g.metrics.hasSubscribers ? {} : void 0 } = e;
          e.status = i, i && (i.op = "get", i.key = t, i.cache = this);
          let s = this.#C(t, e);
          return i && (s !== void 0 && (i.value = s), g.metrics.hasSubscribers && g.metrics.publish(i)), s;
        }
        #C(t, e = {}) {
          let { allowStale: i = this.allowStale, updateAgeOnGet: s = this.updateAgeOnGet, noDeleteOnStaleGet: n = this.noDeleteOnStaleGet, status: r } = e, h = this.#s.get(t);
          if (h === void 0) {
            r && (r.get = "miss");
            return;
          }
          let a = this.#t[h], o = this.#e(a);
          return r && this.#E(r, h), this.#p(h) ? o ? (r && (r.get = "stale-fetching"), i && a.__staleWhileFetching !== void 0 ? (r && (r.returnedStale = true), a.__staleWhileFetching) : void 0) : (n || this.#v(t, "expire"), r && (r.get = "stale"), i ? (r && (r.returnedStale = true), a) : void 0) : (r && (r.get = o ? "fetching" : "hit"), this.#L(h), s && this.#R(h), o ? a.__staleWhileFetching : a);
        }
        #q(t, e) {
          this.#u[e] = t, this.#l[t] = e;
        }
        #L(t) {
          t !== this.#h && (t === this.#a ? this.#a = this.#l[t] : this.#q(this.#u[t], this.#l[t]), this.#q(this.#h, t), this.#h = t);
        }
        delete(t) {
          return this.#v(t, "delete");
        }
        #v(t, e) {
          g.metrics.hasSubscribers && g.metrics.publish({ op: "delete", delete: e, key: t, cache: this });
          let i = false;
          if (this.#n !== 0) {
            let s = this.#s.get(t);
            if (s !== void 0) if (this.#g?.[s] && (clearTimeout(this.#g?.[s]), this.#g[s] = void 0), i = true, this.#n === 1) this.#$(e);
            else {
              this.#x(s);
              let n = this.#t[s];
              if (this.#e(n) ? n.__abortController.abort(new Error("deleted")) : (this.#T || this.#f) && (this.#T && this.#m?.(n, t, e), this.#f && this.#r?.push([n, t, e])), this.#s.delete(t), this.#i[s] = void 0, this.#t[s] = void 0, s === this.#h) this.#h = this.#u[s];
              else if (s === this.#a) this.#a = this.#l[s];
              else {
                let r = this.#u[s];
                this.#l[r] = this.#l[s];
                let h = this.#l[s];
                this.#u[h] = this.#u[s];
              }
              this.#n--, this.#y.push(s);
            }
          }
          if (this.#f && this.#r?.length) {
            let s = this.#r, n;
            for (; n = s?.shift(); ) this.#S?.(...n);
          }
          return i;
        }
        clear() {
          return this.#$("delete");
        }
        #$(t) {
          for (let e of this.#z({ allowStale: true })) {
            let i = this.#t[e];
            if (this.#e(i)) i.__abortController.abort(new Error("deleted"));
            else {
              let s = this.#i[e];
              this.#T && this.#m?.(i, s, t), this.#f && this.#r?.push([i, s, t]);
            }
          }
          if (this.#s.clear(), this.#t.fill(void 0), this.#i.fill(void 0), this.#d && this.#F) {
            this.#d.fill(0), this.#F.fill(0);
            for (let e of this.#g ?? []) e !== void 0 && clearTimeout(e);
            this.#g?.fill(void 0);
          }
          if (this.#_ && this.#_.fill(0), this.#a = 0, this.#h = 0, this.#y.length = 0, this.#b = 0, this.#n = 0, this.#f && this.#r) {
            let e = this.#r, i;
            for (; i = e?.shift(); ) this.#S?.(...i);
          }
        }
      };
      exports.LRUCache = L;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/hosts.js
  var require_hosts = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/hosts.js"(exports, module) {
      "use strict";
      var maybeJoin = (...args) => args.every((arg) => arg) ? args.join("") : "";
      var maybeEncode = (arg) => arg ? encodeURIComponent(arg) : "";
      var formatHashFragment = (f) => f.toLowerCase().replace(/^\W+/g, "").replace(/(?<!\W)\W+$/, "").replace(/\//g, "").replace(/\W+/g, "-");
      var defaults = {
        sshtemplate: ({ domain, user, project, committish }) => `git@${domain}:${user}/${project}.git${maybeJoin("#", committish)}`,
        sshurltemplate: ({ domain, user, project, committish }) => `git+ssh://git@${domain}/${user}/${project}.git${maybeJoin("#", committish)}`,
        edittemplate: ({ domain, user, project, committish, editpath, path }) => `https://${domain}/${user}/${project}${maybeJoin("/", editpath, "/", maybeEncode(committish || "HEAD"), "/", path)}`,
        browsetemplate: ({ domain, user, project, committish, treepath }) => `https://${domain}/${user}/${project}${maybeJoin("/", treepath, "/", maybeEncode(committish))}`,
        browsetreetemplate: ({ domain, user, project, committish, treepath, path, fragment, hashformat }) => `https://${domain}/${user}/${project}/${treepath}/${maybeEncode(committish || "HEAD")}/${path}${maybeJoin("#", hashformat(fragment || ""))}`,
        browseblobtemplate: ({ domain, user, project, committish, blobpath, path, fragment, hashformat }) => `https://${domain}/${user}/${project}/${blobpath}/${maybeEncode(committish || "HEAD")}/${path}${maybeJoin("#", hashformat(fragment || ""))}`,
        docstemplate: ({ domain, user, project, treepath, committish }) => `https://${domain}/${user}/${project}${maybeJoin("/", treepath, "/", maybeEncode(committish))}#readme`,
        httpstemplate: ({ auth, domain, user, project, committish }) => `git+https://${maybeJoin(auth, "@")}${domain}/${user}/${project}.git${maybeJoin("#", committish)}`,
        filetemplate: ({ domain, user, project, committish, path }) => `https://${domain}/${user}/${project}/raw/${maybeEncode(committish || "HEAD")}/${path}`,
        shortcuttemplate: ({ type, user, project, committish }) => `${type}:${user}/${project}${maybeJoin("#", committish)}`,
        pathtemplate: ({ user, project, committish }) => `${user}/${project}${maybeJoin("#", committish)}`,
        bugstemplate: ({ domain, user, project }) => `https://${domain}/${user}/${project}/issues`,
        hashformat: formatHashFragment
      };
      var hosts = {};
      hosts.github = {
        // First two are insecure and generally shouldn't be used any more, but
        // they are still supported.
        protocols: ["git:", "http:", "git+ssh:", "git+https:", "ssh:", "https:"],
        domain: "github.com",
        treepath: "tree",
        blobpath: "blob",
        editpath: "edit",
        filetemplate: ({ auth, user, project, committish, path }) => `https://${maybeJoin(auth, "@")}raw.githubusercontent.com/${user}/${project}/${maybeEncode(committish || "HEAD")}/${path}`,
        gittemplate: ({ auth, domain, user, project, committish }) => `git://${maybeJoin(auth, "@")}${domain}/${user}/${project}.git${maybeJoin("#", committish)}`,
        tarballtemplate: ({ domain, user, project, committish }) => `https://codeload.${domain}/${user}/${project}/tar.gz/${maybeEncode(committish || "HEAD")}`,
        extract: (url) => {
          let [, user, project, type, committish] = url.pathname.split("/", 5);
          if (type && type !== "tree") {
            return;
          }
          if (!type) {
            committish = url.hash.slice(1);
          }
          if (project && project.endsWith(".git")) {
            project = project.slice(0, -4);
          }
          if (!user || !project) {
            return;
          }
          return { user, project, committish };
        }
      };
      hosts.bitbucket = {
        protocols: ["git+ssh:", "git+https:", "ssh:", "https:"],
        domain: "bitbucket.org",
        treepath: "src",
        blobpath: "src",
        editpath: "?mode=edit",
        edittemplate: ({ domain, user, project, committish, treepath, path, editpath }) => `https://${domain}/${user}/${project}${maybeJoin("/", treepath, "/", maybeEncode(committish || "HEAD"), "/", path, editpath)}`,
        tarballtemplate: ({ domain, user, project, committish }) => `https://${domain}/${user}/${project}/get/${maybeEncode(committish || "HEAD")}.tar.gz`,
        extract: (url) => {
          let [, user, project, aux] = url.pathname.split("/", 4);
          if (["get"].includes(aux)) {
            return;
          }
          if (project && project.endsWith(".git")) {
            project = project.slice(0, -4);
          }
          if (!user || !project) {
            return;
          }
          return { user, project, committish: url.hash.slice(1) };
        }
      };
      hosts.gitlab = {
        protocols: ["git+ssh:", "git+https:", "ssh:", "https:"],
        domain: "gitlab.com",
        treepath: "tree",
        blobpath: "tree",
        editpath: "-/edit",
        tarballtemplate: ({ domain, user, project, committish }) => `https://${domain}/api/v4/projects/${maybeEncode(user + "/" + project)}/repository/archive.tar.gz?sha=${maybeEncode(committish || "HEAD")}`,
        extract: (url) => {
          const path = url.pathname.slice(1);
          if (path.includes("/-/") || path.includes("/archive.tar.gz")) {
            return;
          }
          const segments = path.split("/");
          let project = segments.pop();
          if (project.endsWith(".git")) {
            project = project.slice(0, -4);
          }
          const user = segments.join("/");
          if (!user || !project) {
            return;
          }
          return { user, project, committish: url.hash.slice(1) };
        }
      };
      hosts.gist = {
        protocols: ["git:", "git+ssh:", "git+https:", "ssh:", "https:"],
        domain: "gist.github.com",
        editpath: "edit",
        sshtemplate: ({ domain, project, committish }) => `git@${domain}:${project}.git${maybeJoin("#", committish)}`,
        sshurltemplate: ({ domain, project, committish }) => `git+ssh://git@${domain}/${project}.git${maybeJoin("#", committish)}`,
        edittemplate: ({ domain, user, project, committish, editpath }) => `https://${domain}/${user}/${project}${maybeJoin("/", maybeEncode(committish))}/${editpath}`,
        browsetemplate: ({ domain, project, committish }) => `https://${domain}/${project}${maybeJoin("/", maybeEncode(committish))}`,
        browsetreetemplate: ({ domain, project, committish, path, hashformat }) => `https://${domain}/${project}${maybeJoin("/", maybeEncode(committish))}${maybeJoin("#", hashformat(path))}`,
        browseblobtemplate: ({ domain, project, committish, path, hashformat }) => `https://${domain}/${project}${maybeJoin("/", maybeEncode(committish))}${maybeJoin("#", hashformat(path))}`,
        docstemplate: ({ domain, project, committish }) => `https://${domain}/${project}${maybeJoin("/", maybeEncode(committish))}`,
        httpstemplate: ({ domain, project, committish }) => `git+https://${domain}/${project}.git${maybeJoin("#", committish)}`,
        filetemplate: ({ user, project, committish, path }) => `https://gist.githubusercontent.com/${user}/${project}/raw${maybeJoin("/", maybeEncode(committish))}/${path}`,
        shortcuttemplate: ({ type, project, committish }) => `${type}:${project}${maybeJoin("#", committish)}`,
        pathtemplate: ({ project, committish }) => `${project}${maybeJoin("#", committish)}`,
        bugstemplate: ({ domain, project }) => `https://${domain}/${project}`,
        gittemplate: ({ domain, project, committish }) => `git://${domain}/${project}.git${maybeJoin("#", committish)}`,
        tarballtemplate: ({ project, committish }) => `https://codeload.github.com/gist/${project}/tar.gz/${maybeEncode(committish || "HEAD")}`,
        extract: (url) => {
          let [, user, project, aux] = url.pathname.split("/", 4);
          if (aux === "raw") {
            return;
          }
          if (!project) {
            if (!user) {
              return;
            }
            project = user;
            user = null;
          }
          if (project.endsWith(".git")) {
            project = project.slice(0, -4);
          }
          return { user, project, committish: url.hash.slice(1) };
        },
        hashformat: function(fragment) {
          return fragment && "file-" + formatHashFragment(fragment);
        }
      };
      hosts.sourcehut = {
        protocols: ["git+ssh:", "https:"],
        domain: "git.sr.ht",
        treepath: "tree",
        blobpath: "tree",
        filetemplate: ({ domain, user, project, committish, path }) => `https://${domain}/${user}/${project}/blob/${maybeEncode(committish) || "HEAD"}/${path}`,
        httpstemplate: ({ domain, user, project, committish }) => `https://${domain}/${user}/${project}${maybeJoin("#", committish)}`,
        tarballtemplate: ({ domain, user, project, committish }) => `https://${domain}/${user}/${project}/archive/${maybeEncode(committish) || "HEAD"}.tar.gz`,
        bugstemplate: () => null,
        extract: (url) => {
          let [, user, project, aux] = url.pathname.split("/", 4);
          if (["archive"].includes(aux)) {
            return;
          }
          if (project && project.endsWith(".git")) {
            project = project.slice(0, -4);
          }
          if (!user || !project) {
            return;
          }
          return { user, project, committish: url.hash.slice(1) };
        }
      };
      for (const [name, host] of Object.entries(hosts)) {
        hosts[name] = Object.assign({}, defaults, host);
      }
      module.exports = hosts;
    }
  });

  // scripts/native/market-index/url.ts
  var url_exports = {};
  __export(url_exports, {
    URL: () => URL2
  });
  var URL2;
  var init_url = __esm({
    "scripts/native/market-index/url.ts"() {
      URL2 = globalThis.URL;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/parse-url.js
  var require_parse_url = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/parse-url.js"(exports, module) {
      var url = (init_url(), __toCommonJS(url_exports));
      var lastIndexOfBefore = (str, char, beforeChar) => {
        const startPosition = str.indexOf(beforeChar);
        return str.lastIndexOf(char, startPosition > -1 ? startPosition : Infinity);
      };
      var safeUrl = (u) => {
        try {
          return new url.URL(u);
        } catch {
        }
      };
      var correctProtocol = (arg, protocols) => {
        const firstColon = arg.indexOf(":");
        const proto = arg.slice(0, firstColon + 1);
        if (Object.prototype.hasOwnProperty.call(protocols, proto)) {
          return arg;
        }
        if (arg.substr(firstColon, 3) === "://") {
          return arg;
        }
        const firstAt = arg.indexOf("@");
        if (firstAt > -1) {
          if (firstAt > firstColon) {
            return `git+ssh://${arg}`;
          } else {
            return arg;
          }
        }
        return `${arg.slice(0, firstColon + 1)}//${arg.slice(firstColon + 1)}`;
      };
      var correctUrl = (giturl) => {
        const firstAt = lastIndexOfBefore(giturl, "@", "#");
        const lastColonBeforeHash = lastIndexOfBefore(giturl, ":", "#");
        if (lastColonBeforeHash > firstAt) {
          giturl = giturl.slice(0, lastColonBeforeHash) + "/" + giturl.slice(lastColonBeforeHash + 1);
        }
        if (lastIndexOfBefore(giturl, ":", "#") === -1 && giturl.indexOf("//") === -1) {
          giturl = `git+ssh://${giturl}`;
        }
        return giturl;
      };
      module.exports = (giturl, protocols) => {
        const withProtocol = protocols ? correctProtocol(giturl, protocols) : giturl;
        return safeUrl(withProtocol) || safeUrl(correctUrl(withProtocol));
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/from-url.js
  var require_from_url = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/from-url.js"(exports, module) {
      "use strict";
      var parseUrl = require_parse_url();
      var isGitHubShorthand = (arg) => {
        const firstHash = arg.indexOf("#");
        const firstSlash = arg.indexOf("/");
        const secondSlash = arg.indexOf("/", firstSlash + 1);
        const firstColon = arg.indexOf(":");
        const firstSpace = /\s/.exec(arg);
        const firstAt = arg.indexOf("@");
        const spaceOnlyAfterHash = !firstSpace || firstHash > -1 && firstSpace.index > firstHash;
        const atOnlyAfterHash = firstAt === -1 || firstHash > -1 && firstAt > firstHash;
        const colonOnlyAfterHash = firstColon === -1 || firstHash > -1 && firstColon > firstHash;
        const secondSlashOnlyAfterHash = secondSlash === -1 || firstHash > -1 && secondSlash > firstHash;
        const hasSlash = firstSlash > 0;
        const doesNotEndWithSlash = firstHash > -1 ? arg[firstHash - 1] !== "/" : !arg.endsWith("/");
        const doesNotStartWithDot = !arg.startsWith(".");
        return spaceOnlyAfterHash && hasSlash && doesNotEndWithSlash && doesNotStartWithDot && atOnlyAfterHash && colonOnlyAfterHash && secondSlashOnlyAfterHash;
      };
      module.exports = (giturl, opts, { gitHosts, protocols }) => {
        if (!giturl) {
          return;
        }
        const correctedUrl = isGitHubShorthand(giturl) ? `github:${giturl}` : giturl;
        const parsed = parseUrl(correctedUrl, protocols);
        if (!parsed) {
          return;
        }
        const gitHostShortcut = gitHosts.byShortcut[parsed.protocol];
        const gitHostDomain = gitHosts.byDomain[parsed.hostname.startsWith("www.") ? parsed.hostname.slice(4) : parsed.hostname];
        const gitHostName = gitHostShortcut || gitHostDomain;
        if (!gitHostName) {
          return;
        }
        const gitHostInfo = gitHosts[gitHostShortcut || gitHostDomain];
        let auth = null;
        if (protocols[parsed.protocol]?.auth && (parsed.username || parsed.password)) {
          auth = `${parsed.username}${parsed.password ? ":" + parsed.password : ""}`;
        }
        let committish = null;
        let user = null;
        let project = null;
        let defaultRepresentation = null;
        try {
          if (gitHostShortcut) {
            let pathname = parsed.pathname.startsWith("/") ? parsed.pathname.slice(1) : parsed.pathname;
            const firstAt = pathname.indexOf("@");
            if (firstAt > -1) {
              pathname = pathname.slice(firstAt + 1);
            }
            const lastSlash = pathname.lastIndexOf("/");
            if (lastSlash > -1) {
              user = decodeURIComponent(pathname.slice(0, lastSlash));
              if (!user) {
                user = null;
              }
              project = decodeURIComponent(pathname.slice(lastSlash + 1));
            } else {
              project = decodeURIComponent(pathname);
            }
            if (project.endsWith(".git")) {
              project = project.slice(0, -4);
            }
            if (parsed.hash) {
              committish = decodeURIComponent(parsed.hash.slice(1));
            }
            defaultRepresentation = "shortcut";
          } else {
            if (!gitHostInfo.protocols.includes(parsed.protocol)) {
              return;
            }
            const segments = gitHostInfo.extract(parsed);
            if (!segments) {
              return;
            }
            user = segments.user && decodeURIComponent(segments.user);
            project = decodeURIComponent(segments.project);
            committish = decodeURIComponent(segments.committish);
            defaultRepresentation = protocols[parsed.protocol]?.name || parsed.protocol.slice(0, -1);
          }
        } catch (err) {
          if (err instanceof URIError) {
            return;
          } else {
            throw err;
          }
        }
        return [gitHostName, user, auth, project, committish, defaultRepresentation, opts];
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/index.js
  var require_lib = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/hosted-git-info@9.0.3/node_modules/hosted-git-info/lib/index.js"(exports, module) {
      "use strict";
      var { LRUCache } = require_index_min();
      var hosts = require_hosts();
      var fromUrl = require_from_url();
      var parseUrl = require_parse_url();
      var cache = new LRUCache({ max: 1e3 });
      function unknownHostedUrl(url) {
        try {
          const {
            protocol,
            hostname,
            pathname
          } = new URL(url);
          if (!hostname) {
            return null;
          }
          const proto = /(?:git\+)http:$/.test(protocol) ? "http:" : "https:";
          const path = pathname.replace(/\.git$/, "");
          return `${proto}//${hostname}${path}`;
        } catch {
          return null;
        }
      }
      var GitHost = class _GitHost {
        constructor(type, user, auth, project, committish, defaultRepresentation, opts = {}) {
          Object.assign(this, _GitHost.#gitHosts[type], {
            type,
            user,
            auth,
            project,
            committish,
            default: defaultRepresentation,
            opts
          });
        }
        static #gitHosts = { byShortcut: {}, byDomain: {} };
        static #protocols = {
          "git+ssh:": { name: "sshurl" },
          "ssh:": { name: "sshurl" },
          "git+https:": { name: "https", auth: true },
          "git:": { auth: true },
          "http:": { auth: true },
          "https:": { auth: true },
          "git+http:": { auth: true }
        };
        static addHost(name, host) {
          _GitHost.#gitHosts[name] = host;
          _GitHost.#gitHosts.byDomain[host.domain] = name;
          _GitHost.#gitHosts.byShortcut[`${name}:`] = name;
          _GitHost.#protocols[`${name}:`] = { name };
        }
        static fromUrl(giturl, opts) {
          if (typeof giturl !== "string") {
            return;
          }
          const key = giturl + JSON.stringify(opts || {});
          if (!cache.has(key)) {
            const hostArgs = fromUrl(giturl, opts, {
              gitHosts: _GitHost.#gitHosts,
              protocols: _GitHost.#protocols
            });
            cache.set(key, hostArgs ? new _GitHost(...hostArgs) : void 0);
          }
          return cache.get(key);
        }
        static fromManifest(manifest, opts = {}) {
          if (!manifest || typeof manifest !== "object") {
            return;
          }
          const r = manifest.repository;
          const rurl = r && (typeof r === "string" ? r : typeof r === "object" && typeof r.url === "string" ? r.url : null);
          if (!rurl) {
            throw new Error("no repository");
          }
          const info = rurl && _GitHost.fromUrl(rurl.replace(/^git\+/, ""), opts) || null;
          if (info) {
            return info;
          }
          const unk = unknownHostedUrl(rurl);
          return _GitHost.fromUrl(unk, opts) || unk;
        }
        static parseUrl(url) {
          return parseUrl(url);
        }
        #fill(template, opts) {
          if (typeof template !== "function") {
            return null;
          }
          const options = { ...this, ...this.opts, ...opts };
          if (!options.path) {
            options.path = "";
          }
          if (options.path.startsWith("/")) {
            options.path = options.path.slice(1);
          }
          if (options.noCommittish) {
            options.committish = null;
          }
          const result = template(options);
          return options.noGitPlus && result.startsWith("git+") ? result.slice(4) : result;
        }
        hash() {
          return this.committish ? `#${this.committish}` : "";
        }
        ssh(opts) {
          return this.#fill(this.sshtemplate, opts);
        }
        sshurl(opts) {
          return this.#fill(this.sshurltemplate, opts);
        }
        browse(path, ...args) {
          if (typeof path !== "string") {
            return this.#fill(this.browsetemplate, path);
          }
          if (typeof args[0] !== "string") {
            return this.#fill(this.browsetreetemplate, { ...args[0], path });
          }
          return this.#fill(this.browsetreetemplate, { ...args[1], fragment: args[0], path });
        }
        // If the path is known to be a file, then browseFile should be used. For some hosts
        // the url is the same as browse, but for others like GitHub a file can use both `/tree/`
        // and `/blob/` in the path. When using a default committish of `HEAD` then the `/tree/`
        // path will redirect to a specific commit. Using the `/blob/` path avoids this and
        // does not redirect to a different commit.
        browseFile(path, ...args) {
          if (typeof args[0] !== "string") {
            return this.#fill(this.browseblobtemplate, { ...args[0], path });
          }
          return this.#fill(this.browseblobtemplate, { ...args[1], fragment: args[0], path });
        }
        docs(opts) {
          return this.#fill(this.docstemplate, opts);
        }
        bugs(opts) {
          return this.#fill(this.bugstemplate, opts);
        }
        https(opts) {
          return this.#fill(this.httpstemplate, opts);
        }
        git(opts) {
          return this.#fill(this.gittemplate, opts);
        }
        shortcut(opts) {
          return this.#fill(this.shortcuttemplate, opts);
        }
        path(opts) {
          return this.#fill(this.pathtemplate, opts);
        }
        tarball(opts) {
          return this.#fill(this.tarballtemplate, { ...opts, noCommittish: false });
        }
        file(path, opts) {
          return this.#fill(this.filetemplate, { ...opts, path });
        }
        edit(path, opts) {
          return this.#fill(this.edittemplate, { ...opts, path });
        }
        getDefaultRepresentation() {
          return this.default;
        }
        toString(opts) {
          if (this.default && typeof this[this.default] === "function") {
            return this[this.default](opts);
          }
          return this.sshurl(opts);
        }
      };
      for (const [name, host] of Object.entries(hosts)) {
        GitHost.addHost(name, host);
      }
      module.exports = GitHost;
    }
  });

  // scripts/native/market-index/entry.ts
  var entry_exports = {};
  __export(entry_exports, {
    observe: () => observe,
    openSearch: () => openSearch
  });

  // .goose/out/rc022-prep-20261114-01/source/packages/util/plugin-market-index/src/index.ts
  var import_semver = __toESM(require_semver2(), 1);
  var MarketIndexError = class extends Error {
    /**
     * @param path - JSON path of the offending value.
     * @param reason - the violated rule.
     */
    constructor(path, reason) {
      super(`${path} ${reason}`);
      this.path = path;
      this.reason = reason;
      this.name = "MarketIndexError";
    }
    path;
    reason;
  };
  var LANGUAGE_ID = /^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/u;
  var PACKAGE_NAME = /^(?:@[a-z0-9][a-z0-9._~-]*\/)?[a-z0-9][a-z0-9._~-]*$/u;
  var PACKAGE_NAME_MAX_LENGTH = 214;
  var NUMERIC = "(?:0|[1-9]\\d*)";
  var PRERELEASE_PART = `(?:${NUMERIC}|\\d*[a-zA-Z-][0-9a-zA-Z-]*)`;
  var SEMVER = new RegExp(
    `^${NUMERIC}\\.${NUMERIC}\\.${NUMERIC}(?:-${PRERELEASE_PART}(?:\\.${PRERELEASE_PART})*)?(?:\\+[0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*)?$`,
    "u"
  );
  var COMMIT = /^[0-9a-f]{40}$/u;
  var PATH_SEGMENT = /^[A-Za-z0-9._@+-]+$/u;
  var DATA_ICON = /^data:(?:image\/svg\+xml|image\/png|image\/jpeg|image\/webp);base64,([A-Za-z0-9+/]*={0,2})$/u;
  var BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;
  var MAX_INLINE_ICON_BYTES = 32 * 1024;
  var MAX_PUBLISH_TIMESTAMP = 1e11;
  function fail(path, reason) {
    throw new MarketIndexError(path, reason);
  }
  function objectAt(value, path) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) fail(path, "must be an object");
    return value;
  }
  function stringAt(value, path) {
    if (typeof value !== "string" || value.trim() === "") fail(path, "must be a string with a non-whitespace character");
    return value;
  }
  function optional(object, key, path, read) {
    return Object.hasOwn(object, key) ? read(object[key], `${path}.${key}`) : void 0;
  }
  function localizedText(value, path) {
    if (typeof value === "string") return stringAt(value, path);
    const object = objectAt(value, path);
    const text = {};
    for (const [language, member] of Object.entries(object)) {
      if (!LANGUAGE_ID.test(language)) fail(`${path}.${language}`, "must be keyed by a lowercase language id");
      own(text, language, stringAt(member, `${path}.${language}`));
    }
    if (!Object.hasOwn(text, "en")) fail(path, "must contain en");
    return text;
  }
  function own(record, key, value) {
    Object.defineProperty(record, key, { value, enumerable: true, writable: true, configurable: true });
  }
  function declarations(value, path, read) {
    const result = {};
    for (const [id, member] of Object.entries(objectAt(value, path))) {
      if (id === "") fail(path, "must not declare an empty id");
      own(result, id, read(objectAt(member, `${path}.${id}`), `${path}.${id}`));
    }
    return result;
  }
  function declaration(object, path) {
    return { title: localizedText(object.title, `${path}.title`) };
  }
  function sortKeyDeclaration(object, path) {
    if (object.order !== "asc" && object.order !== "desc") fail(`${path}.order`, 'must be "asc" or "desc"');
    return { title: localizedText(object.title, `${path}.title`), order: object.order };
  }
  function indexMetadata(value, path) {
    const object = value === void 0 ? {} : objectAt(value, path);
    return {
      categories: optional(object, "categories", path, (member, at) => declarations(member, at, declaration)) ?? {},
      labels: optional(object, "labels", path, (member, at) => declarations(member, at, declaration)) ?? {},
      sortKeys: optional(object, "sortKeys", path, (member, at) => declarations(member, at, sortKeyDeclaration)) ?? {}
    };
  }
  function declaredId(value, path, declared) {
    const id = stringAt(value, path);
    if (!Object.hasOwn(declared, id)) fail(path, `references undeclared id ${JSON.stringify(id)}`);
    return id;
  }
  function pluginMetadata(value, path, index) {
    const object = value === void 0 || value === null ? {} : objectAt(value, path);
    const field = (key, read) => object[key] === null ? void 0 : optional(object, key, path, read);
    const category = field("category", (member, at) => declaredId(member, at, index.categories));
    const keywords = field("keywords", (member, at) => {
      if (!Array.isArray(member)) fail(at, "must be an array");
      return member.map((keyword, position) => {
        if (typeof keyword !== "string") fail(`${at}[${String(position)}]`, "must be a string");
        return keyword;
      });
    }) ?? [];
    const labels = field("labels", (member, at) => {
      if (!Array.isArray(member)) fail(at, "must be an array");
      const ids = member.map((label, position) => declaredId(label, `${at}[${String(position)}]`, index.labels));
      if (new Set(ids).size !== ids.length) fail(at, "must not repeat a label");
      return ids;
    }) ?? [];
    const sortKeys = field("sortKeys", (member, at) => {
      const values = {};
      for (const [id, sortValue] of Object.entries(objectAt(member, at))) {
        declaredId(id, `${at}.${id}`, index.sortKeys);
        if (sortValue === null) continue;
        if (typeof sortValue !== "number" || !Number.isFinite(sortValue)) fail(`${at}.${id}`, "must be a finite number");
        own(values, id, sortValue);
      }
      return values;
    }) ?? {};
    return { ...category === void 0 ? {} : { category }, keywords, labels, sortKeys };
  }
  function httpUrl(value, path, protocols) {
    const text = stringAt(value, path);
    let url;
    try {
      url = new URL(text);
    } catch {
      fail(path, "must be an absolute URL");
    }
    if (!protocols.includes(url.protocol)) fail(path, `must use ${protocols.join(" or ")}`);
    if (url.username !== "" || url.password !== "") fail(path, "must not contain credentials");
    if (url.href.includes("?") || url.href.includes("#")) fail(path, "must not contain a query or fragment");
    return url;
  }
  function homepageUrl(value, path) {
    const text = stringAt(value, path);
    if (!URL.canParse(text)) fail(path, "must be an absolute URL");
    const url = new URL(text);
    if (url.protocol !== "https:" && url.protocol !== "http:") fail(path, "must use https: or http:");
    return url.href;
  }
  function gitUrl(value, path) {
    const url = httpUrl(value, path, ["https:"]);
    if (url.href !== value) fail(path, "must be a canonical URL");
    if (!/^(?:\/[^/]+){2,}$/u.test(url.pathname)) fail(path, "must name a repository with at least two path segments");
    if (/\.(?:tgz|tar\.gz)$/iu.test(url.pathname)) fail(path, "must name a repository, not a tarball");
    return url.href;
  }
  function packagePath(value, path) {
    const text = stringAt(value, path);
    const segments = text.split("/");
    if (segments.some((segment) => segment === "." || segment === ".." || !PATH_SEGMENT.test(segment))) {
      fail(path, "must be a relative directory of letters, digits, and ._@+- segments without . or ..");
    }
    return text;
  }
  function repository(value, path) {
    const object = objectAt(value, path);
    const url = httpUrl(object.url, `${path}.url`, ["https:", "http:"]).href;
    const directory = optional(object, "directory", path, packagePath);
    return { url, ...directory === void 0 ? {} : { directory } };
  }
  function source(value, path) {
    const object = objectAt(value, path);
    switch (object.type) {
      case "npm": {
        const registry = optional(object, "registry", path, (member, at) => httpUrl(member, at, ["https:", "http:"]).href);
        return { type: "npm", ...registry === void 0 ? {} : { registry } };
      }
      case "git": {
        const commit = stringAt(object.commit, `${path}.commit`);
        if (!COMMIT.test(commit)) fail(`${path}.commit`, "must be a lowercase 40-hex-digit commit SHA");
        const packageDir = optional(object, "path", path, packagePath);
        return { type: "git", url: gitUrl(object.url, `${path}.url`), commit, ...packageDir === void 0 ? {} : { path: packageDir } };
      }
      default:
        return fail(`${path}.type`, 'must be "npm" or "git"');
    }
  }
  function engines(value, path) {
    const object = objectAt(value, path);
    const dsh = optional(object, "dsh", path, (member, at) => {
      const range = stringAt(member, at);
      if (range.startsWith("workspace:")) fail(at, "must not be a workspace: range");
      if (import_semver.default.validRange(range) === null) fail(at, "must be a SemVer range");
      return range;
    });
    return dsh === void 0 ? {} : { dsh };
  }
  function icon(value, path, indexUrl) {
    const text = stringAt(value, path);
    if (text.startsWith("data:")) {
      const match = DATA_ICON.exec(text);
      const payload = match?.[1];
      if (payload === void 0 || payload === "" || !BASE64.test(payload)) fail(path, "must be a base64 SVG, PNG, JPEG, or WebP data URL");
      const bytes = payload.length / 4 * 3 - (payload.endsWith("==") ? 2 : payload.endsWith("=") ? 1 : 0);
      if (bytes > MAX_INLINE_ICON_BYTES) fail(path, `must not exceed ${String(MAX_INLINE_ICON_BYTES / 1024)} KiB of decoded bytes`);
      return text;
    }
    let resolved;
    try {
      resolved = new URL(text, indexUrl);
    } catch {
      fail(path, "must be a URL reference");
    }
    if (resolved.protocol !== "https:" && (resolved.origin === "null" || resolved.origin !== indexUrl.origin)) fail(path, "must resolve to https or the index origin");
    return resolved.href;
  }
  function marketVersion(value, path) {
    const object = objectAt(value, path);
    const version = stringAt(object.version, `${path}.version`);
    if (!SEMVER.test(version)) fail(`${path}.version`, "must be an exact SemVer version");
    const publishTimestamp = object.publishTimestamp;
    if (typeof publishTimestamp !== "number" || !Number.isInteger(publishTimestamp) || publishTimestamp < 0 || publishTimestamp >= MAX_PUBLISH_TIMESTAMP) {
      fail(`${path}.publishTimestamp`, "must be an integer number of Unix seconds in [0, 10^11)");
    }
    return {
      version,
      publishTimestamp,
      source: source(object.source, `${path}.source`),
      engines: optional(object, "engines", path, engines) ?? {}
    };
  }
  function versions(value, path) {
    if (!Array.isArray(value) || value.length === 0) fail(path, "must be a non-empty array");
    const seen = /* @__PURE__ */ new Set();
    const parsed = value.map((member, position) => {
      const at = `${path}[${String(position)}]`;
      const entry = marketVersion(member, at);
      if (seen.has(entry.version)) fail(`${at}.version`, `duplicates ${entry.version}`);
      seen.add(entry.version);
      return entry;
    });
    return parsed.sort((left, right) => import_semver.default.rcompare(left.version, right.version));
  }
  function plugin(value, path, index, indexUrl) {
    const object = objectAt(value, path);
    const name = stringAt(object.name, `${path}.name`);
    if (name.length > PACKAGE_NAME_MAX_LENGTH || !PACKAGE_NAME.test(name)) fail(`${path}.name`, "must be a valid npm package name");
    const title = optional(object, "title", path, localizedText);
    const description = optional(object, "description", path, localizedText);
    const iconUrl = optional(object, "icon", path, (member, at) => icon(member, at, indexUrl));
    const author = optional(object, "author", path, stringAt);
    const homepage = optional(object, "homepage", path, homepageUrl);
    const repo = optional(object, "repository", path, repository);
    return {
      name,
      ...title === void 0 ? {} : { title },
      ...description === void 0 ? {} : { description },
      ...iconUrl === void 0 ? {} : { icon: iconUrl },
      ...author === void 0 ? {} : { author },
      ...homepage === void 0 ? {} : { homepage },
      ...repo === void 0 ? {} : { repository: repo },
      metadata: pluginMetadata(object.metadata, `${path}.metadata`, index),
      versions: versions(object.versions, `${path}.versions`)
    };
  }
  function parseMarketIndex(value, indexUrl) {
    if (!URL.canParse(indexUrl)) fail("$", `index URL ${JSON.stringify(indexUrl)} must be an absolute URL`);
    const base = new URL(indexUrl);
    const object = objectAt(value, "$");
    if (object.format !== 1) fail("$.format", "must be 1");
    const metadata = indexMetadata(object.metadata, "$.metadata");
    if (!Array.isArray(object.plugins)) fail("$.plugins", "must be an array");
    const names = /* @__PURE__ */ new Set();
    const plugins = object.plugins.map((entry, position) => {
      const parsed = plugin(entry, `$.plugins[${String(position)}]`, metadata, base);
      if (names.has(parsed.name)) fail(`$.plugins[${String(position)}].name`, `duplicates ${parsed.name}`);
      names.add(parsed.name);
      return parsed;
    });
    const title = localizedText(object.title, "$.title");
    const description = optional(object, "description", "$", localizedText);
    return { format: 1, title, ...description === void 0 ? {} : { description }, metadata, plugins };
  }
  function marketInstallTarget(name, version) {
    const { source: from } = version;
    if (from.type === "npm") return { spec: `${name}@${version.version}`, ...from.registry === void 0 ? {} : { registry: from.registry } };
    const repository2 = from.url.endsWith(".git") ? from.url : `${from.url}.git`;
    return { spec: `git+${repository2}#${from.commit}${from.path === void 0 ? "" : `&path:/${from.path}`}` };
  }

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/minisearch@7.2.0/node_modules/minisearch/dist/es/index.js
  var ENTRIES = "ENTRIES";
  var KEYS = "KEYS";
  var VALUES = "VALUES";
  var LEAF = "";
  var TreeIterator = class {
    constructor(set, type) {
      const node = set._tree;
      const keys = Array.from(node.keys());
      this.set = set;
      this._type = type;
      this._path = keys.length > 0 ? [{ node, keys }] : [];
    }
    next() {
      const value = this.dive();
      this.backtrack();
      return value;
    }
    dive() {
      if (this._path.length === 0) {
        return { done: true, value: void 0 };
      }
      const { node, keys } = last$1(this._path);
      if (last$1(keys) === LEAF) {
        return { done: false, value: this.result() };
      }
      const child = node.get(last$1(keys));
      this._path.push({ node: child, keys: Array.from(child.keys()) });
      return this.dive();
    }
    backtrack() {
      if (this._path.length === 0) {
        return;
      }
      const keys = last$1(this._path).keys;
      keys.pop();
      if (keys.length > 0) {
        return;
      }
      this._path.pop();
      this.backtrack();
    }
    key() {
      return this.set._prefix + this._path.map(({ keys }) => last$1(keys)).filter((key) => key !== LEAF).join("");
    }
    value() {
      return last$1(this._path).node.get(LEAF);
    }
    result() {
      switch (this._type) {
        case VALUES:
          return this.value();
        case KEYS:
          return this.key();
        default:
          return [this.key(), this.value()];
      }
    }
    [Symbol.iterator]() {
      return this;
    }
  };
  var last$1 = (array) => {
    return array[array.length - 1];
  };
  var fuzzySearch = (node, query, maxDistance) => {
    const results = /* @__PURE__ */ new Map();
    if (query === void 0)
      return results;
    const n = query.length + 1;
    const m = n + maxDistance;
    const matrix = new Uint8Array(m * n).fill(maxDistance + 1);
    for (let j = 0; j < n; ++j)
      matrix[j] = j;
    for (let i = 1; i < m; ++i)
      matrix[i * n] = i;
    recurse(node, query, maxDistance, results, matrix, 1, n, "");
    return results;
  };
  var recurse = (node, query, maxDistance, results, matrix, m, n, prefix) => {
    const offset = m * n;
    key: for (const key of node.keys()) {
      if (key === LEAF) {
        const distance = matrix[offset - 1];
        if (distance <= maxDistance) {
          results.set(prefix, [node.get(key), distance]);
        }
      } else {
        let i = m;
        for (let pos = 0; pos < key.length; ++pos, ++i) {
          const char = key[pos];
          const thisRowOffset = n * i;
          const prevRowOffset = thisRowOffset - n;
          let minDistance = matrix[thisRowOffset];
          const jmin = Math.max(0, i - maxDistance - 1);
          const jmax = Math.min(n - 1, i + maxDistance);
          for (let j = jmin; j < jmax; ++j) {
            const different = char !== query[j];
            const rpl = matrix[prevRowOffset + j] + +different;
            const del = matrix[prevRowOffset + j + 1] + 1;
            const ins = matrix[thisRowOffset + j] + 1;
            const dist = matrix[thisRowOffset + j + 1] = Math.min(rpl, del, ins);
            if (dist < minDistance)
              minDistance = dist;
          }
          if (minDistance > maxDistance) {
            continue key;
          }
        }
        recurse(node.get(key), query, maxDistance, results, matrix, i, n, prefix + key);
      }
    }
  };
  var SearchableMap = class _SearchableMap {
    /**
     * The constructor is normally called without arguments, creating an empty
     * map. In order to create a {@link SearchableMap} from an iterable or from an
     * object, check {@link SearchableMap.from} and {@link
     * SearchableMap.fromObject}.
     *
     * The constructor arguments are for internal use, when creating derived
     * mutable views of a map at a prefix.
     */
    constructor(tree = /* @__PURE__ */ new Map(), prefix = "") {
      this._size = void 0;
      this._tree = tree;
      this._prefix = prefix;
    }
    /**
     * Creates and returns a mutable view of this {@link SearchableMap},
     * containing only entries that share the given prefix.
     *
     * ### Usage:
     *
     * ```javascript
     * let map = new SearchableMap()
     * map.set("unicorn", 1)
     * map.set("universe", 2)
     * map.set("university", 3)
     * map.set("unique", 4)
     * map.set("hello", 5)
     *
     * let uni = map.atPrefix("uni")
     * uni.get("unique") // => 4
     * uni.get("unicorn") // => 1
     * uni.get("hello") // => undefined
     *
     * let univer = map.atPrefix("univer")
     * univer.get("unique") // => undefined
     * univer.get("universe") // => 2
     * univer.get("university") // => 3
     * ```
     *
     * @param prefix  The prefix
     * @return A {@link SearchableMap} representing a mutable view of the original
     * Map at the given prefix
     */
    atPrefix(prefix) {
      if (!prefix.startsWith(this._prefix)) {
        throw new Error("Mismatched prefix");
      }
      const [node, path] = trackDown(this._tree, prefix.slice(this._prefix.length));
      if (node === void 0) {
        const [parentNode, key] = last(path);
        for (const k of parentNode.keys()) {
          if (k !== LEAF && k.startsWith(key)) {
            const node2 = /* @__PURE__ */ new Map();
            node2.set(k.slice(key.length), parentNode.get(k));
            return new _SearchableMap(node2, prefix);
          }
        }
      }
      return new _SearchableMap(node, prefix);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/clear
     */
    clear() {
      this._size = void 0;
      this._tree.clear();
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/delete
     * @param key  Key to delete
     */
    delete(key) {
      this._size = void 0;
      return remove(this._tree, key);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/entries
     * @return An iterator iterating through `[key, value]` entries.
     */
    entries() {
      return new TreeIterator(this, ENTRIES);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/forEach
     * @param fn  Iteration function
     */
    forEach(fn) {
      for (const [key, value] of this) {
        fn(key, value, this);
      }
    }
    /**
     * Returns a Map of all the entries that have a key within the given edit
     * distance from the search key. The keys of the returned Map are the matching
     * keys, while the values are two-element arrays where the first element is
     * the value associated to the key, and the second is the edit distance of the
     * key to the search key.
     *
     * ### Usage:
     *
     * ```javascript
     * let map = new SearchableMap()
     * map.set('hello', 'world')
     * map.set('hell', 'yeah')
     * map.set('ciao', 'mondo')
     *
     * // Get all entries that match the key 'hallo' with a maximum edit distance of 2
     * map.fuzzyGet('hallo', 2)
     * // => Map(2) { 'hello' => ['world', 1], 'hell' => ['yeah', 2] }
     *
     * // In the example, the "hello" key has value "world" and edit distance of 1
     * // (change "e" to "a"), the key "hell" has value "yeah" and edit distance of 2
     * // (change "e" to "a", delete "o")
     * ```
     *
     * @param key  The search key
     * @param maxEditDistance  The maximum edit distance (Levenshtein)
     * @return A Map of the matching keys to their value and edit distance
     */
    fuzzyGet(key, maxEditDistance) {
      return fuzzySearch(this._tree, key, maxEditDistance);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/get
     * @param key  Key to get
     * @return Value associated to the key, or `undefined` if the key is not
     * found.
     */
    get(key) {
      const node = lookup(this._tree, key);
      return node !== void 0 ? node.get(LEAF) : void 0;
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/has
     * @param key  Key
     * @return True if the key is in the map, false otherwise
     */
    has(key) {
      const node = lookup(this._tree, key);
      return node !== void 0 && node.has(LEAF);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/keys
     * @return An `Iterable` iterating through keys
     */
    keys() {
      return new TreeIterator(this, KEYS);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/set
     * @param key  Key to set
     * @param value  Value to associate to the key
     * @return The {@link SearchableMap} itself, to allow chaining
     */
    set(key, value) {
      if (typeof key !== "string") {
        throw new Error("key must be a string");
      }
      this._size = void 0;
      const node = createPath(this._tree, key);
      node.set(LEAF, value);
      return this;
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/size
     */
    get size() {
      if (this._size) {
        return this._size;
      }
      this._size = 0;
      const iter = this.entries();
      while (!iter.next().done)
        this._size += 1;
      return this._size;
    }
    /**
     * Updates the value at the given key using the provided function. The function
     * is called with the current value at the key, and its return value is used as
     * the new value to be set.
     *
     * ### Example:
     *
     * ```javascript
     * // Increment the current value by one
     * searchableMap.update('somekey', (currentValue) => currentValue == null ? 0 : currentValue + 1)
     * ```
     *
     * If the value at the given key is or will be an object, it might not require
     * re-assignment. In that case it is better to use `fetch()`, because it is
     * faster.
     *
     * @param key  The key to update
     * @param fn  The function used to compute the new value from the current one
     * @return The {@link SearchableMap} itself, to allow chaining
     */
    update(key, fn) {
      if (typeof key !== "string") {
        throw new Error("key must be a string");
      }
      this._size = void 0;
      const node = createPath(this._tree, key);
      node.set(LEAF, fn(node.get(LEAF)));
      return this;
    }
    /**
     * Fetches the value of the given key. If the value does not exist, calls the
     * given function to create a new value, which is inserted at the given key
     * and subsequently returned.
     *
     * ### Example:
     *
     * ```javascript
     * const map = searchableMap.fetch('somekey', () => new Map())
     * map.set('foo', 'bar')
     * ```
     *
     * @param key  The key to update
     * @param initial  A function that creates a new value if the key does not exist
     * @return The existing or new value at the given key
     */
    fetch(key, initial) {
      if (typeof key !== "string") {
        throw new Error("key must be a string");
      }
      this._size = void 0;
      const node = createPath(this._tree, key);
      let value = node.get(LEAF);
      if (value === void 0) {
        node.set(LEAF, value = initial());
      }
      return value;
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/values
     * @return An `Iterable` iterating through values.
     */
    values() {
      return new TreeIterator(this, VALUES);
    }
    /**
     * @see https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Map/@@iterator
     */
    [Symbol.iterator]() {
      return this.entries();
    }
    /**
     * Creates a {@link SearchableMap} from an `Iterable` of entries
     *
     * @param entries  Entries to be inserted in the {@link SearchableMap}
     * @return A new {@link SearchableMap} with the given entries
     */
    static from(entries) {
      const tree = new _SearchableMap();
      for (const [key, value] of entries) {
        tree.set(key, value);
      }
      return tree;
    }
    /**
     * Creates a {@link SearchableMap} from the iterable properties of a JavaScript object
     *
     * @param object  Object of entries for the {@link SearchableMap}
     * @return A new {@link SearchableMap} with the given entries
     */
    static fromObject(object) {
      return _SearchableMap.from(Object.entries(object));
    }
  };
  var trackDown = (tree, key, path = []) => {
    if (key.length === 0 || tree == null) {
      return [tree, path];
    }
    for (const k of tree.keys()) {
      if (k !== LEAF && key.startsWith(k)) {
        path.push([tree, k]);
        return trackDown(tree.get(k), key.slice(k.length), path);
      }
    }
    path.push([tree, key]);
    return trackDown(void 0, "", path);
  };
  var lookup = (tree, key) => {
    if (key.length === 0 || tree == null) {
      return tree;
    }
    for (const k of tree.keys()) {
      if (k !== LEAF && key.startsWith(k)) {
        return lookup(tree.get(k), key.slice(k.length));
      }
    }
  };
  var createPath = (node, key) => {
    const keyLength = key.length;
    outer: for (let pos = 0; node && pos < keyLength; ) {
      for (const k of node.keys()) {
        if (k !== LEAF && key[pos] === k[0]) {
          const len = Math.min(keyLength - pos, k.length);
          let offset = 1;
          while (offset < len && key[pos + offset] === k[offset])
            ++offset;
          const child2 = node.get(k);
          if (offset === k.length) {
            node = child2;
          } else {
            const intermediate = /* @__PURE__ */ new Map();
            intermediate.set(k.slice(offset), child2);
            node.set(key.slice(pos, pos + offset), intermediate);
            node.delete(k);
            node = intermediate;
          }
          pos += offset;
          continue outer;
        }
      }
      const child = /* @__PURE__ */ new Map();
      node.set(key.slice(pos), child);
      return child;
    }
    return node;
  };
  var remove = (tree, key) => {
    const [node, path] = trackDown(tree, key);
    if (node === void 0) {
      return;
    }
    node.delete(LEAF);
    if (node.size === 0) {
      cleanup(path);
    } else if (node.size === 1) {
      const [key2, value] = node.entries().next().value;
      merge(path, key2, value);
    }
  };
  var cleanup = (path) => {
    if (path.length === 0) {
      return;
    }
    const [node, key] = last(path);
    node.delete(key);
    if (node.size === 0) {
      cleanup(path.slice(0, -1));
    } else if (node.size === 1) {
      const [key2, value] = node.entries().next().value;
      if (key2 !== LEAF) {
        merge(path.slice(0, -1), key2, value);
      }
    }
  };
  var merge = (path, key, value) => {
    if (path.length === 0) {
      return;
    }
    const [node, nodeKey] = last(path);
    node.set(nodeKey + key, value);
    node.delete(nodeKey);
  };
  var last = (array) => {
    return array[array.length - 1];
  };
  var OR = "or";
  var AND = "and";
  var AND_NOT = "and_not";
  var MiniSearch = class _MiniSearch {
    /**
     * @param options  Configuration options
     *
     * ### Examples:
     *
     * ```javascript
     * // Create a search engine that indexes the 'title' and 'text' fields of your
     * // documents:
     * const miniSearch = new MiniSearch({ fields: ['title', 'text'] })
     * ```
     *
     * ### ID Field:
     *
     * ```javascript
     * // Your documents are assumed to include a unique 'id' field, but if you want
     * // to use a different field for document identification, you can set the
     * // 'idField' option:
     * const miniSearch = new MiniSearch({ idField: 'key', fields: ['title', 'text'] })
     * ```
     *
     * ### Options and defaults:
     *
     * ```javascript
     * // The full set of options (here with their default value) is:
     * const miniSearch = new MiniSearch({
     *   // idField: field that uniquely identifies a document
     *   idField: 'id',
     *
     *   // extractField: function used to get the value of a field in a document.
     *   // By default, it assumes the document is a flat object with field names as
     *   // property keys and field values as string property values, but custom logic
     *   // can be implemented by setting this option to a custom extractor function.
     *   extractField: (document, fieldName) => document[fieldName],
     *
     *   // tokenize: function used to split fields into individual terms. By
     *   // default, it is also used to tokenize search queries, unless a specific
     *   // `tokenize` search option is supplied. When tokenizing an indexed field,
     *   // the field name is passed as the second argument.
     *   tokenize: (string, _fieldName) => string.split(SPACE_OR_PUNCTUATION),
     *
     *   // processTerm: function used to process each tokenized term before
     *   // indexing. It can be used for stemming and normalization. Return a falsy
     *   // value in order to discard a term. By default, it is also used to process
     *   // search queries, unless a specific `processTerm` option is supplied as a
     *   // search option. When processing a term from a indexed field, the field
     *   // name is passed as the second argument.
     *   processTerm: (term, _fieldName) => term.toLowerCase(),
     *
     *   // searchOptions: default search options, see the `search` method for
     *   // details
     *   searchOptions: undefined,
     *
     *   // fields: document fields to be indexed. Mandatory, but not set by default
     *   fields: undefined
     *
     *   // storeFields: document fields to be stored and returned as part of the
     *   // search results.
     *   storeFields: []
     * })
     * ```
     */
    constructor(options) {
      if ((options === null || options === void 0 ? void 0 : options.fields) == null) {
        throw new Error('MiniSearch: option "fields" must be provided');
      }
      const autoVacuum = options.autoVacuum == null || options.autoVacuum === true ? defaultAutoVacuumOptions : options.autoVacuum;
      this._options = {
        ...defaultOptions,
        ...options,
        autoVacuum,
        searchOptions: { ...defaultSearchOptions, ...options.searchOptions || {} },
        autoSuggestOptions: { ...defaultAutoSuggestOptions, ...options.autoSuggestOptions || {} }
      };
      this._index = new SearchableMap();
      this._documentCount = 0;
      this._documentIds = /* @__PURE__ */ new Map();
      this._idToShortId = /* @__PURE__ */ new Map();
      this._fieldIds = {};
      this._fieldLength = /* @__PURE__ */ new Map();
      this._avgFieldLength = [];
      this._nextId = 0;
      this._storedFields = /* @__PURE__ */ new Map();
      this._dirtCount = 0;
      this._currentVacuum = null;
      this._enqueuedVacuum = null;
      this._enqueuedVacuumConditions = defaultVacuumConditions;
      this.addFields(this._options.fields);
    }
    /**
     * Adds a document to the index
     *
     * @param document  The document to be indexed
     */
    add(document) {
      const { extractField, stringifyField, tokenize, processTerm, fields, idField } = this._options;
      const id = extractField(document, idField);
      if (id == null) {
        throw new Error(`MiniSearch: document does not have ID field "${idField}"`);
      }
      if (this._idToShortId.has(id)) {
        throw new Error(`MiniSearch: duplicate ID ${id}`);
      }
      const shortDocumentId = this.addDocumentId(id);
      this.saveStoredFields(shortDocumentId, document);
      for (const field of fields) {
        const fieldValue = extractField(document, field);
        if (fieldValue == null)
          continue;
        const tokens = tokenize(stringifyField(fieldValue, field), field);
        const fieldId = this._fieldIds[field];
        const uniqueTerms = new Set(tokens).size;
        this.addFieldLength(shortDocumentId, fieldId, this._documentCount - 1, uniqueTerms);
        for (const term of tokens) {
          const processedTerm = processTerm(term, field);
          if (Array.isArray(processedTerm)) {
            for (const t of processedTerm) {
              this.addTerm(fieldId, shortDocumentId, t);
            }
          } else if (processedTerm) {
            this.addTerm(fieldId, shortDocumentId, processedTerm);
          }
        }
      }
    }
    /**
     * Adds all the given documents to the index
     *
     * @param documents  An array of documents to be indexed
     */
    addAll(documents) {
      for (const document of documents)
        this.add(document);
    }
    /**
     * Adds all the given documents to the index asynchronously.
     *
     * Returns a promise that resolves (to `undefined`) when the indexing is done.
     * This method is useful when index many documents, to avoid blocking the main
     * thread. The indexing is performed asynchronously and in chunks.
     *
     * @param documents  An array of documents to be indexed
     * @param options  Configuration options
     * @return A promise resolving to `undefined` when the indexing is done
     */
    addAllAsync(documents, options = {}) {
      const { chunkSize = 10 } = options;
      const acc = { chunk: [], promise: Promise.resolve() };
      const { chunk, promise } = documents.reduce(({ chunk: chunk2, promise: promise2 }, document, i) => {
        chunk2.push(document);
        if ((i + 1) % chunkSize === 0) {
          return {
            chunk: [],
            promise: promise2.then(() => new Promise((resolve) => setTimeout(resolve, 0))).then(() => this.addAll(chunk2))
          };
        } else {
          return { chunk: chunk2, promise: promise2 };
        }
      }, acc);
      return promise.then(() => this.addAll(chunk));
    }
    /**
     * Removes the given document from the index.
     *
     * The document to remove must NOT have changed between indexing and removal,
     * otherwise the index will be corrupted.
     *
     * This method requires passing the full document to be removed (not just the
     * ID), and immediately removes the document from the inverted index, allowing
     * memory to be released. A convenient alternative is {@link
     * MiniSearch#discard}, which needs only the document ID, and has the same
     * visible effect, but delays cleaning up the index until the next vacuuming.
     *
     * @param document  The document to be removed
     */
    remove(document) {
      const { tokenize, processTerm, extractField, stringifyField, fields, idField } = this._options;
      const id = extractField(document, idField);
      if (id == null) {
        throw new Error(`MiniSearch: document does not have ID field "${idField}"`);
      }
      const shortId = this._idToShortId.get(id);
      if (shortId == null) {
        throw new Error(`MiniSearch: cannot remove document with ID ${id}: it is not in the index`);
      }
      for (const field of fields) {
        const fieldValue = extractField(document, field);
        if (fieldValue == null)
          continue;
        const tokens = tokenize(stringifyField(fieldValue, field), field);
        const fieldId = this._fieldIds[field];
        const uniqueTerms = new Set(tokens).size;
        this.removeFieldLength(shortId, fieldId, this._documentCount, uniqueTerms);
        for (const term of tokens) {
          const processedTerm = processTerm(term, field);
          if (Array.isArray(processedTerm)) {
            for (const t of processedTerm) {
              this.removeTerm(fieldId, shortId, t);
            }
          } else if (processedTerm) {
            this.removeTerm(fieldId, shortId, processedTerm);
          }
        }
      }
      this._storedFields.delete(shortId);
      this._documentIds.delete(shortId);
      this._idToShortId.delete(id);
      this._fieldLength.delete(shortId);
      this._documentCount -= 1;
    }
    /**
     * Removes all the given documents from the index. If called with no arguments,
     * it removes _all_ documents from the index.
     *
     * @param documents  The documents to be removed. If this argument is omitted,
     * all documents are removed. Note that, for removing all documents, it is
     * more efficient to call this method with no arguments than to pass all
     * documents.
     */
    removeAll(documents) {
      if (documents) {
        for (const document of documents)
          this.remove(document);
      } else if (arguments.length > 0) {
        throw new Error("Expected documents to be present. Omit the argument to remove all documents.");
      } else {
        this._index = new SearchableMap();
        this._documentCount = 0;
        this._documentIds = /* @__PURE__ */ new Map();
        this._idToShortId = /* @__PURE__ */ new Map();
        this._fieldLength = /* @__PURE__ */ new Map();
        this._avgFieldLength = [];
        this._storedFields = /* @__PURE__ */ new Map();
        this._nextId = 0;
      }
    }
    /**
     * Discards the document with the given ID, so it won't appear in search results
     *
     * It has the same visible effect of {@link MiniSearch.remove} (both cause the
     * document to stop appearing in searches), but a different effect on the
     * internal data structures:
     *
     *   - {@link MiniSearch#remove} requires passing the full document to be
     *   removed as argument, and removes it from the inverted index immediately.
     *
     *   - {@link MiniSearch#discard} instead only needs the document ID, and
     *   works by marking the current version of the document as discarded, so it
     *   is immediately ignored by searches. This is faster and more convenient
     *   than {@link MiniSearch#remove}, but the index is not immediately
     *   modified. To take care of that, vacuuming is performed after a certain
     *   number of documents are discarded, cleaning up the index and allowing
     *   memory to be released.
     *
     * After discarding a document, it is possible to re-add a new version, and
     * only the new version will appear in searches. In other words, discarding
     * and re-adding a document works exactly like removing and re-adding it. The
     * {@link MiniSearch.replace} method can also be used to replace a document
     * with a new version.
     *
     * #### Details about vacuuming
     *
     * Repetite calls to this method would leave obsolete document references in
     * the index, invisible to searches. Two mechanisms take care of cleaning up:
     * clean up during search, and vacuuming.
     *
     *   - Upon search, whenever a discarded ID is found (and ignored for the
     *   results), references to the discarded document are removed from the
     *   inverted index entries for the search terms. This ensures that subsequent
     *   searches for the same terms do not need to skip these obsolete references
     *   again.
     *
     *   - In addition, vacuuming is performed automatically by default (see the
     *   `autoVacuum` field in {@link Options}) after a certain number of
     *   documents are discarded. Vacuuming traverses all terms in the index,
     *   cleaning up all references to discarded documents. Vacuuming can also be
     *   triggered manually by calling {@link MiniSearch#vacuum}.
     *
     * @param id  The ID of the document to be discarded
     */
    discard(id) {
      const shortId = this._idToShortId.get(id);
      if (shortId == null) {
        throw new Error(`MiniSearch: cannot discard document with ID ${id}: it is not in the index`);
      }
      this._idToShortId.delete(id);
      this._documentIds.delete(shortId);
      this._storedFields.delete(shortId);
      (this._fieldLength.get(shortId) || []).forEach((fieldLength, fieldId) => {
        this.removeFieldLength(shortId, fieldId, this._documentCount, fieldLength);
      });
      this._fieldLength.delete(shortId);
      this._documentCount -= 1;
      this._dirtCount += 1;
      this.maybeAutoVacuum();
    }
    maybeAutoVacuum() {
      if (this._options.autoVacuum === false) {
        return;
      }
      const { minDirtFactor, minDirtCount, batchSize, batchWait } = this._options.autoVacuum;
      this.conditionalVacuum({ batchSize, batchWait }, { minDirtCount, minDirtFactor });
    }
    /**
     * Discards the documents with the given IDs, so they won't appear in search
     * results
     *
     * It is equivalent to calling {@link MiniSearch#discard} for all the given
     * IDs, but with the optimization of triggering at most one automatic
     * vacuuming at the end.
     *
     * Note: to remove all documents from the index, it is faster and more
     * convenient to call {@link MiniSearch.removeAll} with no argument, instead
     * of passing all IDs to this method.
     */
    discardAll(ids) {
      const autoVacuum = this._options.autoVacuum;
      try {
        this._options.autoVacuum = false;
        for (const id of ids) {
          this.discard(id);
        }
      } finally {
        this._options.autoVacuum = autoVacuum;
      }
      this.maybeAutoVacuum();
    }
    /**
     * It replaces an existing document with the given updated version
     *
     * It works by discarding the current version and adding the updated one, so
     * it is functionally equivalent to calling {@link MiniSearch#discard}
     * followed by {@link MiniSearch#add}. The ID of the updated document should
     * be the same as the original one.
     *
     * Since it uses {@link MiniSearch#discard} internally, this method relies on
     * vacuuming to clean up obsolete document references from the index, allowing
     * memory to be released (see {@link MiniSearch#discard}).
     *
     * @param updatedDocument  The updated document to replace the old version
     * with
     */
    replace(updatedDocument) {
      const { idField, extractField } = this._options;
      const id = extractField(updatedDocument, idField);
      this.discard(id);
      this.add(updatedDocument);
    }
    /**
     * Triggers a manual vacuuming, cleaning up references to discarded documents
     * from the inverted index
     *
     * Vacuuming is only useful for applications that use the {@link
     * MiniSearch#discard} or {@link MiniSearch#replace} methods.
     *
     * By default, vacuuming is performed automatically when needed (controlled by
     * the `autoVacuum` field in {@link Options}), so there is usually no need to
     * call this method, unless one wants to make sure to perform vacuuming at a
     * specific moment.
     *
     * Vacuuming traverses all terms in the inverted index in batches, and cleans
     * up references to discarded documents from the posting list, allowing memory
     * to be released.
     *
     * The method takes an optional object as argument with the following keys:
     *
     *   - `batchSize`: the size of each batch (1000 by default)
     *
     *   - `batchWait`: the number of milliseconds to wait between batches (10 by
     *   default)
     *
     * On large indexes, vacuuming could have a non-negligible cost: batching
     * avoids blocking the thread for long, diluting this cost so that it is not
     * negatively affecting the application. Nonetheless, this method should only
     * be called when necessary, and relying on automatic vacuuming is usually
     * better.
     *
     * It returns a promise that resolves (to undefined) when the clean up is
     * completed. If vacuuming is already ongoing at the time this method is
     * called, a new one is enqueued immediately after the ongoing one, and a
     * corresponding promise is returned. However, no more than one vacuuming is
     * enqueued on top of the ongoing one, even if this method is called more
     * times (enqueuing multiple ones would be useless).
     *
     * @param options  Configuration options for the batch size and delay. See
     * {@link VacuumOptions}.
     */
    vacuum(options = {}) {
      return this.conditionalVacuum(options);
    }
    conditionalVacuum(options, conditions) {
      if (this._currentVacuum) {
        this._enqueuedVacuumConditions = this._enqueuedVacuumConditions && conditions;
        if (this._enqueuedVacuum != null) {
          return this._enqueuedVacuum;
        }
        this._enqueuedVacuum = this._currentVacuum.then(() => {
          const conditions2 = this._enqueuedVacuumConditions;
          this._enqueuedVacuumConditions = defaultVacuumConditions;
          return this.performVacuuming(options, conditions2);
        });
        return this._enqueuedVacuum;
      }
      if (this.vacuumConditionsMet(conditions) === false) {
        return Promise.resolve();
      }
      this._currentVacuum = this.performVacuuming(options);
      return this._currentVacuum;
    }
    async performVacuuming(options, conditions) {
      const initialDirtCount = this._dirtCount;
      if (this.vacuumConditionsMet(conditions)) {
        const batchSize = options.batchSize || defaultVacuumOptions.batchSize;
        const batchWait = options.batchWait || defaultVacuumOptions.batchWait;
        let i = 1;
        for (const [term, fieldsData] of this._index) {
          for (const [fieldId, fieldIndex] of fieldsData) {
            for (const [shortId] of fieldIndex) {
              if (this._documentIds.has(shortId)) {
                continue;
              }
              if (fieldIndex.size <= 1) {
                fieldsData.delete(fieldId);
              } else {
                fieldIndex.delete(shortId);
              }
            }
          }
          if (this._index.get(term).size === 0) {
            this._index.delete(term);
          }
          if (i % batchSize === 0) {
            await new Promise((resolve) => setTimeout(resolve, batchWait));
          }
          i += 1;
        }
        this._dirtCount -= initialDirtCount;
      }
      await null;
      this._currentVacuum = this._enqueuedVacuum;
      this._enqueuedVacuum = null;
    }
    vacuumConditionsMet(conditions) {
      if (conditions == null) {
        return true;
      }
      let { minDirtCount, minDirtFactor } = conditions;
      minDirtCount = minDirtCount || defaultAutoVacuumOptions.minDirtCount;
      minDirtFactor = minDirtFactor || defaultAutoVacuumOptions.minDirtFactor;
      return this.dirtCount >= minDirtCount && this.dirtFactor >= minDirtFactor;
    }
    /**
     * Is `true` if a vacuuming operation is ongoing, `false` otherwise
     */
    get isVacuuming() {
      return this._currentVacuum != null;
    }
    /**
     * The number of documents discarded since the most recent vacuuming
     */
    get dirtCount() {
      return this._dirtCount;
    }
    /**
     * A number between 0 and 1 giving an indication about the proportion of
     * documents that are discarded, and can therefore be cleaned up by vacuuming.
     * A value close to 0 means that the index is relatively clean, while a higher
     * value means that the index is relatively dirty, and vacuuming could release
     * memory.
     */
    get dirtFactor() {
      return this._dirtCount / (1 + this._documentCount + this._dirtCount);
    }
    /**
     * Returns `true` if a document with the given ID is present in the index and
     * available for search, `false` otherwise
     *
     * @param id  The document ID
     */
    has(id) {
      return this._idToShortId.has(id);
    }
    /**
     * Returns the stored fields (as configured in the `storeFields` constructor
     * option) for the given document ID. Returns `undefined` if the document is
     * not present in the index.
     *
     * @param id  The document ID
     */
    getStoredFields(id) {
      const shortId = this._idToShortId.get(id);
      if (shortId == null) {
        return void 0;
      }
      return this._storedFields.get(shortId);
    }
    /**
     * Search for documents matching the given search query.
     *
     * The result is a list of scored document IDs matching the query, sorted by
     * descending score, and each including data about which terms were matched and
     * in which fields.
     *
     * ### Basic usage:
     *
     * ```javascript
     * // Search for "zen art motorcycle" with default options: terms have to match
     * // exactly, and individual terms are joined with OR
     * miniSearch.search('zen art motorcycle')
     * // => [ { id: 2, score: 2.77258, match: { ... } }, { id: 4, score: 1.38629, match: { ... } } ]
     * ```
     *
     * ### Restrict search to specific fields:
     *
     * ```javascript
     * // Search only in the 'title' field
     * miniSearch.search('zen', { fields: ['title'] })
     * ```
     *
     * ### Field boosting:
     *
     * ```javascript
     * // Boost a field
     * miniSearch.search('zen', { boost: { title: 2 } })
     * ```
     *
     * ### Prefix search:
     *
     * ```javascript
     * // Search for "moto" with prefix search (it will match documents
     * // containing terms that start with "moto" or "neuro")
     * miniSearch.search('moto neuro', { prefix: true })
     * ```
     *
     * ### Fuzzy search:
     *
     * ```javascript
     * // Search for "ismael" with fuzzy search (it will match documents containing
     * // terms similar to "ismael", with a maximum edit distance of 0.2 term.length
     * // (rounded to nearest integer)
     * miniSearch.search('ismael', { fuzzy: 0.2 })
     * ```
     *
     * ### Combining strategies:
     *
     * ```javascript
     * // Mix of exact match, prefix search, and fuzzy search
     * miniSearch.search('ismael mob', {
     *  prefix: true,
     *  fuzzy: 0.2
     * })
     * ```
     *
     * ### Advanced prefix and fuzzy search:
     *
     * ```javascript
     * // Perform fuzzy and prefix search depending on the search term. Here
     * // performing prefix and fuzzy search only on terms longer than 3 characters
     * miniSearch.search('ismael mob', {
     *  prefix: term => term.length > 3
     *  fuzzy: term => term.length > 3 ? 0.2 : null
     * })
     * ```
     *
     * ### Combine with AND:
     *
     * ```javascript
     * // Combine search terms with AND (to match only documents that contain both
     * // "motorcycle" and "art")
     * miniSearch.search('motorcycle art', { combineWith: 'AND' })
     * ```
     *
     * ### Combine with AND_NOT:
     *
     * There is also an AND_NOT combinator, that finds documents that match the
     * first term, but do not match any of the other terms. This combinator is
     * rarely useful with simple queries, and is meant to be used with advanced
     * query combinations (see later for more details).
     *
     * ### Filtering results:
     *
     * ```javascript
     * // Filter only results in the 'fiction' category (assuming that 'category'
     * // is a stored field)
     * miniSearch.search('motorcycle art', {
     *   filter: (result) => result.category === 'fiction'
     * })
     * ```
     *
     * ### Wildcard query
     *
     * Searching for an empty string (assuming the default tokenizer) returns no
     * results. Sometimes though, one needs to match all documents, like in a
     * "wildcard" search. This is possible by passing the special value
     * {@link MiniSearch.wildcard} as the query:
     *
     * ```javascript
     * // Return search results for all documents
     * miniSearch.search(MiniSearch.wildcard)
     * ```
     *
     * Note that search options such as `filter` and `boostDocument` are still
     * applied, influencing which results are returned, and their order:
     *
     * ```javascript
     * // Return search results for all documents in the 'fiction' category
     * miniSearch.search(MiniSearch.wildcard, {
     *   filter: (result) => result.category === 'fiction'
     * })
     * ```
     *
     * ### Advanced combination of queries:
     *
     * It is possible to combine different subqueries with OR, AND, and AND_NOT,
     * and even with different search options, by passing a query expression
     * tree object as the first argument, instead of a string.
     *
     * ```javascript
     * // Search for documents that contain "zen" and ("motorcycle" or "archery")
     * miniSearch.search({
     *   combineWith: 'AND',
     *   queries: [
     *     'zen',
     *     {
     *       combineWith: 'OR',
     *       queries: ['motorcycle', 'archery']
     *     }
     *   ]
     * })
     *
     * // Search for documents that contain ("apple" or "pear") but not "juice" and
     * // not "tree"
     * miniSearch.search({
     *   combineWith: 'AND_NOT',
     *   queries: [
     *     {
     *       combineWith: 'OR',
     *       queries: ['apple', 'pear']
     *     },
     *     'juice',
     *     'tree'
     *   ]
     * })
     * ```
     *
     * Each node in the expression tree can be either a string, or an object that
     * supports all {@link SearchOptions} fields, plus a `queries` array field for
     * subqueries.
     *
     * Note that, while this can become complicated to do by hand for complex or
     * deeply nested queries, it provides a formalized expression tree API for
     * external libraries that implement a parser for custom query languages.
     *
     * @param query  Search query
     * @param searchOptions  Search options. Each option, if not given, defaults to the corresponding value of `searchOptions` given to the constructor, or to the library default.
     */
    search(query, searchOptions = {}) {
      const { searchOptions: globalSearchOptions } = this._options;
      const searchOptionsWithDefaults = { ...globalSearchOptions, ...searchOptions };
      const rawResults = this.executeQuery(query, searchOptions);
      const results = [];
      for (const [docId, { score, terms, match }] of rawResults) {
        const quality = terms.length || 1;
        const result = {
          id: this._documentIds.get(docId),
          score: score * quality,
          terms: Object.keys(match),
          queryTerms: terms,
          match
        };
        Object.assign(result, this._storedFields.get(docId));
        if (searchOptionsWithDefaults.filter == null || searchOptionsWithDefaults.filter(result)) {
          results.push(result);
        }
      }
      if (query === _MiniSearch.wildcard && searchOptionsWithDefaults.boostDocument == null) {
        return results;
      }
      results.sort(byScore);
      return results;
    }
    /**
     * Provide suggestions for the given search query
     *
     * The result is a list of suggested modified search queries, derived from the
     * given search query, each with a relevance score, sorted by descending score.
     *
     * By default, it uses the same options used for search, except that by
     * default it performs prefix search on the last term of the query, and
     * combine terms with `'AND'` (requiring all query terms to match). Custom
     * options can be passed as a second argument. Defaults can be changed upon
     * calling the {@link MiniSearch} constructor, by passing a
     * `autoSuggestOptions` option.
     *
     * ### Basic usage:
     *
     * ```javascript
     * // Get suggestions for 'neuro':
     * miniSearch.autoSuggest('neuro')
     * // => [ { suggestion: 'neuromancer', terms: [ 'neuromancer' ], score: 0.46240 } ]
     * ```
     *
     * ### Multiple words:
     *
     * ```javascript
     * // Get suggestions for 'zen ar':
     * miniSearch.autoSuggest('zen ar')
     * // => [
     * //  { suggestion: 'zen archery art', terms: [ 'zen', 'archery', 'art' ], score: 1.73332 },
     * //  { suggestion: 'zen art', terms: [ 'zen', 'art' ], score: 1.21313 }
     * // ]
     * ```
     *
     * ### Fuzzy suggestions:
     *
     * ```javascript
     * // Correct spelling mistakes using fuzzy search:
     * miniSearch.autoSuggest('neromancer', { fuzzy: 0.2 })
     * // => [ { suggestion: 'neuromancer', terms: [ 'neuromancer' ], score: 1.03998 } ]
     * ```
     *
     * ### Filtering:
     *
     * ```javascript
     * // Get suggestions for 'zen ar', but only within the 'fiction' category
     * // (assuming that 'category' is a stored field):
     * miniSearch.autoSuggest('zen ar', {
     *   filter: (result) => result.category === 'fiction'
     * })
     * // => [
     * //  { suggestion: 'zen archery art', terms: [ 'zen', 'archery', 'art' ], score: 1.73332 },
     * //  { suggestion: 'zen art', terms: [ 'zen', 'art' ], score: 1.21313 }
     * // ]
     * ```
     *
     * @param queryString  Query string to be expanded into suggestions
     * @param options  Search options. The supported options and default values
     * are the same as for the {@link MiniSearch#search} method, except that by
     * default prefix search is performed on the last term in the query, and terms
     * are combined with `'AND'`.
     * @return  A sorted array of suggestions sorted by relevance score.
     */
    autoSuggest(queryString, options = {}) {
      options = { ...this._options.autoSuggestOptions, ...options };
      const suggestions = /* @__PURE__ */ new Map();
      for (const { score, terms } of this.search(queryString, options)) {
        const phrase = terms.join(" ");
        const suggestion = suggestions.get(phrase);
        if (suggestion != null) {
          suggestion.score += score;
          suggestion.count += 1;
        } else {
          suggestions.set(phrase, { score, terms, count: 1 });
        }
      }
      const results = [];
      for (const [suggestion, { score, terms, count }] of suggestions) {
        results.push({ suggestion, terms, score: score / count });
      }
      results.sort(byScore);
      return results;
    }
    /**
     * Total number of documents available to search
     */
    get documentCount() {
      return this._documentCount;
    }
    /**
     * Number of terms in the index
     */
    get termCount() {
      return this._index.size;
    }
    /**
     * Deserializes a JSON index (serialized with `JSON.stringify(miniSearch)`)
     * and instantiates a MiniSearch instance. It should be given the same options
     * originally used when serializing the index.
     *
     * ### Usage:
     *
     * ```javascript
     * // If the index was serialized with:
     * let miniSearch = new MiniSearch({ fields: ['title', 'text'] })
     * miniSearch.addAll(documents)
     *
     * const json = JSON.stringify(miniSearch)
     * // It can later be deserialized like this:
     * miniSearch = MiniSearch.loadJSON(json, { fields: ['title', 'text'] })
     * ```
     *
     * @param json  JSON-serialized index
     * @param options  configuration options, same as the constructor
     * @return An instance of MiniSearch deserialized from the given JSON.
     */
    static loadJSON(json, options) {
      if (options == null) {
        throw new Error("MiniSearch: loadJSON should be given the same options used when serializing the index");
      }
      return this.loadJS(JSON.parse(json), options);
    }
    /**
     * Async equivalent of {@link MiniSearch.loadJSON}
     *
     * This function is an alternative to {@link MiniSearch.loadJSON} that returns
     * a promise, and loads the index in batches, leaving pauses between them to avoid
     * blocking the main thread. It tends to be slower than the synchronous
     * version, but does not block the main thread, so it can be a better choice
     * when deserializing very large indexes.
     *
     * @param json  JSON-serialized index
     * @param options  configuration options, same as the constructor
     * @return A Promise that will resolve to an instance of MiniSearch deserialized from the given JSON.
     */
    static async loadJSONAsync(json, options) {
      if (options == null) {
        throw new Error("MiniSearch: loadJSON should be given the same options used when serializing the index");
      }
      return this.loadJSAsync(JSON.parse(json), options);
    }
    /**
     * Returns the default value of an option. It will throw an error if no option
     * with the given name exists.
     *
     * @param optionName  Name of the option
     * @return The default value of the given option
     *
     * ### Usage:
     *
     * ```javascript
     * // Get default tokenizer
     * MiniSearch.getDefault('tokenize')
     *
     * // Get default term processor
     * MiniSearch.getDefault('processTerm')
     *
     * // Unknown options will throw an error
     * MiniSearch.getDefault('notExisting')
     * // => throws 'MiniSearch: unknown option "notExisting"'
     * ```
     */
    static getDefault(optionName) {
      if (defaultOptions.hasOwnProperty(optionName)) {
        return getOwnProperty(defaultOptions, optionName);
      } else {
        throw new Error(`MiniSearch: unknown option "${optionName}"`);
      }
    }
    /**
     * @ignore
     */
    static loadJS(js, options) {
      const { index, documentIds, fieldLength, storedFields, serializationVersion } = js;
      const miniSearch = this.instantiateMiniSearch(js, options);
      miniSearch._documentIds = objectToNumericMap(documentIds);
      miniSearch._fieldLength = objectToNumericMap(fieldLength);
      miniSearch._storedFields = objectToNumericMap(storedFields);
      for (const [shortId, id] of miniSearch._documentIds) {
        miniSearch._idToShortId.set(id, shortId);
      }
      for (const [term, data] of index) {
        const dataMap = /* @__PURE__ */ new Map();
        for (const fieldId of Object.keys(data)) {
          let indexEntry = data[fieldId];
          if (serializationVersion === 1) {
            indexEntry = indexEntry.ds;
          }
          dataMap.set(parseInt(fieldId, 10), objectToNumericMap(indexEntry));
        }
        miniSearch._index.set(term, dataMap);
      }
      return miniSearch;
    }
    /**
     * @ignore
     */
    static async loadJSAsync(js, options) {
      const { index, documentIds, fieldLength, storedFields, serializationVersion } = js;
      const miniSearch = this.instantiateMiniSearch(js, options);
      miniSearch._documentIds = await objectToNumericMapAsync(documentIds);
      miniSearch._fieldLength = await objectToNumericMapAsync(fieldLength);
      miniSearch._storedFields = await objectToNumericMapAsync(storedFields);
      for (const [shortId, id] of miniSearch._documentIds) {
        miniSearch._idToShortId.set(id, shortId);
      }
      let count = 0;
      for (const [term, data] of index) {
        const dataMap = /* @__PURE__ */ new Map();
        for (const fieldId of Object.keys(data)) {
          let indexEntry = data[fieldId];
          if (serializationVersion === 1) {
            indexEntry = indexEntry.ds;
          }
          dataMap.set(parseInt(fieldId, 10), await objectToNumericMapAsync(indexEntry));
        }
        if (++count % 1e3 === 0)
          await wait(0);
        miniSearch._index.set(term, dataMap);
      }
      return miniSearch;
    }
    /**
     * @ignore
     */
    static instantiateMiniSearch(js, options) {
      const { documentCount, nextId, fieldIds, averageFieldLength, dirtCount, serializationVersion } = js;
      if (serializationVersion !== 1 && serializationVersion !== 2) {
        throw new Error("MiniSearch: cannot deserialize an index created with an incompatible version");
      }
      const miniSearch = new _MiniSearch(options);
      miniSearch._documentCount = documentCount;
      miniSearch._nextId = nextId;
      miniSearch._idToShortId = /* @__PURE__ */ new Map();
      miniSearch._fieldIds = fieldIds;
      miniSearch._avgFieldLength = averageFieldLength;
      miniSearch._dirtCount = dirtCount || 0;
      miniSearch._index = new SearchableMap();
      return miniSearch;
    }
    /**
     * @ignore
     */
    executeQuery(query, searchOptions = {}) {
      if (query === _MiniSearch.wildcard) {
        return this.executeWildcardQuery(searchOptions);
      }
      if (typeof query !== "string") {
        const options2 = { ...searchOptions, ...query, queries: void 0 };
        const results2 = query.queries.map((subquery) => this.executeQuery(subquery, options2));
        return this.combineResults(results2, options2.combineWith);
      }
      const { tokenize, processTerm, searchOptions: globalSearchOptions } = this._options;
      const options = { tokenize, processTerm, ...globalSearchOptions, ...searchOptions };
      const { tokenize: searchTokenize, processTerm: searchProcessTerm } = options;
      const terms = searchTokenize(query).flatMap((term) => searchProcessTerm(term)).filter((term) => !!term);
      const queries = terms.map(termToQuerySpec(options));
      const results = queries.map((query2) => this.executeQuerySpec(query2, options));
      return this.combineResults(results, options.combineWith);
    }
    /**
     * @ignore
     */
    executeQuerySpec(query, searchOptions) {
      const options = { ...this._options.searchOptions, ...searchOptions };
      const boosts = (options.fields || this._options.fields).reduce((boosts2, field) => ({ ...boosts2, [field]: getOwnProperty(options.boost, field) || 1 }), {});
      const { boostDocument, weights, maxFuzzy, bm25: bm25params } = options;
      const { fuzzy: fuzzyWeight, prefix: prefixWeight } = { ...defaultSearchOptions.weights, ...weights };
      const data = this._index.get(query.term);
      const results = this.termResults(query.term, query.term, 1, query.termBoost, data, boosts, boostDocument, bm25params);
      let prefixMatches;
      let fuzzyMatches;
      if (query.prefix) {
        prefixMatches = this._index.atPrefix(query.term);
      }
      if (query.fuzzy) {
        const fuzzy = query.fuzzy === true ? 0.2 : query.fuzzy;
        const maxDistance = fuzzy < 1 ? Math.min(maxFuzzy, Math.round(query.term.length * fuzzy)) : fuzzy;
        if (maxDistance)
          fuzzyMatches = this._index.fuzzyGet(query.term, maxDistance);
      }
      if (prefixMatches) {
        for (const [term, data2] of prefixMatches) {
          const distance = term.length - query.term.length;
          if (!distance) {
            continue;
          }
          fuzzyMatches === null || fuzzyMatches === void 0 ? void 0 : fuzzyMatches.delete(term);
          const weight = prefixWeight * term.length / (term.length + 0.3 * distance);
          this.termResults(query.term, term, weight, query.termBoost, data2, boosts, boostDocument, bm25params, results);
        }
      }
      if (fuzzyMatches) {
        for (const term of fuzzyMatches.keys()) {
          const [data2, distance] = fuzzyMatches.get(term);
          if (!distance) {
            continue;
          }
          const weight = fuzzyWeight * term.length / (term.length + distance);
          this.termResults(query.term, term, weight, query.termBoost, data2, boosts, boostDocument, bm25params, results);
        }
      }
      return results;
    }
    /**
     * @ignore
     */
    executeWildcardQuery(searchOptions) {
      const results = /* @__PURE__ */ new Map();
      const options = { ...this._options.searchOptions, ...searchOptions };
      for (const [shortId, id] of this._documentIds) {
        const score = options.boostDocument ? options.boostDocument(id, "", this._storedFields.get(shortId)) : 1;
        results.set(shortId, {
          score,
          terms: [],
          match: {}
        });
      }
      return results;
    }
    /**
     * @ignore
     */
    combineResults(results, combineWith = OR) {
      if (results.length === 0) {
        return /* @__PURE__ */ new Map();
      }
      const operator = combineWith.toLowerCase();
      const combinator = combinators[operator];
      if (!combinator) {
        throw new Error(`Invalid combination operator: ${combineWith}`);
      }
      return results.reduce(combinator) || /* @__PURE__ */ new Map();
    }
    /**
     * Allows serialization of the index to JSON, to possibly store it and later
     * deserialize it with {@link MiniSearch.loadJSON}.
     *
     * Normally one does not directly call this method, but rather call the
     * standard JavaScript `JSON.stringify()` passing the {@link MiniSearch}
     * instance, and JavaScript will internally call this method. Upon
     * deserialization, one must pass to {@link MiniSearch.loadJSON} the same
     * options used to create the original instance that was serialized.
     *
     * ### Usage:
     *
     * ```javascript
     * // Serialize the index:
     * let miniSearch = new MiniSearch({ fields: ['title', 'text'] })
     * miniSearch.addAll(documents)
     * const json = JSON.stringify(miniSearch)
     *
     * // Later, to deserialize it:
     * miniSearch = MiniSearch.loadJSON(json, { fields: ['title', 'text'] })
     * ```
     *
     * @return A plain-object serializable representation of the search index.
     */
    toJSON() {
      const index = [];
      for (const [term, fieldIndex] of this._index) {
        const data = {};
        for (const [fieldId, freqs] of fieldIndex) {
          data[fieldId] = Object.fromEntries(freqs);
        }
        index.push([term, data]);
      }
      return {
        documentCount: this._documentCount,
        nextId: this._nextId,
        documentIds: Object.fromEntries(this._documentIds),
        fieldIds: this._fieldIds,
        fieldLength: Object.fromEntries(this._fieldLength),
        averageFieldLength: this._avgFieldLength,
        storedFields: Object.fromEntries(this._storedFields),
        dirtCount: this._dirtCount,
        index,
        serializationVersion: 2
      };
    }
    /**
     * @ignore
     */
    termResults(sourceTerm, derivedTerm, termWeight, termBoost, fieldTermData, fieldBoosts, boostDocumentFn, bm25params, results = /* @__PURE__ */ new Map()) {
      if (fieldTermData == null)
        return results;
      for (const field of Object.keys(fieldBoosts)) {
        const fieldBoost = fieldBoosts[field];
        const fieldId = this._fieldIds[field];
        const fieldTermFreqs = fieldTermData.get(fieldId);
        if (fieldTermFreqs == null)
          continue;
        let matchingFields = fieldTermFreqs.size;
        const avgFieldLength = this._avgFieldLength[fieldId];
        for (const docId of fieldTermFreqs.keys()) {
          if (!this._documentIds.has(docId)) {
            this.removeTerm(fieldId, docId, derivedTerm);
            matchingFields -= 1;
            continue;
          }
          const docBoost = boostDocumentFn ? boostDocumentFn(this._documentIds.get(docId), derivedTerm, this._storedFields.get(docId)) : 1;
          if (!docBoost)
            continue;
          const termFreq = fieldTermFreqs.get(docId);
          const fieldLength = this._fieldLength.get(docId)[fieldId];
          const rawScore = calcBM25Score(termFreq, matchingFields, this._documentCount, fieldLength, avgFieldLength, bm25params);
          const weightedScore = termWeight * termBoost * fieldBoost * docBoost * rawScore;
          const result = results.get(docId);
          if (result) {
            result.score += weightedScore;
            assignUniqueTerm(result.terms, sourceTerm);
            const match = getOwnProperty(result.match, derivedTerm);
            if (match) {
              match.push(field);
            } else {
              result.match[derivedTerm] = [field];
            }
          } else {
            results.set(docId, {
              score: weightedScore,
              terms: [sourceTerm],
              match: { [derivedTerm]: [field] }
            });
          }
        }
      }
      return results;
    }
    /**
     * @ignore
     */
    addTerm(fieldId, documentId, term) {
      const indexData = this._index.fetch(term, createMap);
      let fieldIndex = indexData.get(fieldId);
      if (fieldIndex == null) {
        fieldIndex = /* @__PURE__ */ new Map();
        fieldIndex.set(documentId, 1);
        indexData.set(fieldId, fieldIndex);
      } else {
        const docs = fieldIndex.get(documentId);
        fieldIndex.set(documentId, (docs || 0) + 1);
      }
    }
    /**
     * @ignore
     */
    removeTerm(fieldId, documentId, term) {
      if (!this._index.has(term)) {
        this.warnDocumentChanged(documentId, fieldId, term);
        return;
      }
      const indexData = this._index.fetch(term, createMap);
      const fieldIndex = indexData.get(fieldId);
      if (fieldIndex == null || fieldIndex.get(documentId) == null) {
        this.warnDocumentChanged(documentId, fieldId, term);
      } else if (fieldIndex.get(documentId) <= 1) {
        if (fieldIndex.size <= 1) {
          indexData.delete(fieldId);
        } else {
          fieldIndex.delete(documentId);
        }
      } else {
        fieldIndex.set(documentId, fieldIndex.get(documentId) - 1);
      }
      if (this._index.get(term).size === 0) {
        this._index.delete(term);
      }
    }
    /**
     * @ignore
     */
    warnDocumentChanged(shortDocumentId, fieldId, term) {
      for (const fieldName of Object.keys(this._fieldIds)) {
        if (this._fieldIds[fieldName] === fieldId) {
          this._options.logger("warn", `MiniSearch: document with ID ${this._documentIds.get(shortDocumentId)} has changed before removal: term "${term}" was not present in field "${fieldName}". Removing a document after it has changed can corrupt the index!`, "version_conflict");
          return;
        }
      }
    }
    /**
     * @ignore
     */
    addDocumentId(documentId) {
      const shortDocumentId = this._nextId;
      this._idToShortId.set(documentId, shortDocumentId);
      this._documentIds.set(shortDocumentId, documentId);
      this._documentCount += 1;
      this._nextId += 1;
      return shortDocumentId;
    }
    /**
     * @ignore
     */
    addFields(fields) {
      for (let i = 0; i < fields.length; i++) {
        this._fieldIds[fields[i]] = i;
      }
    }
    /**
     * @ignore
     */
    addFieldLength(documentId, fieldId, count, length) {
      let fieldLengths = this._fieldLength.get(documentId);
      if (fieldLengths == null)
        this._fieldLength.set(documentId, fieldLengths = []);
      fieldLengths[fieldId] = length;
      const averageFieldLength = this._avgFieldLength[fieldId] || 0;
      const totalFieldLength = averageFieldLength * count + length;
      this._avgFieldLength[fieldId] = totalFieldLength / (count + 1);
    }
    /**
     * @ignore
     */
    removeFieldLength(documentId, fieldId, count, length) {
      if (count === 1) {
        this._avgFieldLength[fieldId] = 0;
        return;
      }
      const totalFieldLength = this._avgFieldLength[fieldId] * count - length;
      this._avgFieldLength[fieldId] = totalFieldLength / (count - 1);
    }
    /**
     * @ignore
     */
    saveStoredFields(documentId, doc) {
      const { storeFields, extractField } = this._options;
      if (storeFields == null || storeFields.length === 0) {
        return;
      }
      let documentFields = this._storedFields.get(documentId);
      if (documentFields == null)
        this._storedFields.set(documentId, documentFields = {});
      for (const fieldName of storeFields) {
        const fieldValue = extractField(doc, fieldName);
        if (fieldValue !== void 0)
          documentFields[fieldName] = fieldValue;
      }
    }
  };
  MiniSearch.wildcard = /* @__PURE__ */ Symbol("*");
  var getOwnProperty = (object, property) => Object.prototype.hasOwnProperty.call(object, property) ? object[property] : void 0;
  var combinators = {
    [OR]: (a, b) => {
      for (const docId of b.keys()) {
        const existing = a.get(docId);
        if (existing == null) {
          a.set(docId, b.get(docId));
        } else {
          const { score, terms, match } = b.get(docId);
          existing.score = existing.score + score;
          existing.match = Object.assign(existing.match, match);
          assignUniqueTerms(existing.terms, terms);
        }
      }
      return a;
    },
    [AND]: (a, b) => {
      const combined = /* @__PURE__ */ new Map();
      for (const docId of b.keys()) {
        const existing = a.get(docId);
        if (existing == null)
          continue;
        const { score, terms, match } = b.get(docId);
        assignUniqueTerms(existing.terms, terms);
        combined.set(docId, {
          score: existing.score + score,
          terms: existing.terms,
          match: Object.assign(existing.match, match)
        });
      }
      return combined;
    },
    [AND_NOT]: (a, b) => {
      for (const docId of b.keys())
        a.delete(docId);
      return a;
    }
  };
  var defaultBM25params = { k: 1.2, b: 0.7, d: 0.5 };
  var calcBM25Score = (termFreq, matchingCount, totalCount, fieldLength, avgFieldLength, bm25params) => {
    const { k, b, d } = bm25params;
    const invDocFreq = Math.log(1 + (totalCount - matchingCount + 0.5) / (matchingCount + 0.5));
    return invDocFreq * (d + termFreq * (k + 1) / (termFreq + k * (1 - b + b * fieldLength / avgFieldLength)));
  };
  var termToQuerySpec = (options) => (term, i, terms) => {
    const fuzzy = typeof options.fuzzy === "function" ? options.fuzzy(term, i, terms) : options.fuzzy || false;
    const prefix = typeof options.prefix === "function" ? options.prefix(term, i, terms) : options.prefix === true;
    const termBoost = typeof options.boostTerm === "function" ? options.boostTerm(term, i, terms) : 1;
    return { term, fuzzy, prefix, termBoost };
  };
  var defaultOptions = {
    idField: "id",
    extractField: (document, fieldName) => document[fieldName],
    stringifyField: (fieldValue, fieldName) => fieldValue.toString(),
    tokenize: (text) => text.split(SPACE_OR_PUNCTUATION),
    processTerm: (term) => term.toLowerCase(),
    fields: void 0,
    searchOptions: void 0,
    storeFields: [],
    logger: (level, message) => {
      if (typeof (console === null || console === void 0 ? void 0 : console[level]) === "function")
        console[level](message);
    },
    autoVacuum: true
  };
  var defaultSearchOptions = {
    combineWith: OR,
    prefix: false,
    fuzzy: false,
    maxFuzzy: 6,
    boost: {},
    weights: { fuzzy: 0.45, prefix: 0.375 },
    bm25: defaultBM25params
  };
  var defaultAutoSuggestOptions = {
    combineWith: AND,
    prefix: (term, i, terms) => i === terms.length - 1
  };
  var defaultVacuumOptions = { batchSize: 1e3, batchWait: 10 };
  var defaultVacuumConditions = { minDirtFactor: 0.1, minDirtCount: 20 };
  var defaultAutoVacuumOptions = { ...defaultVacuumOptions, ...defaultVacuumConditions };
  var assignUniqueTerm = (target, term) => {
    if (!target.includes(term))
      target.push(term);
  };
  var assignUniqueTerms = (target, source2) => {
    for (const term of source2) {
      if (!target.includes(term))
        target.push(term);
    }
  };
  var byScore = ({ score: a }, { score: b }) => b - a;
  var createMap = () => /* @__PURE__ */ new Map();
  var objectToNumericMap = (object) => {
    const map = /* @__PURE__ */ new Map();
    for (const key of Object.keys(object)) {
      map.set(parseInt(key, 10), object[key]);
    }
    return map;
  };
  var objectToNumericMapAsync = async (object) => {
    const map = /* @__PURE__ */ new Map();
    let count = 0;
    for (const key of Object.keys(object)) {
      map.set(parseInt(key, 10), object[key]);
      if (++count % 1e3 === 0) {
        await wait(0);
      }
    }
    return map;
  };
  var wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  var SPACE_OR_PUNCTUATION = /[\n\r\p{Z}\p{P}]+/u;

  // .goose/out/rc022-prep-20261114-01/source/packages/util/values/src/partial-json.ts
  var SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    b: "\b",
    f: "\f",
    n: "\n",
    r: "\r",
    t: "	"
  };
  var CONTENT_ESCAPE = /[\\\u0000-\u001f]/u;
  function isWhitespace(c) {
    return c === " " || c === "\n" || c === "\r" || c === "	";
  }
  function isHex(c) {
    return c >= "0" && c <= "9" || c >= "a" && c <= "f" || c >= "A" && c <= "F";
  }
  var PartialArguments = class _PartialArguments {
    /** The view of a call with no arguments available. */
    static EMPTY = _PartialArguments.fromObject({});
    /**
     * View finished argument text without scanning it until a reader asks.
     * @param text - the complete argument JSON text.
     * @returns a sealed view.
     */
    static fromText(text) {
      const view = new _PartialArguments();
      view.append(text);
      view.sealed = true;
      return view;
    }
    /**
     * View an already parsed argument payload, such as a PTC dispatch object.
     * @param value - the parsed argument value.
     * @returns a sealed view; a non-object payload has no fields.
     */
    static fromObject(value) {
      const view = new _PartialArguments();
      view.object = typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
      view.sealed = true;
      return view;
    }
    /**
     * The source: text so far or a parsed object, plus whether it can still grow.
     * These are the only enumerable fields, so two views over the same source
     * compare equal structurally however far each has been read.
     */
    chunks = [];
    object;
    sealed = false;
    // Scan progress, located fields, and remembered reads are caches over the source.
    #ends = [];
    #size = 0;
    #consumed = 0;
    #mode = "root";
    #escape = false;
    #keyStart = 0;
    #keyEscaped = false;
    #key = "";
    #current = null;
    #nestedEnds = [];
    #nestedInString = false;
    #invalidAt;
    #invalidValue = false;
    #entries = /* @__PURE__ */ new Map();
    #order = [];
    #reads = /* @__PURE__ */ new Map();
    /** Whether this view rejects further appends; does not scan text or register reads. */
    get isSealed() {
      return this.sealed;
    }
    /** Whether indexing or a content read found invalid JSON; unread value contents are not validated. */
    get invalid() {
      this.scan();
      return this.#mode === "invalid" || this.#invalidValue;
    }
    /**
     * Retain streamed argument text without scanning or comparing observed answers.
     * @param fragment - the text following every fragment appended before.
     */
    append(fragment) {
      if (this.sealed) throw new Error("PartialArguments: cannot append to a sealed view");
      if (fragment.length === 0) return;
      this.chunks.push(fragment);
      this.#size += fragment.length;
      this.#ends.push(this.#size);
    }
    /**
     * Reconcile a streamed prefix with authoritative complete text without joining the fragments.
     * @param text - the final argument text, which replaces missing or conflicting deltas.
     * @returns this view sealed with its caches retained when every character matches; otherwise a new sealed view.
     */
    settle(text) {
      if (this.object !== void 0 || text.length !== this.#size) return _PartialArguments.fromText(text);
      let offset = 0;
      for (const chunk of this.chunks) {
        if (!text.startsWith(chunk, offset)) return _PartialArguments.fromText(text);
        offset += chunk.length;
      }
      this.chunks = text.length === 0 ? [] : [text];
      this.#ends = text.length === 0 ? [] : [text.length];
      this.sealed = true;
      return this;
    }
    /**
     * Compare observed answers and advance their publication baseline. Unread views remain unscanned.
     * @returns whether any observed answer changed since its first read or the preceding refresh.
     */
    refresh() {
      if (this.#reads.size === 0) return false;
      this.scan();
      let changed = false;
      let completions = false;
      for (const read of this.#reads.values()) {
        if (read.completion) {
          completions = true;
          continue;
        }
        changed = this.refreshRead(read) || changed;
      }
      if (completions) {
        for (const read of this.#reads.values()) if (read.completion) changed = this.refreshRead(read) || changed;
      }
      if (this.sealed) this.#reads.clear();
      return changed;
    }
    refreshRead(read) {
      const now = read.answer();
      if (Object.is(now, read.last)) return false;
      read.last = now;
      return true;
    }
    /**
     * Check whether no further fields can arrive.
     * @returns whether the outer object closed, indexing failed, or the view is sealed; unread values are not validated.
     */
    closed() {
      return this.remember("closed", "", () => this.closedNow());
    }
    /**
     * List discovered fields in first-appearance order.
     * @returns top-level keys seen so far, in first-appearance order.
     */
    keys() {
      return this.remember("keys", "", () => this.keysNow(), (keys) => keys.length);
    }
    /**
     * Check whether a top-level field has appeared.
     * @param key - argument name.
     * @returns whether the field has appeared (a string opened or another value began).
     */
    has(key) {
      return this.remember("has", key, () => this.hasNow(key));
    }
    /**
     * Check whether a field's closing delimiter has arrived, without validating its contents.
     * @param key - argument name.
     * @returns whether its delimiter arrived and no content reader has reported an error for this value.
     */
    complete(key) {
      return this.remember("complete", key, () => this.completeNow(key));
    }
    /**
     * Read string length without materializing its text.
     * @param key - argument name.
     * @param options - change granularity for a streaming string.
     * @returns decoded UTF-16 length of the string field so far; undefined when absent or not a string.
     */
    stringLength(key, options) {
      const step = Math.max(1, Math.floor(options?.step ?? 1));
      const offset = options?.offset ?? 0;
      return this.remember(
        `length:${step}:${offset}`,
        key,
        () => this.lengthNow(key),
        (length) => length === void 0 ? void 0 : Math.ceil((length + offset) / step)
      );
    }
    /**
     * Check a string against a decoded UTF-16 length limit without materializing it.
     * @param key - argument name.
     * @param maxLength - decoded UTF-16 limit, floored to at least zero.
     * @returns whether the string is longer than the limit; false when absent or not a string.
     */
    stringExceeds(key, maxLength) {
      const limit = Math.max(0, Math.floor(maxLength));
      return this.remember(
        `exceeds:${limit}`,
        key,
        () => (this.lengthNow(key, limit + 1) ?? 0) > limit
      );
    }
    /**
     * Read a decoded string, including a streaming prefix.
     * @param key - argument name.
     * @returns the string field's decoded text so far; undefined when absent or not a string.
     */
    text(key) {
      return this.remember("text", key, () => this.textNow(key));
    }
    /**
     * Read at most the first decoded UTF-16 units of a string.
     * @param key - argument name.
     * @param maxLength - maximum decoded UTF-16 length, floored to at least one.
     * @returns the bounded string prefix; undefined when absent or not a string.
     */
    textPrefix(key, maxLength) {
      const limit = Math.max(1, Math.floor(maxLength));
      return this.remember(
        `prefix:${limit}`,
        key,
        () => this.textPrefixNow(key, limit)
      );
    }
    /**
     * Read a completed non-string argument.
     * @param key - argument name.
     * @returns the parsed non-string value once it closed; undefined while open, absent, or a string.
     */
    value(key) {
      return this.remember("value", key, () => this.valueNow(key));
    }
    /** Answer a question and, on a streaming view, remember it for change detection. */
    remember(kind, key, read, comparison) {
      this.scan();
      const result = read();
      if (!this.sealed) {
        const id = `${kind}/${key}`;
        if (!this.#reads.has(id)) {
          this.#reads.set(id, {
            completion: kind === "complete",
            answer: comparison === void 0 ? read : () => comparison(read()),
            last: comparison === void 0 ? result : comparison(result)
          });
        }
      }
      return result;
    }
    closedNow() {
      return this.sealed || this.#mode === "closed" || this.#mode === "invalid";
    }
    keysNow() {
      return this.object === void 0 ? this.#order : Object.keys(this.object);
    }
    hasNow(key) {
      return this.object === void 0 ? this.#entries.has(key) : Object.hasOwn(this.object, key);
    }
    completeNow(key) {
      if (this.object !== void 0) return Object.hasOwn(this.object, key);
      const entry = this.#entries.get(key);
      return entry !== void 0 && entry.end >= 0 && (entry.kind === "string" ? entry.invalidAt === void 0 : !entry.invalid);
    }
    lengthNow(key, limit = Number.POSITIVE_INFINITY) {
      if (this.object !== void 0) {
        const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
        return typeof field === "string" ? field.length : void 0;
      }
      const entry = this.#entries.get(key);
      if (entry?.kind !== "string") return void 0;
      if (entry.text !== void 0 && entry.text.at === entry.end) return entry.text.length;
      const read = entry.length ??= { at: entry.start, length: 0, text: "" };
      this.readString(entry, read, limit, false);
      return read.length;
    }
    textNow(key) {
      if (this.object !== void 0) {
        const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
        return typeof field === "string" ? field : void 0;
      }
      const entry = this.#entries.get(key);
      if (entry?.kind !== "string") return void 0;
      if (entry.text === void 0 && entry.end >= 0 && entry.needsDecoding && entry.invalidAt === void 0) {
        let text;
        try {
          text = JSON.parse(`"${this.slice(entry.start, entry.end)}"`);
        } catch (_error) {
        }
        if (text !== void 0) entry.text = { at: entry.end, length: text.length, text };
      }
      const read = entry.text ??= { at: entry.start, length: 0, text: "" };
      this.readString(entry, read, Number.POSITIVE_INFINITY, true);
      return read.text;
    }
    textPrefixNow(key, maxLength) {
      if (this.object !== void 0) {
        const field = Object.hasOwn(this.object, key) ? this.object[key] : void 0;
        return typeof field === "string" ? field.slice(0, maxLength) : void 0;
      }
      const entry = this.#entries.get(key);
      if (entry?.kind !== "string") return void 0;
      const prefixes = entry.prefixes ??= /* @__PURE__ */ new Map();
      let read = prefixes.get(maxLength);
      if (read === void 0) {
        read = { at: entry.start, length: 0, text: "" };
        prefixes.set(maxLength, read);
      }
      this.readString(entry, read, maxLength, true);
      return read.text;
    }
    valueNow(key) {
      if (this.object !== void 0) {
        if (!Object.hasOwn(this.object, key)) return void 0;
        const field = this.object[key];
        return typeof field === "string" ? void 0 : field;
      }
      const entry = this.#entries.get(key);
      if (entry?.kind !== "value" || entry.end < 0 || entry.invalid) return void 0;
      if (entry.parsed === void 0) {
        try {
          entry.parsed = JSON.parse(this.slice(entry.start, entry.end));
        } catch (_error) {
          entry.invalid = true;
          this.#invalidValue = true;
        }
      }
      return entry.parsed;
    }
    chunkAt(at) {
      let low = 0;
      let high = this.#ends.length;
      while (low < high) {
        const mid = low + high >>> 1;
        if (this.#ends[mid] <= at) low = mid + 1;
        else high = mid;
      }
      return low;
    }
    /** Materialize only a requested range, never the cumulative source. */
    slice(start, end) {
      if (start >= end) return "";
      const first = this.chunkAt(start);
      const last2 = this.chunkAt(end - 1);
      const base = first === 0 ? 0 : this.#ends[first - 1];
      if (first === last2) return this.chunks[first].slice(start - base, end - base);
      const parts = [this.chunks[first].slice(start - base)];
      for (let i = first + 1; i < last2; i++) parts.push(this.chunks[i]);
      parts.push(this.chunks[last2].slice(0, end - this.#ends[last2 - 1]));
      return parts.join("");
    }
    readString(entry, read, limit, materialize) {
      const end = Math.min(
        entry.end < 0 ? this.#consumed : entry.end,
        entry.invalidAt ?? Number.POSITIVE_INFINITY,
        this.#invalidAt ?? Number.POSITIVE_INFINITY
      );
      if (!entry.needsDecoding) {
        const length = Math.min(end - read.at, limit - read.length);
        if (length <= 0) return;
        if (materialize) read.text += this.slice(read.at, read.at + length);
        read.at += length;
        read.length += length;
        return;
      }
      let chunkIndex = this.chunkAt(read.at);
      while (read.at < end && read.length < limit) {
        const base = chunkIndex === 0 ? 0 : this.#ends[chunkIndex - 1];
        const chunk = this.chunks[chunkIndex];
        const remaining = chunk.slice(read.at - base, Math.min(chunk.length, end - base));
        const boundary = remaining.search(CONTENT_ESCAPE);
        const length = Math.min(boundary < 0 ? remaining.length : boundary, limit - read.length);
        if (length > 0) {
          if (materialize) read.text += remaining.slice(0, length);
          read.at += length;
          read.length += length;
          if (read.at === base + chunk.length) chunkIndex++;
          continue;
        }
        const type = remaining.length > 1 ? remaining[1] : read.at + 1 < end ? this.chunks[chunkIndex + 1][0] : void 0;
        let decoded;
        let width = 2;
        if (remaining[0] === "\\" && type === void 0 && entry.end < 0) return;
        if (remaining[0] === "\\" && type === "u") {
          const hex = this.slice(read.at + 2, Math.min(end, read.at + 6));
          let valid = true;
          for (let i = 0; i < hex.length; i++) if (!isHex(hex[i])) valid = false;
          if (valid) {
            if (hex.length < 4 && entry.end < 0) return;
            if (hex.length === 4) decoded = String.fromCharCode(Number.parseInt(hex, 16));
          }
          width = 6;
        } else if (remaining[0] === "\\" && type !== void 0) {
          decoded = SIMPLE_ESCAPES[type];
        }
        if (decoded === void 0) {
          entry.invalidAt = read.at;
          this.#invalidValue = true;
          return;
        }
        if (materialize) read.text += decoded;
        read.length++;
        read.at += width;
        while (chunkIndex < this.chunks.length && read.at >= this.#ends[chunkIndex]) chunkIndex++;
      }
    }
    /** Locate new field ranges without decoding or parsing their contents. */
    scan() {
      if (this.object !== void 0 || this.#consumed === this.#size) return;
      for (let i = this.chunkAt(this.#consumed); i < this.chunks.length && this.#invalidAt === void 0; i++) {
        const pending = this.chunks[i];
        const base = i === 0 ? 0 : this.#ends[i - 1];
        for (let index = this.#consumed - base; index < pending.length && this.#mode !== "invalid"; index++) {
          if (this.#mode === "string" || this.#mode === "nested" && this.#nestedInString) {
            const end = this.stringBoundary(pending, index);
            this.#consumed += end - index;
            index = end;
            if (index === pending.length) break;
          }
          this.step(pending[index], this.#consumed);
          this.#consumed++;
        }
      }
    }
    /** Only raw quotes and their preceding backslash runs can terminate a string. */
    stringBoundary(fragment, start) {
      let at = start;
      while (true) {
        const quote = fragment.indexOf('"', at);
        const end = quote < 0 ? fragment.length : quote;
        if (this.#mode === "string") {
          const entry = this.#current;
          if (!entry.needsDecoding && CONTENT_ESCAPE.test(fragment.slice(at, end))) entry.needsDecoding = true;
        }
        let slashStart = end;
        while (slashStart > at && fragment[slashStart - 1] === "\\") slashStart--;
        const escaped = (end - slashStart) % 2 === 1 !== (slashStart === at && this.#escape);
        this.#escape = quote < 0 && escaped;
        if (quote < 0 || !escaped) return end;
        at = quote + 1;
      }
    }
    step(c, at) {
      switch (this.#mode) {
        case "root":
          if (isWhitespace(c)) return;
          if (c === "{") {
            this.#mode = "key-or-end";
            return;
          }
          this.fail();
          return;
        case "key-or-end":
          if (isWhitespace(c)) return;
          if (c === "}") {
            this.#mode = "closed";
            return;
          }
          if (c === '"') {
            this.beginKey(at);
            return;
          }
          this.fail();
          return;
        case "key-only":
          if (isWhitespace(c)) return;
          if (c === '"') {
            this.beginKey(at);
            return;
          }
          this.fail();
          return;
        case "key":
          this.stepKey(c, at);
          return;
        case "colon":
          if (isWhitespace(c)) return;
          if (c === ":") {
            this.#mode = "value";
            return;
          }
          this.fail();
          return;
        case "value":
          this.beginValue(c, at);
          return;
        case "string": {
          const entry = this.#current;
          entry.end = at;
          this.#current = null;
          this.#mode = "comma-or-end";
          return;
        }
        case "scalar":
          this.stepScalar(c, at);
          return;
        case "nested":
          this.stepNested(c, at);
          return;
        case "comma-or-end":
          if (isWhitespace(c)) return;
          if (c === ",") {
            this.#mode = "key-only";
            return;
          }
          if (c === "}") {
            this.#mode = "closed";
            return;
          }
          this.fail();
          return;
        case "closed":
          if (isWhitespace(c)) return;
          this.fail();
          return;
        /* v8 ignore next 2 -- scan() stops stepping once the view is invalid. */
        case "invalid":
          return;
        /* v8 ignore next 2 -- Every scanner mode has a handler above. */
        default:
          assertNever(this.#mode);
      }
    }
    fail() {
      this.#invalidAt = this.#consumed;
      this.#mode = "invalid";
      this.#current = null;
    }
    beginKey(at) {
      this.#mode = "key";
      this.#keyStart = at + 1;
      this.#keyEscaped = false;
      this.#escape = false;
    }
    stepKey(c, at) {
      if (c < " ") {
        this.fail();
        return;
      }
      if (this.#escape) {
        this.#escape = false;
        return;
      }
      if (c === "\\") {
        this.#escape = true;
        this.#keyEscaped = true;
        return;
      }
      if (c !== '"') return;
      const raw = this.slice(this.#keyStart, at);
      if (this.#keyEscaped) {
        try {
          this.#key = JSON.parse(`"${raw}"`);
        } catch (_error) {
          this.fail();
          return;
        }
      } else {
        this.#key = raw;
      }
      this.#mode = "colon";
    }
    open(entry) {
      if (!this.#entries.has(this.#key)) this.#order.push(this.#key);
      this.#entries.set(this.#key, entry);
      this.#current = entry;
    }
    beginValue(c, at) {
      if (isWhitespace(c)) return;
      if (c === '"') {
        this.open({
          kind: "string",
          start: at + 1,
          end: -1,
          needsDecoding: false,
          invalidAt: void 0,
          length: void 0,
          text: void 0,
          prefixes: void 0
        });
        this.#escape = false;
        this.#mode = "string";
        return;
      }
      if (c === "}" || c === "," || c === ":" || c === "]") {
        this.fail();
        return;
      }
      this.open({ kind: "value", start: at, end: -1, parsed: void 0, invalid: false });
      if (c === "{" || c === "[") {
        this.#mode = "nested";
        this.#nestedEnds = [c === "{" ? "}" : "]"];
        this.#nestedInString = false;
        this.#escape = false;
        return;
      }
      this.#mode = "scalar";
    }
    stepScalar(c, at) {
      if (c !== "," && c !== "}" && !isWhitespace(c)) return;
      this.closeValue(at);
      this.#mode = c === "," ? "key-only" : c === "}" ? "closed" : "comma-or-end";
    }
    stepNested(c, at) {
      if (this.#nestedInString) {
        this.#nestedInString = false;
        return;
      }
      if (c === '"') {
        this.#nestedInString = true;
        return;
      }
      if (c === "{" || c === "[") {
        this.#nestedEnds.push(c === "{" ? "}" : "]");
        return;
      }
      if (c === "}" || c === "]") {
        if (this.#nestedEnds.pop() !== c) {
          this.fail();
          return;
        }
        if (this.#nestedEnds.length === 0) {
          this.closeValue(at + 1);
          this.#mode = "comma-or-end";
        }
      }
    }
    closeValue(end) {
      const entry = this.#current;
      entry.end = end;
      this.#current = null;
    }
  };

  // .goose/out/rc022-prep-20261114-01/source/packages/util/values/src/index.ts
  function assertNever(value, context) {
    const rendered = JSON.stringify(value) ?? String(value);
    throw new Error(`unreachable variant${context ? ` in ${context}` : ""}: ${rendered}`);
  }

  // .goose/out/rc022-prep-20261114-01/source/packages/boot/plugin-market/src/search.ts
  var CJK = String.raw`[[\p{scx=Han}\p{scx=Hira}\p{scx=Kana}\p{scx=Hang}]&&[\p{L}\p{M}\p{N}]]`;
  var RUN = new RegExp(String.raw`${CJK}+|[[\p{L}\p{M}\p{N}]--${CJK}]+`, "gv");
  var CJK_START = new RegExp(String.raw`^${CJK}`, "v");
  function searchTerms(text) {
    return [...text.normalize("NFKC").matchAll(RUN)].flatMap(([run]) => {
      if (!CJK_START.test(run)) return [run];
      const chars = Array.from(run);
      return [...chars.slice(1).map((char, position) => `${chars[position]}${char}`), chars.at(-1)];
    });
  }
  function variants(text) {
    if (text === void 0) return [];
    return typeof text === "string" ? [text] : Object.values(text);
  }
  var BUILD_CHUNK = 500;
  var MarketSearch = class {
    /** @param index - the validated index to search. */
    constructor(index) {
      this.index = index;
    }
    index;
    engine;
    /**
     * Select and order the plugins matching a query.
     * @param selection - text, filters, and order.
     * @returns every matching plugin in result order.
     */
    async select(selection) {
      const plugins = this.index.plugins;
      const text = selection.text ?? "";
      const scores = /* @__PURE__ */ new Map();
      let positions;
      if (searchTerms(text).length === 0) {
        positions = plugins.map((_plugin, position) => position);
      } else {
        for (const result of await this.search(text)) scores.set(result.id, result.score);
        positions = [...scores.keys()].sort((a, b) => a - b);
      }
      const labels = selection.labels ?? [];
      const matching = positions.filter((position) => {
        const { metadata } = plugins[position];
        return (selection.category === void 0 || metadata.category === selection.category) && labels.every((label) => metadata.labels.includes(label));
      });
      return this.order(matching, selection.sort, scores).map((position) => plugins[position]);
    }
    async search(text) {
      this.engine ??= this.build();
      return (await this.engine).search(text);
    }
    async build() {
      const { categories, labels } = this.index.metadata;
      const engine = new MiniSearch({
        fields: ["name", "title", "keywords", "description", "author", "taxonomy"],
        storeFields: [],
        tokenize: searchTerms,
        processTerm: (term) => term.toLowerCase(),
        searchOptions: {
          boost: { name: 3, title: 3, keywords: 2 },
          prefix: true,
          // Edit distance of one fifth of the term length, rounded, at most 2; shorter terms match only as written or as a prefix.
          fuzzy: (term) => term.length >= 4 ? 0.2 : false,
          maxFuzzy: 2,
          combineWith: "AND"
        }
      });
      await engine.addAllAsync(this.index.plugins.map((plugin2, id) => {
        const { category, keywords } = plugin2.metadata;
        const title = (declarations2, id2) => variants(declarations2[id2].title);
        const taxonomy = [
          ...category === void 0 ? [] : title(categories, category),
          ...plugin2.metadata.labels.flatMap((label) => title(labels, label))
        ];
        return {
          id,
          name: plugin2.name,
          title: variants(plugin2.title).join("\n"),
          keywords: keywords.join("\n"),
          description: variants(plugin2.description).join("\n"),
          author: plugin2.author ?? "",
          taxonomy: taxonomy.join("\n")
        };
      }), { chunkSize: BUILD_CHUNK });
      return engine;
    }
    order(positions, sort, scores) {
      switch (sort.kind) {
        case "index":
          return positions;
        case "relevance":
          return positions.sort((a, b) => (scores.get(b) ?? 0) - (scores.get(a) ?? 0) || a - b);
        case "published":
        case "key": {
          const value = (position) => {
            const plugin2 = this.index.plugins[position];
            if (sort.kind === "published") return Math.max(...plugin2.versions.map((version) => version.publishTimestamp));
            return Object.hasOwn(plugin2.metadata.sortKeys, sort.id) ? plugin2.metadata.sortKeys[sort.id] : void 0;
          };
          const sign = sort.direction === "asc" ? 1 : -1;
          return positions.map((position) => ({ position, value: value(position) })).sort((a, b) => {
            if (a.value === void 0 || b.value === void 0) {
              return a.value === b.value ? a.position - b.position : a.value === void 0 ? 1 : -1;
            }
            return (a.value - b.value) * sign || a.position - b.position;
          }).map((item) => item.position);
        }
        /* v8 ignore next -- the Gateway validates `sort` against the closed union */
        default:
          return assertNever(sort);
      }
    }
  };

  // .goose/out/rc022-prep-20261114-01/source/packages/typert/protocol/src/remote-error.ts
  var RemoteError = class extends Error {
    /**
     * @param code - stable failure code declared in {@link RemoteErrorDetailsMap}.
     * @param message - human diagnostic carried across the wire.
     * @param details - structured payload typed by the code.
     * @param options - standard Error options (`cause` survives in-process only).
     */
    constructor(code, message, details, options) {
      super(message, options);
      this.code = code;
      this.details = details;
      this.name = "RemoteError";
    }
    code;
    details;
    /** Structural marker: cross-realm/bundle identification never uses instanceof. */
    isDSHRemoteError = true;
  };

  // .goose/out/rc022-prep-20261114-01/source/packages/boot/plugin-market/src/index-url.ts
  function normalizeIndexUrl(text) {
    let url;
    try {
      url = new URL(text.trim());
    } catch {
      throw new RemoteError("plugin-market/invalid-index-url", `Not an absolute URL: ${text}`, { url: text, reason: "not-absolute" });
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") {
      throw new RemoteError("plugin-market/invalid-index-url", `Index URLs use http or https: ${text}`, { url: text, reason: "scheme" });
    }
    if (url.username !== "" || url.password !== "" || url.href.includes("#")) {
      throw new RemoteError("plugin-market/invalid-index-url", `Index URLs carry no credentials or fragment: ${text}`, { url: text, reason: "credentials-or-fragment" });
    }
    return url.href;
  }

  // market-repository:detail.ts
  var import_hosted_git_info = __toESM(require_lib());

  // scripts/native/market-index/posix.ts
  var posix = {
    isAbsolute: (path) => path.startsWith("/"),
    normalize(path) {
      if (path === "") return ".";
      const absolute = path.startsWith("/"), trailing = path.endsWith("/"), parts = [];
      for (const part of path.split("/")) {
        if (part === "" || part === ".") continue;
        if (part === "..") {
          if (parts.length && parts.at(-1) !== "..") parts.pop();
          else if (!absolute) parts.push("..");
        } else parts.push(part);
      }
      let value = parts.join("/");
      if (!value && !absolute) value = ".";
      if (value && trailing) value += "/";
      return (absolute ? "/" : "") + value;
    }
  };

  // market-repository:detail.ts
  function repositoryOf(url) {
    const declared = url.replace(/#.*$/u, "");
    const hosted = import_hosted_git_info.default.fromUrl(declared);
    if (hosted !== void 0) {
      if (hosted.type === "gist") return void 0;
      const project2 = `${hosted.user}/${hosted.project}`;
      return { host: hosted.domain.toLowerCase(), project: project2, url: `https://${hosted.domain}/${project2}.git` };
    }
    const address = declared.replace(/^git\+/u, "");
    if (!URL.canParse(address)) return void 0;
    const parsed = new URL(address);
    const project = parsed.pathname.replace(/\/-\/.*$/u, "").replace(/^\/+|\/+$/gu, "").replace(/\.git$/u, "");
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:" || parsed.username !== "" || parsed.password !== "" || project.split("/").length < 2) {
      return void 0;
    }
    return { host: parsed.hostname.toLowerCase(), project, url: `${parsed.protocol}//${parsed.host}/${project}.git` };
  }
  function manifestRepository(value) {
    const object = typeof value === "object" && value !== null ? value : void 0;
    const declared = object === void 0 ? value : object.url;
    if (typeof declared !== "string") return void 0;
    const repository2 = repositoryOf(declared);
    if (repository2 === void 0) return void 0;
    return { ...repository2, directory: typeof object?.directory === "string" ? normalizedDirectory(object.directory) ?? "" : "" };
  }
  function normalizedDirectory(directory) {
    const normalized = posix.normalize(directory.replace(/\\/gu, "/")).replace(/\/+$/u, "");
    if (normalized === "." || normalized === "") return "";
    return normalized === ".." || normalized.startsWith("../") || posix.isAbsolute(normalized) ? void 0 : normalized;
  }

  // scripts/native/market-index/entry.ts
  function openSearch(value, url) {
    const search = new MarketSearch(parseMarketIndex(value, url));
    return async (selection) => (await search.select(selection)).map((plugin2) => plugin2.name);
  }
  async function observe(operation) {
    try {
      if (operation.kind === "repository") return { ok: true, value: repositoryOf(operation.value) ?? null };
      if (operation.kind === "manifest-repository") return { ok: true, value: manifestRepository(operation.value) ?? null };
      if (operation.kind === "body") {
        let value;
        try {
          value = JSON.parse(operation.text);
        } catch (error) {
          const reason = `must be JSON: ${error.message}`;
          return { ok: false, path: "$", reason, message: reason };
        }
        try {
          return { ok: true, index: parseMarketIndex(value, operation.url) };
        } catch (error) {
          if (!(error instanceof MarketIndexError)) throw error;
          return { ok: false, path: error.path, reason: error.reason, message: error.message };
        }
      }
      if (operation.kind === "url") {
        return {
          ok: true,
          canonical: URL.canParse(operation.text) ? new URL(operation.text).href : operation.text,
          value: normalizeIndexUrl(operation.text)
        };
      }
      const index = parseMarketIndex(operation.value, operation.url);
      if (operation.kind === "search") {
        const engine = new MarketSearch(index);
        const results = [];
        for (const selection of operation.selections) {
          results.push((await engine.select(selection)).map((plugin2) => plugin2.name));
        }
        return { ok: true, results };
      }
      return { ok: true, index, targets: index.plugins.map((plugin2) => ({
        name: plugin2.name,
        versions: plugin2.versions.map((version) => marketInstallTarget(plugin2.name, version))
      })) };
    } catch (error) {
      return { ok: false, error: {
        name: error.name,
        message: error.message,
        ...error.code === void 0 ? {} : { code: error.code, details: error.details },
        ...operation.kind !== "url" ? {} : { canonical: URL.canParse(operation.text) ? new URL(operation.text).href : operation.text },
        ...error.path === void 0 ? {} : { path: error.path, reason: error.reason }
      } };
    }
  }
  return __toCommonJS(entry_exports);
})();
