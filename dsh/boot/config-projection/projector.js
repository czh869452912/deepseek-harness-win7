var __configProjection = (() => {
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

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/@eslint-community+regexpp@4.12.2/node_modules/@eslint-community/regexpp/index.mjs
  var regexpp_exports = {};
  __export(regexpp_exports, {
    AST: () => ast,
    RegExpParser: () => RegExpParser,
    RegExpSyntaxError: () => RegExpSyntaxError,
    RegExpValidator: () => RegExpValidator,
    parseRegExpLiteral: () => parseRegExpLiteral,
    validateRegExpLiteral: () => validateRegExpLiteral,
    visitRegExpAST: () => visitRegExpAST
  });
  function isIdStart(cp) {
    if (cp < 65)
      return false;
    if (cp < 91)
      return true;
    if (cp < 97)
      return false;
    if (cp < 123)
      return true;
    return isLargeIdStart(cp);
  }
  function isIdContinue(cp) {
    if (cp < 48)
      return false;
    if (cp < 58)
      return true;
    if (cp < 65)
      return false;
    if (cp < 91)
      return true;
    if (cp === 95)
      return true;
    if (cp < 97)
      return false;
    if (cp < 123)
      return true;
    return isLargeIdStart(cp) || isLargeIdContinue(cp);
  }
  function isLargeIdStart(cp) {
    return isInRange(cp, largeIdStartRanges !== null && largeIdStartRanges !== void 0 ? largeIdStartRanges : largeIdStartRanges = initLargeIdStartRanges());
  }
  function isLargeIdContinue(cp) {
    return isInRange(cp, largeIdContinueRanges !== null && largeIdContinueRanges !== void 0 ? largeIdContinueRanges : largeIdContinueRanges = initLargeIdContinueRanges());
  }
  function initLargeIdStartRanges() {
    return restoreRanges("4q 0 b 0 5 0 6 m 2 u 2 cp 5 b f 4 8 0 2 0 3m 4 2 1 3 3 2 0 7 0 2 2 2 0 2 j 2 2a 2 3u 9 4l 2 11 3 0 7 14 20 q 5 3 1a 16 10 1 2 2q 2 0 g 1 8 1 b 2 3 0 h 0 2 t u 2g c 0 p w a 1 5 0 6 l 5 0 a 0 4 0 o o 8 a 6 n 2 6 h 15 1n 1h 4 0 j 0 8 9 g f 5 7 3 1 3 l 2 6 2 0 4 3 4 0 h 0 e 1 2 2 f 1 b 0 9 5 5 1 3 l 2 6 2 1 2 1 2 1 w 3 2 0 k 2 h 8 2 2 2 l 2 6 2 1 2 4 4 0 j 0 g 1 o 0 c 7 3 1 3 l 2 6 2 1 2 4 4 0 v 1 2 2 g 0 i 0 2 5 4 2 2 3 4 1 2 0 2 1 4 1 4 2 4 b n 0 1h 7 2 2 2 m 2 f 4 0 r 2 2 1 3 1 v 0 5 7 2 2 2 m 2 9 2 4 4 0 v 2 2 1 g 1 i 8 2 2 2 14 3 0 h 0 6 2 9 2 p 5 6 h 4 n 2 8 2 0 3 6 1n 1b 2 1 d 6 1n 1 2 0 2 4 2 n 2 0 2 9 2 1 a 0 3 4 2 0 m 3 x 0 1s 7 2 z s 4 38 16 l 0 h 5 5 3 4 0 4 1 8 2 5 c d 0 i 11 2 0 6 0 3 16 2 98 2 3 3 6 2 0 2 3 3 14 2 3 3 w 2 3 3 6 2 0 2 3 3 e 2 1k 2 3 3 1u 12 f h 2d 3 5 4 h7 3 g 2 p 6 22 4 a 8 h e i f h f c 2 2 g 1f 10 0 5 0 1w 2g 8 14 2 0 6 1x b u 1e t 3 4 c 17 5 p 1j m a 1g 2b 0 2m 1a i 7 1j t e 1 b 17 r z 16 2 b z 3 a 6 16 3 2 16 3 2 5 2 1 4 0 6 5b 1t 7p 3 5 3 11 3 5 3 7 2 0 2 0 2 0 2 u 3 1g 2 6 2 0 4 2 2 6 4 3 3 5 5 c 6 2 2 6 39 0 e 0 h c 2u 0 5 0 3 9 2 0 3 5 7 0 2 0 2 0 2 f 3 3 6 4 5 0 i 14 22g 6c 7 3 4 1 d 11 2 0 6 0 3 1j 8 0 h m a 6 2 6 2 6 2 6 2 6 2 6 2 6 2 6 fb 2 q 8 8 4 3 4 5 2d 5 4 2 2h 2 3 6 16 2 2l i v 1d f e9 533 1t h3g 1w 19 3 7g 4 f b 1 l 1a h u 3 27 14 8 3 2u 3 29 l g 2 2 2 3 2 m u 1f f 1d 1r 5 4 0 2 1 c r b m q s 8 1a t 0 h 4 2 9 b 4 2 14 o 2 2 7 l m 4 0 4 1d 2 0 4 1 3 4 3 0 2 0 p 2 3 a 8 2 d 5 3 5 3 5 a 6 2 6 2 16 2 d 7 36 u 8mb d m 5 1c 6it a5 3 2x 13 6 d 4 6 0 2 9 2 c 2 4 2 0 2 1 2 1 2 2z y a2 j 1r 3 1h 15 b 39 4 2 3q 11 p 7 p c 2g 4 5 3 5 3 5 3 2 10 b 2 p 2 i 2 1 2 e 3 d z 3e 1y 1g 7g s 4 1c 1c v e t 6 11 b t 3 z 5 7 2 4 17 4d j z 5 z 5 13 9 1f d a 2 e 2 6 2 1 2 a 2 e 2 6 2 1 4 1f d 8m a l b 7 p 5 2 15 2 8 1y 5 3 0 2 17 2 1 4 0 3 m b m a u 1u i 2 1 b l b p 7 p 13 1j 7 1 1t 0 g 3 2 2 2 s 17 s 4 s 10 7 2 r s 1h b l b i e h 33 20 1k 1e e 1e e z 13 r a m 6z 15 7 1 h 5 1l s b 0 9 l 17 h 1b k s m d 1g 1m 1 3 0 e 18 x o r z u 0 3 0 9 y 4 0 d 1b f 3 m 0 2 0 10 h 2 o k 1 1s 6 2 0 2 3 2 e 2 9 8 1a 13 7 3 1 3 l 2 6 2 1 2 4 4 0 j 0 d 4 v 9 2 0 3 0 2 11 2 0 q 0 2 0 19 1g j 3 l 2 v 1b l 1 2 0 55 1a 16 3 11 1b l 0 1o 16 e 0 20 q 12 6 56 17 39 1r w 7 3 0 3 7 2 1 2 n g 0 2 0 2n 7 3 12 h 0 2 0 t 0 b 13 8 0 m 0 c 19 k 0 j 20 5k w w 8 2 10 i 0 1e t 35 6 2 1 2 11 m 0 q 5 2 1 2 v f 0 o 17 79 i g 0 2 c 2 x 3h 0 28 pl 2v 32 i 5f 219 2o g tr i 5 q 32y 6 g6 5a2 t 1cz fs 8 u i 26 i t j 1b h 3 w k 6 i c1 18 5w 1r x o 3 o 19 22 6 0 1v c 1t 1 2 0 f 4 a 5p1 16 v 2q 36 6pq 3 2 6 2 1 2 82 g 0 u 2 3 0 f 3 9 az 1s5 2y 6 c 4 8 8 9 4mf 2c 2 1y 2 1 3 0 3 1 3 3 2 b 2 0 2 6 2 1s 2 3 3 7 2 6 2 r 2 3 2 4 2 0 4 6 2 9f 3 o 2 o 2 u 2 o 2 u 2 o 2 u 2 o 2 u 2 o 2 7 1f9 u 7 5 7a 1p 43 18 b 6 h 0 8y t j 17 dh r 6d t 3 0 5s u 2 2 2 1 2 6 3 4 a 1 69 6 2 3 2 1 2 e 2 5g 1o 1v 8 0 xh 3 2 q 2 1 2 0 3 0 2 9 2 3 2 0 2 0 7 0 5 0 2 0 2 0 2 2 2 1 2 0 3 0 2 0 2 0 2 0 2 0 2 1 2 0 3 3 2 6 2 3 2 3 2 0 2 9 2 g 6 2 2 4 2 g 3et wyn x 3dp 3 4gd 3 5rk g h9 1wj f1 15v 3t6 6 6jt");
  }
  function initLargeIdContinueRanges() {
    return restoreRanges("53 0 g9 33 o 0 70 4 7e 18 2 0 2 1 2 1 2 0 21 a 1d u 7 0 2u 6 3 5 3 1 2 3 3 9 o 0 v q 2k a g 9 y 8 a 0 p 3 2 8 2 2 2 4 18 2 1o 8 17 n 2 w 1j 2 2 h 2 6 b 1 3 9 i 2 1l 0 2 6 3 1 3 2 a 0 b 1 3 9 f 0 3 2 1l 0 2 4 5 1 3 2 4 0 l b 4 0 c 2 1l 0 2 7 2 2 2 2 l 1 3 9 b 5 2 2 1l 0 2 6 3 1 3 2 8 2 b 1 3 9 j 0 1o 4 4 2 2 3 a 0 f 9 h 4 1k 0 2 6 2 2 2 3 8 1 c 1 3 9 i 2 1l 0 2 6 2 2 2 3 8 1 c 1 3 9 4 0 d 3 1k 1 2 6 2 2 2 3 a 0 b 1 3 9 i 2 1z 0 5 5 2 0 2 7 7 9 3 1 1q 0 3 6 d 7 2 9 2g 0 3 8 c 6 2 9 1r 1 7 9 c 0 2 0 2 0 5 1 1e j 2 1 6 a 2 z a 0 2t j 2 9 d 3 5 2 2 2 3 6 4 3 e b 2 e jk 2 a 8 pt 3 t 2 u 1 v 1 1t v a 0 3 9 y 2 2 a 40 0 3b b 5 b b 9 3l a 1p 4 1m 9 2 s 3 a 7 9 n d 2 u 3 b l 4 1c g c 9 i 8 d 2 v c 3 9 19 d 1d j 9 9 7 9 3b 2 2 k 5 0 7 0 3 2 5j 1r el 1 1e 1 k 0 3g c 5 0 4 b 2db 2 3y 0 2p v ff 5 2y 1 2p 0 n51 9 1y 0 5 9 x 1 29 1 7l 0 4 0 5 0 o 4 5 0 2c 1 1f h b 9 7 h e a t 7 q c 19 3 1c d g 9 c 0 b 9 1c d d 0 9 1 3 9 y 2 1f 0 2 2 3 1 6 1 2 0 16 4 6 1 6l 7 2 1 3 9 fmt 0 ki f h f 4 1 p 2 5d 9 12 0 12 0 ig 0 6b 0 46 4 86 9 120 2 2 1 6 3 15 2 5 0 4m 1 fy 3 9 9 7 9 w 4 8u 1 26 5 1z a 1e 3 3f 2 1i e w a 3 1 b 3 1a a 8 0 1a 9 7 2 11 d 2 9 6 1 19 0 d 2 1d d 9 3 2 b 2b b 7 0 3 0 4e b 6 9 7 3 1k 1 2 6 3 1 3 2 a 0 b 1 3 6 4 4 1w 8 2 0 3 0 2 3 2 4 2 0 f 1 2b h a 9 5 0 2a j d 9 5y 6 3 8 s 1 2b g g 9 2a c 9 9 7 j 1m e 5 9 6r e 4m 9 1z 5 2 1 3 3 2 0 2 1 d 9 3c 6 3 6 4 0 t 9 15 6 2 3 9 0 a a 1b f 5j 7 3t 9 1i 7 2 7 h 9 1l l 2 d 3f 5 4 0 2 1 2 6 2 0 9 9 1d 4 2 1 2 4 9 9 1j 9 7e 3 a 1 2 0 1d 6 4 4 e a 44m 0 7 e 8uh r 1t3 9 2f 9 13 4 1o 6 q 9 ev 9 d2 0 2 1i 8 3 2a 0 c 1 f58 1 382 9 ef 19 3 m f3 4 4 5 9 7 3 6 v 3 45 2 13e 1d e9 1i 5 1d 9 0 f 0 n 4 2 e 11t 6 2 g 3 6 2 1 2 4 2t 0 4h 6 a 9 9x 0 1q d dv d 6t 1 2 9 6h 0 3 0 8 1 6 0 d7 6 32 6 6 9 3o7 9 gvt3 6n");
  }
  function isInRange(cp, ranges) {
    let l = 0, r = ranges.length / 2 | 0, i = 0, min = 0, max = 0;
    while (l < r) {
      i = (l + r) / 2 | 0;
      min = ranges[2 * i];
      max = ranges[2 * i + 1];
      if (cp < min) {
        r = i;
      } else if (cp > max) {
        l = i + 1;
      } else {
        return true;
      }
    }
    return false;
  }
  function restoreRanges(data) {
    let last = 0;
    return data.split(" ").map((s) => last += parseInt(s, 36) | 0);
  }
  function isValidUnicodeProperty(version, name, value) {
    if (gcNameSet.has(name)) {
      return version >= 2018 && gcValueSets.es2018.has(value);
    }
    if (scNameSet.has(name)) {
      return version >= 2018 && scValueSets.es2018.has(value) || version >= 2019 && scValueSets.es2019.has(value) || version >= 2020 && scValueSets.es2020.has(value) || version >= 2021 && scValueSets.es2021.has(value) || version >= 2022 && scValueSets.es2022.has(value) || version >= 2023 && scValueSets.es2023.has(value);
    }
    return false;
  }
  function isValidLoneUnicodeProperty(version, value) {
    return version >= 2018 && binPropertySets.es2018.has(value) || version >= 2019 && binPropertySets.es2019.has(value) || version >= 2021 && binPropertySets.es2021.has(value);
  }
  function isValidLoneUnicodePropertyOfString(version, value) {
    return version >= 2024 && binPropertyOfStringsSets.es2024.has(value);
  }
  function isLatinLetter(code) {
    return code >= LATIN_CAPITAL_LETTER_A && code <= LATIN_CAPITAL_LETTER_Z || code >= LATIN_SMALL_LETTER_A && code <= LATIN_SMALL_LETTER_Z;
  }
  function isDecimalDigit(code) {
    return code >= DIGIT_ZERO && code <= DIGIT_NINE;
  }
  function isOctalDigit(code) {
    return code >= DIGIT_ZERO && code <= DIGIT_SEVEN;
  }
  function isHexDigit(code) {
    return code >= DIGIT_ZERO && code <= DIGIT_NINE || code >= LATIN_CAPITAL_LETTER_A && code <= LATIN_CAPITAL_LETTER_F || code >= LATIN_SMALL_LETTER_A && code <= LATIN_SMALL_LETTER_F;
  }
  function isLineTerminator(code) {
    return code === LINE_FEED || code === CARRIAGE_RETURN || code === LINE_SEPARATOR || code === PARAGRAPH_SEPARATOR;
  }
  function isValidUnicode(code) {
    return code >= MIN_CODE_POINT && code <= MAX_CODE_POINT;
  }
  function digitToInt(code) {
    if (code >= LATIN_SMALL_LETTER_A && code <= LATIN_SMALL_LETTER_F) {
      return code - LATIN_SMALL_LETTER_A + 10;
    }
    if (code >= LATIN_CAPITAL_LETTER_A && code <= LATIN_CAPITAL_LETTER_F) {
      return code - LATIN_CAPITAL_LETTER_A + 10;
    }
    return code - DIGIT_ZERO;
  }
  function isLeadSurrogate(code) {
    return code >= 55296 && code <= 56319;
  }
  function isTrailSurrogate(code) {
    return code >= 56320 && code <= 57343;
  }
  function combineSurrogatePair(lead, trail) {
    return (lead - 55296) * 1024 + (trail - 56320) + 65536;
  }
  function newRegExpSyntaxError(srcCtx, flags, index, message) {
    let source = "";
    if (srcCtx.kind === "literal") {
      const literal = srcCtx.source.slice(srcCtx.start, srcCtx.end);
      if (literal) {
        source = `: ${literal}`;
      }
    } else if (srcCtx.kind === "pattern") {
      const pattern = srcCtx.source.slice(srcCtx.start, srcCtx.end);
      const flagsText = `${flags.unicode ? "u" : ""}${flags.unicodeSets ? "v" : ""}`;
      source = `: /${pattern}/${flagsText}`;
    }
    return new RegExpSyntaxError(`Invalid regular expression${source}: ${message}`, index);
  }
  function isSyntaxCharacter(cp) {
    return SYNTAX_CHARACTER.has(cp);
  }
  function isClassSetReservedDoublePunctuatorCharacter(cp) {
    return CLASS_SET_RESERVED_DOUBLE_PUNCTUATOR_CHARACTER.has(cp);
  }
  function isClassSetSyntaxCharacter(cp) {
    return CLASS_SET_SYNTAX_CHARACTER.has(cp);
  }
  function isClassSetReservedPunctuator(cp) {
    return CLASS_SET_RESERVED_PUNCTUATOR.has(cp);
  }
  function isIdentifierStartChar(cp) {
    return isIdStart(cp) || cp === DOLLAR_SIGN || cp === LOW_LINE;
  }
  function isIdentifierPartChar(cp) {
    return isIdContinue(cp) || cp === DOLLAR_SIGN || cp === ZERO_WIDTH_NON_JOINER || cp === ZERO_WIDTH_JOINER;
  }
  function isUnicodePropertyNameCharacter(cp) {
    return isLatinLetter(cp) || cp === LOW_LINE;
  }
  function isUnicodePropertyValueCharacter(cp) {
    return isUnicodePropertyNameCharacter(cp) || isDecimalDigit(cp);
  }
  function isRegularExpressionModifier(ch) {
    return ch === LATIN_SMALL_LETTER_I || ch === LATIN_SMALL_LETTER_M || ch === LATIN_SMALL_LETTER_S;
  }
  function isClassSetOperand(node) {
    return node.type === "Character" || node.type === "CharacterSet" || node.type === "CharacterClass" || node.type === "ExpressionCharacterClass" || node.type === "ClassStringDisjunction";
  }
  function parseRegExpLiteral(source, options) {
    return new RegExpParser(options).parseLiteral(String(source));
  }
  function validateRegExpLiteral(source, options) {
    new RegExpValidator(options).validateLiteral(source);
  }
  function visitRegExpAST(node, handlers) {
    new RegExpVisitor(handlers).visit(node);
  }
  var ast, latestEcmaVersion, largeIdStartRanges, largeIdContinueRanges, DataSet, gcNameSet, scNameSet, gcValueSets, scValueSets, binPropertySets, binPropertyOfStringsSets, BACKSPACE, CHARACTER_TABULATION, LINE_FEED, LINE_TABULATION, FORM_FEED, CARRIAGE_RETURN, EXCLAMATION_MARK, NUMBER_SIGN, DOLLAR_SIGN, PERCENT_SIGN, AMPERSAND, LEFT_PARENTHESIS, RIGHT_PARENTHESIS, ASTERISK, PLUS_SIGN, COMMA, HYPHEN_MINUS, FULL_STOP, SOLIDUS, DIGIT_ZERO, DIGIT_ONE, DIGIT_SEVEN, DIGIT_NINE, COLON, SEMICOLON, LESS_THAN_SIGN, EQUALS_SIGN, GREATER_THAN_SIGN, QUESTION_MARK, COMMERCIAL_AT, LATIN_CAPITAL_LETTER_A, LATIN_CAPITAL_LETTER_B, LATIN_CAPITAL_LETTER_D, LATIN_CAPITAL_LETTER_F, LATIN_CAPITAL_LETTER_P, LATIN_CAPITAL_LETTER_S, LATIN_CAPITAL_LETTER_W, LATIN_CAPITAL_LETTER_Z, LOW_LINE, LATIN_SMALL_LETTER_A, LATIN_SMALL_LETTER_B, LATIN_SMALL_LETTER_C, LATIN_SMALL_LETTER_D, LATIN_SMALL_LETTER_F, LATIN_SMALL_LETTER_G, LATIN_SMALL_LETTER_I, LATIN_SMALL_LETTER_K, LATIN_SMALL_LETTER_M, LATIN_SMALL_LETTER_N, LATIN_SMALL_LETTER_P, LATIN_SMALL_LETTER_Q, LATIN_SMALL_LETTER_R, LATIN_SMALL_LETTER_S, LATIN_SMALL_LETTER_T, LATIN_SMALL_LETTER_U, LATIN_SMALL_LETTER_V, LATIN_SMALL_LETTER_W, LATIN_SMALL_LETTER_X, LATIN_SMALL_LETTER_Y, LATIN_SMALL_LETTER_Z, LEFT_SQUARE_BRACKET, REVERSE_SOLIDUS, RIGHT_SQUARE_BRACKET, CIRCUMFLEX_ACCENT, GRAVE_ACCENT, LEFT_CURLY_BRACKET, VERTICAL_LINE, RIGHT_CURLY_BRACKET, TILDE, ZERO_WIDTH_NON_JOINER, ZERO_WIDTH_JOINER, LINE_SEPARATOR, PARAGRAPH_SEPARATOR, MIN_CODE_POINT, MAX_CODE_POINT, GroupSpecifiersAsES2018, BranchID, GroupSpecifiersAsES2025, legacyImpl, unicodeImpl, Reader, RegExpSyntaxError, SYNTAX_CHARACTER, CLASS_SET_RESERVED_DOUBLE_PUNCTUATOR_CHARACTER, CLASS_SET_SYNTAX_CHARACTER, CLASS_SET_RESERVED_PUNCTUATOR, FLAG_PROP_TO_CODEPOINT, FLAG_CODEPOINT_TO_PROP, RegExpValidator, DUMMY_PATTERN, DUMMY_FLAGS, DUMMY_CAPTURING_GROUP, RegExpParserState, RegExpParser, RegExpVisitor;
  var init_regexpp = __esm({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/@eslint-community+regexpp@4.12.2/node_modules/@eslint-community/regexpp/index.mjs"() {
      ast = /* @__PURE__ */ Object.freeze({
        __proto__: null
      });
      latestEcmaVersion = 2025;
      largeIdStartRanges = void 0;
      largeIdContinueRanges = void 0;
      DataSet = class {
        constructor(raw2018, raw2019, raw2020, raw2021, raw2022, raw2023, raw2024, raw2025, raw2026) {
          this._raw2018 = raw2018;
          this._raw2019 = raw2019;
          this._raw2020 = raw2020;
          this._raw2021 = raw2021;
          this._raw2022 = raw2022;
          this._raw2023 = raw2023;
          this._raw2024 = raw2024;
          this._raw2025 = raw2025;
          this._raw2026 = raw2026;
        }
        get es2018() {
          var _a;
          return (_a = this._set2018) !== null && _a !== void 0 ? _a : this._set2018 = new Set(this._raw2018.split(" "));
        }
        get es2019() {
          var _a;
          return (_a = this._set2019) !== null && _a !== void 0 ? _a : this._set2019 = new Set(this._raw2019.split(" "));
        }
        get es2020() {
          var _a;
          return (_a = this._set2020) !== null && _a !== void 0 ? _a : this._set2020 = new Set(this._raw2020.split(" "));
        }
        get es2021() {
          var _a;
          return (_a = this._set2021) !== null && _a !== void 0 ? _a : this._set2021 = new Set(this._raw2021.split(" "));
        }
        get es2022() {
          var _a;
          return (_a = this._set2022) !== null && _a !== void 0 ? _a : this._set2022 = new Set(this._raw2022.split(" "));
        }
        get es2023() {
          var _a;
          return (_a = this._set2023) !== null && _a !== void 0 ? _a : this._set2023 = new Set(this._raw2023.split(" "));
        }
        get es2024() {
          var _a;
          return (_a = this._set2024) !== null && _a !== void 0 ? _a : this._set2024 = new Set(this._raw2024.split(" "));
        }
        get es2025() {
          var _a;
          return (_a = this._set2025) !== null && _a !== void 0 ? _a : this._set2025 = new Set(this._raw2025.split(" "));
        }
        get es2026() {
          var _a;
          return (_a = this._set2026) !== null && _a !== void 0 ? _a : this._set2026 = new Set(this._raw2026.split(" "));
        }
      };
      gcNameSet = /* @__PURE__ */ new Set(["General_Category", "gc"]);
      scNameSet = /* @__PURE__ */ new Set(["Script", "Script_Extensions", "sc", "scx"]);
      gcValueSets = new DataSet("C Cased_Letter Cc Cf Close_Punctuation Cn Co Combining_Mark Connector_Punctuation Control Cs Currency_Symbol Dash_Punctuation Decimal_Number Enclosing_Mark Final_Punctuation Format Initial_Punctuation L LC Letter Letter_Number Line_Separator Ll Lm Lo Lowercase_Letter Lt Lu M Mark Math_Symbol Mc Me Mn Modifier_Letter Modifier_Symbol N Nd Nl No Nonspacing_Mark Number Open_Punctuation Other Other_Letter Other_Number Other_Punctuation Other_Symbol P Paragraph_Separator Pc Pd Pe Pf Pi Po Private_Use Ps Punctuation S Sc Separator Sk Sm So Space_Separator Spacing_Mark Surrogate Symbol Titlecase_Letter Unassigned Uppercase_Letter Z Zl Zp Zs cntrl digit punct", "", "", "", "", "", "", "", "");
      scValueSets = new DataSet("Adlam Adlm Aghb Ahom Anatolian_Hieroglyphs Arab Arabic Armenian Armi Armn Avestan Avst Bali Balinese Bamu Bamum Bass Bassa_Vah Batak Batk Beng Bengali Bhaiksuki Bhks Bopo Bopomofo Brah Brahmi Brai Braille Bugi Buginese Buhd Buhid Cakm Canadian_Aboriginal Cans Cari Carian Caucasian_Albanian Chakma Cham Cher Cherokee Common Copt Coptic Cprt Cuneiform Cypriot Cyrillic Cyrl Deseret Deva Devanagari Dsrt Dupl Duployan Egyp Egyptian_Hieroglyphs Elba Elbasan Ethi Ethiopic Geor Georgian Glag Glagolitic Gonm Goth Gothic Gran Grantha Greek Grek Gujarati Gujr Gurmukhi Guru Han Hang Hangul Hani Hano Hanunoo Hatr Hatran Hebr Hebrew Hira Hiragana Hluw Hmng Hung Imperial_Aramaic Inherited Inscriptional_Pahlavi Inscriptional_Parthian Ital Java Javanese Kaithi Kali Kana Kannada Katakana Kayah_Li Khar Kharoshthi Khmer Khmr Khoj Khojki Khudawadi Knda Kthi Lana Lao Laoo Latin Latn Lepc Lepcha Limb Limbu Lina Linb Linear_A Linear_B Lisu Lyci Lycian Lydi Lydian Mahajani Mahj Malayalam Mand Mandaic Mani Manichaean Marc Marchen Masaram_Gondi Meetei_Mayek Mend Mende_Kikakui Merc Mero Meroitic_Cursive Meroitic_Hieroglyphs Miao Mlym Modi Mong Mongolian Mro Mroo Mtei Mult Multani Myanmar Mymr Nabataean Narb Nbat New_Tai_Lue Newa Nko Nkoo Nshu Nushu Ogam Ogham Ol_Chiki Olck Old_Hungarian Old_Italic Old_North_Arabian Old_Permic Old_Persian Old_South_Arabian Old_Turkic Oriya Orkh Orya Osage Osge Osma Osmanya Pahawh_Hmong Palm Palmyrene Pau_Cin_Hau Pauc Perm Phag Phags_Pa Phli Phlp Phnx Phoenician Plrd Prti Psalter_Pahlavi Qaac Qaai Rejang Rjng Runic Runr Samaritan Samr Sarb Saur Saurashtra Sgnw Sharada Shavian Shaw Shrd Sidd Siddham SignWriting Sind Sinh Sinhala Sora Sora_Sompeng Soyo Soyombo Sund Sundanese Sylo Syloti_Nagri Syrc Syriac Tagalog Tagb Tagbanwa Tai_Le Tai_Tham Tai_Viet Takr Takri Tale Talu Tamil Taml Tang Tangut Tavt Telu Telugu Tfng Tglg Thaa Thaana Thai Tibetan Tibt Tifinagh Tirh Tirhuta Ugar Ugaritic Vai Vaii Wara Warang_Citi Xpeo Xsux Yi Yiii Zanabazar_Square Zanb Zinh Zyyy", "Dogr Dogra Gong Gunjala_Gondi Hanifi_Rohingya Maka Makasar Medefaidrin Medf Old_Sogdian Rohg Sogd Sogdian Sogo", "Elym Elymaic Hmnp Nand Nandinagari Nyiakeng_Puachue_Hmong Wancho Wcho", "Chorasmian Chrs Diak Dives_Akuru Khitan_Small_Script Kits Yezi Yezidi", "Cpmn Cypro_Minoan Old_Uyghur Ougr Tangsa Tnsa Toto Vith Vithkuqi", "Berf Beria_Erfe Gara Garay Gukh Gurung_Khema Hrkt Katakana_Or_Hiragana Kawi Kirat_Rai Krai Nag_Mundari Nagm Ol_Onal Onao Sidetic Sidt Sunu Sunuwar Tai_Yo Tayo Todhri Todr Tolong_Siki Tols Tulu_Tigalari Tutg Unknown Zzzz", "", "", "");
      binPropertySets = new DataSet("AHex ASCII ASCII_Hex_Digit Alpha Alphabetic Any Assigned Bidi_C Bidi_Control Bidi_M Bidi_Mirrored CI CWCF CWCM CWKCF CWL CWT CWU Case_Ignorable Cased Changes_When_Casefolded Changes_When_Casemapped Changes_When_Lowercased Changes_When_NFKC_Casefolded Changes_When_Titlecased Changes_When_Uppercased DI Dash Default_Ignorable_Code_Point Dep Deprecated Dia Diacritic Emoji Emoji_Component Emoji_Modifier Emoji_Modifier_Base Emoji_Presentation Ext Extender Gr_Base Gr_Ext Grapheme_Base Grapheme_Extend Hex Hex_Digit IDC IDS IDSB IDST IDS_Binary_Operator IDS_Trinary_Operator ID_Continue ID_Start Ideo Ideographic Join_C Join_Control LOE Logical_Order_Exception Lower Lowercase Math NChar Noncharacter_Code_Point Pat_Syn Pat_WS Pattern_Syntax Pattern_White_Space QMark Quotation_Mark RI Radical Regional_Indicator SD STerm Sentence_Terminal Soft_Dotted Term Terminal_Punctuation UIdeo Unified_Ideograph Upper Uppercase VS Variation_Selector White_Space XIDC XIDS XID_Continue XID_Start space", "Extended_Pictographic", "", "EBase EComp EMod EPres ExtPict", "", "", "", "", "");
      binPropertyOfStringsSets = new DataSet("", "", "", "", "", "", "Basic_Emoji Emoji_Keycap_Sequence RGI_Emoji RGI_Emoji_Flag_Sequence RGI_Emoji_Modifier_Sequence RGI_Emoji_Tag_Sequence RGI_Emoji_ZWJ_Sequence", "", "");
      BACKSPACE = 8;
      CHARACTER_TABULATION = 9;
      LINE_FEED = 10;
      LINE_TABULATION = 11;
      FORM_FEED = 12;
      CARRIAGE_RETURN = 13;
      EXCLAMATION_MARK = 33;
      NUMBER_SIGN = 35;
      DOLLAR_SIGN = 36;
      PERCENT_SIGN = 37;
      AMPERSAND = 38;
      LEFT_PARENTHESIS = 40;
      RIGHT_PARENTHESIS = 41;
      ASTERISK = 42;
      PLUS_SIGN = 43;
      COMMA = 44;
      HYPHEN_MINUS = 45;
      FULL_STOP = 46;
      SOLIDUS = 47;
      DIGIT_ZERO = 48;
      DIGIT_ONE = 49;
      DIGIT_SEVEN = 55;
      DIGIT_NINE = 57;
      COLON = 58;
      SEMICOLON = 59;
      LESS_THAN_SIGN = 60;
      EQUALS_SIGN = 61;
      GREATER_THAN_SIGN = 62;
      QUESTION_MARK = 63;
      COMMERCIAL_AT = 64;
      LATIN_CAPITAL_LETTER_A = 65;
      LATIN_CAPITAL_LETTER_B = 66;
      LATIN_CAPITAL_LETTER_D = 68;
      LATIN_CAPITAL_LETTER_F = 70;
      LATIN_CAPITAL_LETTER_P = 80;
      LATIN_CAPITAL_LETTER_S = 83;
      LATIN_CAPITAL_LETTER_W = 87;
      LATIN_CAPITAL_LETTER_Z = 90;
      LOW_LINE = 95;
      LATIN_SMALL_LETTER_A = 97;
      LATIN_SMALL_LETTER_B = 98;
      LATIN_SMALL_LETTER_C = 99;
      LATIN_SMALL_LETTER_D = 100;
      LATIN_SMALL_LETTER_F = 102;
      LATIN_SMALL_LETTER_G = 103;
      LATIN_SMALL_LETTER_I = 105;
      LATIN_SMALL_LETTER_K = 107;
      LATIN_SMALL_LETTER_M = 109;
      LATIN_SMALL_LETTER_N = 110;
      LATIN_SMALL_LETTER_P = 112;
      LATIN_SMALL_LETTER_Q = 113;
      LATIN_SMALL_LETTER_R = 114;
      LATIN_SMALL_LETTER_S = 115;
      LATIN_SMALL_LETTER_T = 116;
      LATIN_SMALL_LETTER_U = 117;
      LATIN_SMALL_LETTER_V = 118;
      LATIN_SMALL_LETTER_W = 119;
      LATIN_SMALL_LETTER_X = 120;
      LATIN_SMALL_LETTER_Y = 121;
      LATIN_SMALL_LETTER_Z = 122;
      LEFT_SQUARE_BRACKET = 91;
      REVERSE_SOLIDUS = 92;
      RIGHT_SQUARE_BRACKET = 93;
      CIRCUMFLEX_ACCENT = 94;
      GRAVE_ACCENT = 96;
      LEFT_CURLY_BRACKET = 123;
      VERTICAL_LINE = 124;
      RIGHT_CURLY_BRACKET = 125;
      TILDE = 126;
      ZERO_WIDTH_NON_JOINER = 8204;
      ZERO_WIDTH_JOINER = 8205;
      LINE_SEPARATOR = 8232;
      PARAGRAPH_SEPARATOR = 8233;
      MIN_CODE_POINT = 0;
      MAX_CODE_POINT = 1114111;
      GroupSpecifiersAsES2018 = class {
        constructor() {
          this.groupName = /* @__PURE__ */ new Set();
        }
        clear() {
          this.groupName.clear();
        }
        isEmpty() {
          return !this.groupName.size;
        }
        hasInPattern(name) {
          return this.groupName.has(name);
        }
        hasInScope(name) {
          return this.hasInPattern(name);
        }
        addToScope(name) {
          this.groupName.add(name);
        }
        enterDisjunction() {
        }
        enterAlternative() {
        }
        leaveDisjunction() {
        }
      };
      BranchID = class _BranchID {
        constructor(parent, base) {
          this.parent = parent;
          this.base = base !== null && base !== void 0 ? base : this;
        }
        separatedFrom(other) {
          var _a, _b;
          if (this.base === other.base && this !== other) {
            return true;
          }
          if (other.parent && this.separatedFrom(other.parent)) {
            return true;
          }
          return (_b = (_a = this.parent) === null || _a === void 0 ? void 0 : _a.separatedFrom(other)) !== null && _b !== void 0 ? _b : false;
        }
        child() {
          return new _BranchID(this, null);
        }
        sibling() {
          return new _BranchID(this.parent, this.base);
        }
      };
      GroupSpecifiersAsES2025 = class {
        constructor() {
          this.branchID = new BranchID(null, null);
          this.groupNames = /* @__PURE__ */ new Map();
        }
        clear() {
          this.branchID = new BranchID(null, null);
          this.groupNames.clear();
        }
        isEmpty() {
          return !this.groupNames.size;
        }
        enterDisjunction() {
          this.branchID = this.branchID.child();
        }
        enterAlternative(index) {
          if (index === 0) {
            return;
          }
          this.branchID = this.branchID.sibling();
        }
        leaveDisjunction() {
          this.branchID = this.branchID.parent;
        }
        hasInPattern(name) {
          return this.groupNames.has(name);
        }
        hasInScope(name) {
          const branches = this.groupNames.get(name);
          if (!branches) {
            return false;
          }
          for (const branch of branches) {
            if (!branch.separatedFrom(this.branchID)) {
              return true;
            }
          }
          return false;
        }
        addToScope(name) {
          const branches = this.groupNames.get(name);
          if (branches) {
            branches.push(this.branchID);
            return;
          }
          this.groupNames.set(name, [this.branchID]);
        }
      };
      legacyImpl = {
        at(s, end, i) {
          return i < end ? s.charCodeAt(i) : -1;
        },
        width(c) {
          return 1;
        }
      };
      unicodeImpl = {
        at(s, end, i) {
          return i < end ? s.codePointAt(i) : -1;
        },
        width(c) {
          return c > 65535 ? 2 : 1;
        }
      };
      Reader = class {
        constructor() {
          this._impl = legacyImpl;
          this._s = "";
          this._i = 0;
          this._end = 0;
          this._cp1 = -1;
          this._w1 = 1;
          this._cp2 = -1;
          this._w2 = 1;
          this._cp3 = -1;
          this._w3 = 1;
          this._cp4 = -1;
        }
        get source() {
          return this._s;
        }
        get index() {
          return this._i;
        }
        get currentCodePoint() {
          return this._cp1;
        }
        get nextCodePoint() {
          return this._cp2;
        }
        get nextCodePoint2() {
          return this._cp3;
        }
        get nextCodePoint3() {
          return this._cp4;
        }
        reset(source, start, end, uFlag) {
          this._impl = uFlag ? unicodeImpl : legacyImpl;
          this._s = source;
          this._end = end;
          this.rewind(start);
        }
        rewind(index) {
          const impl = this._impl;
          this._i = index;
          this._cp1 = impl.at(this._s, this._end, index);
          this._w1 = impl.width(this._cp1);
          this._cp2 = impl.at(this._s, this._end, index + this._w1);
          this._w2 = impl.width(this._cp2);
          this._cp3 = impl.at(this._s, this._end, index + this._w1 + this._w2);
          this._w3 = impl.width(this._cp3);
          this._cp4 = impl.at(this._s, this._end, index + this._w1 + this._w2 + this._w3);
        }
        advance() {
          if (this._cp1 !== -1) {
            const impl = this._impl;
            this._i += this._w1;
            this._cp1 = this._cp2;
            this._w1 = this._w2;
            this._cp2 = this._cp3;
            this._w2 = impl.width(this._cp2);
            this._cp3 = this._cp4;
            this._w3 = impl.width(this._cp3);
            this._cp4 = impl.at(this._s, this._end, this._i + this._w1 + this._w2 + this._w3);
          }
        }
        eat(cp) {
          if (this._cp1 === cp) {
            this.advance();
            return true;
          }
          return false;
        }
        eat2(cp1, cp2) {
          if (this._cp1 === cp1 && this._cp2 === cp2) {
            this.advance();
            this.advance();
            return true;
          }
          return false;
        }
        eat3(cp1, cp2, cp3) {
          if (this._cp1 === cp1 && this._cp2 === cp2 && this._cp3 === cp3) {
            this.advance();
            this.advance();
            this.advance();
            return true;
          }
          return false;
        }
      };
      RegExpSyntaxError = class extends SyntaxError {
        constructor(message, index) {
          super(message);
          this.index = index;
        }
      };
      SYNTAX_CHARACTER = /* @__PURE__ */ new Set([
        CIRCUMFLEX_ACCENT,
        DOLLAR_SIGN,
        REVERSE_SOLIDUS,
        FULL_STOP,
        ASTERISK,
        PLUS_SIGN,
        QUESTION_MARK,
        LEFT_PARENTHESIS,
        RIGHT_PARENTHESIS,
        LEFT_SQUARE_BRACKET,
        RIGHT_SQUARE_BRACKET,
        LEFT_CURLY_BRACKET,
        RIGHT_CURLY_BRACKET,
        VERTICAL_LINE
      ]);
      CLASS_SET_RESERVED_DOUBLE_PUNCTUATOR_CHARACTER = /* @__PURE__ */ new Set([
        AMPERSAND,
        EXCLAMATION_MARK,
        NUMBER_SIGN,
        DOLLAR_SIGN,
        PERCENT_SIGN,
        ASTERISK,
        PLUS_SIGN,
        COMMA,
        FULL_STOP,
        COLON,
        SEMICOLON,
        LESS_THAN_SIGN,
        EQUALS_SIGN,
        GREATER_THAN_SIGN,
        QUESTION_MARK,
        COMMERCIAL_AT,
        CIRCUMFLEX_ACCENT,
        GRAVE_ACCENT,
        TILDE
      ]);
      CLASS_SET_SYNTAX_CHARACTER = /* @__PURE__ */ new Set([
        LEFT_PARENTHESIS,
        RIGHT_PARENTHESIS,
        LEFT_SQUARE_BRACKET,
        RIGHT_SQUARE_BRACKET,
        LEFT_CURLY_BRACKET,
        RIGHT_CURLY_BRACKET,
        SOLIDUS,
        HYPHEN_MINUS,
        REVERSE_SOLIDUS,
        VERTICAL_LINE
      ]);
      CLASS_SET_RESERVED_PUNCTUATOR = /* @__PURE__ */ new Set([
        AMPERSAND,
        HYPHEN_MINUS,
        EXCLAMATION_MARK,
        NUMBER_SIGN,
        PERCENT_SIGN,
        COMMA,
        COLON,
        SEMICOLON,
        LESS_THAN_SIGN,
        EQUALS_SIGN,
        GREATER_THAN_SIGN,
        COMMERCIAL_AT,
        GRAVE_ACCENT,
        TILDE
      ]);
      FLAG_PROP_TO_CODEPOINT = {
        global: LATIN_SMALL_LETTER_G,
        ignoreCase: LATIN_SMALL_LETTER_I,
        multiline: LATIN_SMALL_LETTER_M,
        unicode: LATIN_SMALL_LETTER_U,
        sticky: LATIN_SMALL_LETTER_Y,
        dotAll: LATIN_SMALL_LETTER_S,
        hasIndices: LATIN_SMALL_LETTER_D,
        unicodeSets: LATIN_SMALL_LETTER_V
      };
      FLAG_CODEPOINT_TO_PROP = Object.fromEntries(Object.entries(FLAG_PROP_TO_CODEPOINT).map(([k, v]) => [v, k]));
      RegExpValidator = class {
        constructor(options) {
          this._reader = new Reader();
          this._unicodeMode = false;
          this._unicodeSetsMode = false;
          this._nFlag = false;
          this._lastIntValue = 0;
          this._lastRange = {
            min: 0,
            max: Number.POSITIVE_INFINITY
          };
          this._lastStrValue = "";
          this._lastAssertionIsQuantifiable = false;
          this._numCapturingParens = 0;
          this._backreferenceNames = /* @__PURE__ */ new Set();
          this._srcCtx = null;
          this._options = options !== null && options !== void 0 ? options : {};
          this._groupSpecifiers = this.ecmaVersion >= 2025 ? new GroupSpecifiersAsES2025() : new GroupSpecifiersAsES2018();
        }
        validateLiteral(source, start = 0, end = source.length) {
          this._srcCtx = { source, start, end, kind: "literal" };
          this._unicodeSetsMode = this._unicodeMode = this._nFlag = false;
          this.reset(source, start, end);
          this.onLiteralEnter(start);
          if (this.eat(SOLIDUS) && this.eatRegExpBody() && this.eat(SOLIDUS)) {
            const flagStart = this.index;
            const unicode = source.includes("u", flagStart);
            const unicodeSets = source.includes("v", flagStart);
            this.validateFlagsInternal(source, flagStart, end);
            this.validatePatternInternal(source, start + 1, flagStart - 1, {
              unicode,
              unicodeSets
            });
          } else if (start >= end) {
            this.raise("Empty");
          } else {
            const c = String.fromCodePoint(this.currentCodePoint);
            this.raise(`Unexpected character '${c}'`);
          }
          this.onLiteralLeave(start, end);
        }
        validateFlags(source, start = 0, end = source.length) {
          this._srcCtx = { source, start, end, kind: "flags" };
          this.validateFlagsInternal(source, start, end);
        }
        validatePattern(source, start = 0, end = source.length, uFlagOrFlags = void 0) {
          this._srcCtx = { source, start, end, kind: "pattern" };
          this.validatePatternInternal(source, start, end, uFlagOrFlags);
        }
        validatePatternInternal(source, start = 0, end = source.length, uFlagOrFlags = void 0) {
          const mode = this._parseFlagsOptionToMode(uFlagOrFlags, end);
          this._unicodeMode = mode.unicodeMode;
          this._nFlag = mode.nFlag;
          this._unicodeSetsMode = mode.unicodeSetsMode;
          this.reset(source, start, end);
          this.consumePattern();
          if (!this._nFlag && this.ecmaVersion >= 2018 && !this._groupSpecifiers.isEmpty()) {
            this._nFlag = true;
            this.rewind(start);
            this.consumePattern();
          }
        }
        validateFlagsInternal(source, start, end) {
          const flags = this.parseFlags(source, start, end);
          this.onRegExpFlags(start, end, flags);
        }
        _parseFlagsOptionToMode(uFlagOrFlags, sourceEnd) {
          let unicode = false;
          let unicodeSets = false;
          if (uFlagOrFlags && this.ecmaVersion >= 2015) {
            if (typeof uFlagOrFlags === "object") {
              unicode = Boolean(uFlagOrFlags.unicode);
              if (this.ecmaVersion >= 2024) {
                unicodeSets = Boolean(uFlagOrFlags.unicodeSets);
              }
            } else {
              unicode = uFlagOrFlags;
            }
          }
          if (unicode && unicodeSets) {
            this.raise("Invalid regular expression flags", {
              index: sourceEnd + 1,
              unicode,
              unicodeSets
            });
          }
          const unicodeMode = unicode || unicodeSets;
          const nFlag = unicode && this.ecmaVersion >= 2018 || unicodeSets || Boolean(this._options.strict && this.ecmaVersion >= 2023);
          const unicodeSetsMode = unicodeSets;
          return { unicodeMode, nFlag, unicodeSetsMode };
        }
        get strict() {
          return Boolean(this._options.strict) || this._unicodeMode;
        }
        get ecmaVersion() {
          var _a;
          return (_a = this._options.ecmaVersion) !== null && _a !== void 0 ? _a : latestEcmaVersion;
        }
        onLiteralEnter(start) {
          if (this._options.onLiteralEnter) {
            this._options.onLiteralEnter(start);
          }
        }
        onLiteralLeave(start, end) {
          if (this._options.onLiteralLeave) {
            this._options.onLiteralLeave(start, end);
          }
        }
        onRegExpFlags(start, end, flags) {
          if (this._options.onRegExpFlags) {
            this._options.onRegExpFlags(start, end, flags);
          }
          if (this._options.onFlags) {
            this._options.onFlags(start, end, flags.global, flags.ignoreCase, flags.multiline, flags.unicode, flags.sticky, flags.dotAll, flags.hasIndices);
          }
        }
        onPatternEnter(start) {
          if (this._options.onPatternEnter) {
            this._options.onPatternEnter(start);
          }
        }
        onPatternLeave(start, end) {
          if (this._options.onPatternLeave) {
            this._options.onPatternLeave(start, end);
          }
        }
        onDisjunctionEnter(start) {
          if (this._options.onDisjunctionEnter) {
            this._options.onDisjunctionEnter(start);
          }
        }
        onDisjunctionLeave(start, end) {
          if (this._options.onDisjunctionLeave) {
            this._options.onDisjunctionLeave(start, end);
          }
        }
        onAlternativeEnter(start, index) {
          if (this._options.onAlternativeEnter) {
            this._options.onAlternativeEnter(start, index);
          }
        }
        onAlternativeLeave(start, end, index) {
          if (this._options.onAlternativeLeave) {
            this._options.onAlternativeLeave(start, end, index);
          }
        }
        onGroupEnter(start) {
          if (this._options.onGroupEnter) {
            this._options.onGroupEnter(start);
          }
        }
        onGroupLeave(start, end) {
          if (this._options.onGroupLeave) {
            this._options.onGroupLeave(start, end);
          }
        }
        onModifiersEnter(start) {
          if (this._options.onModifiersEnter) {
            this._options.onModifiersEnter(start);
          }
        }
        onModifiersLeave(start, end) {
          if (this._options.onModifiersLeave) {
            this._options.onModifiersLeave(start, end);
          }
        }
        onAddModifiers(start, end, flags) {
          if (this._options.onAddModifiers) {
            this._options.onAddModifiers(start, end, flags);
          }
        }
        onRemoveModifiers(start, end, flags) {
          if (this._options.onRemoveModifiers) {
            this._options.onRemoveModifiers(start, end, flags);
          }
        }
        onCapturingGroupEnter(start, name) {
          if (this._options.onCapturingGroupEnter) {
            this._options.onCapturingGroupEnter(start, name);
          }
        }
        onCapturingGroupLeave(start, end, name) {
          if (this._options.onCapturingGroupLeave) {
            this._options.onCapturingGroupLeave(start, end, name);
          }
        }
        onQuantifier(start, end, min, max, greedy) {
          if (this._options.onQuantifier) {
            this._options.onQuantifier(start, end, min, max, greedy);
          }
        }
        onLookaroundAssertionEnter(start, kind, negate) {
          if (this._options.onLookaroundAssertionEnter) {
            this._options.onLookaroundAssertionEnter(start, kind, negate);
          }
        }
        onLookaroundAssertionLeave(start, end, kind, negate) {
          if (this._options.onLookaroundAssertionLeave) {
            this._options.onLookaroundAssertionLeave(start, end, kind, negate);
          }
        }
        onEdgeAssertion(start, end, kind) {
          if (this._options.onEdgeAssertion) {
            this._options.onEdgeAssertion(start, end, kind);
          }
        }
        onWordBoundaryAssertion(start, end, kind, negate) {
          if (this._options.onWordBoundaryAssertion) {
            this._options.onWordBoundaryAssertion(start, end, kind, negate);
          }
        }
        onAnyCharacterSet(start, end, kind) {
          if (this._options.onAnyCharacterSet) {
            this._options.onAnyCharacterSet(start, end, kind);
          }
        }
        onEscapeCharacterSet(start, end, kind, negate) {
          if (this._options.onEscapeCharacterSet) {
            this._options.onEscapeCharacterSet(start, end, kind, negate);
          }
        }
        onUnicodePropertyCharacterSet(start, end, kind, key, value, negate, strings) {
          if (this._options.onUnicodePropertyCharacterSet) {
            this._options.onUnicodePropertyCharacterSet(start, end, kind, key, value, negate, strings);
          }
        }
        onCharacter(start, end, value) {
          if (this._options.onCharacter) {
            this._options.onCharacter(start, end, value);
          }
        }
        onBackreference(start, end, ref) {
          if (this._options.onBackreference) {
            this._options.onBackreference(start, end, ref);
          }
        }
        onCharacterClassEnter(start, negate, unicodeSets) {
          if (this._options.onCharacterClassEnter) {
            this._options.onCharacterClassEnter(start, negate, unicodeSets);
          }
        }
        onCharacterClassLeave(start, end, negate) {
          if (this._options.onCharacterClassLeave) {
            this._options.onCharacterClassLeave(start, end, negate);
          }
        }
        onCharacterClassRange(start, end, min, max) {
          if (this._options.onCharacterClassRange) {
            this._options.onCharacterClassRange(start, end, min, max);
          }
        }
        onClassIntersection(start, end) {
          if (this._options.onClassIntersection) {
            this._options.onClassIntersection(start, end);
          }
        }
        onClassSubtraction(start, end) {
          if (this._options.onClassSubtraction) {
            this._options.onClassSubtraction(start, end);
          }
        }
        onClassStringDisjunctionEnter(start) {
          if (this._options.onClassStringDisjunctionEnter) {
            this._options.onClassStringDisjunctionEnter(start);
          }
        }
        onClassStringDisjunctionLeave(start, end) {
          if (this._options.onClassStringDisjunctionLeave) {
            this._options.onClassStringDisjunctionLeave(start, end);
          }
        }
        onStringAlternativeEnter(start, index) {
          if (this._options.onStringAlternativeEnter) {
            this._options.onStringAlternativeEnter(start, index);
          }
        }
        onStringAlternativeLeave(start, end, index) {
          if (this._options.onStringAlternativeLeave) {
            this._options.onStringAlternativeLeave(start, end, index);
          }
        }
        get index() {
          return this._reader.index;
        }
        get currentCodePoint() {
          return this._reader.currentCodePoint;
        }
        get nextCodePoint() {
          return this._reader.nextCodePoint;
        }
        get nextCodePoint2() {
          return this._reader.nextCodePoint2;
        }
        get nextCodePoint3() {
          return this._reader.nextCodePoint3;
        }
        reset(source, start, end) {
          this._reader.reset(source, start, end, this._unicodeMode);
        }
        rewind(index) {
          this._reader.rewind(index);
        }
        advance() {
          this._reader.advance();
        }
        eat(cp) {
          return this._reader.eat(cp);
        }
        eat2(cp1, cp2) {
          return this._reader.eat2(cp1, cp2);
        }
        eat3(cp1, cp2, cp3) {
          return this._reader.eat3(cp1, cp2, cp3);
        }
        raise(message, context) {
          var _a, _b, _c;
          throw newRegExpSyntaxError(this._srcCtx, {
            unicode: (_a = context === null || context === void 0 ? void 0 : context.unicode) !== null && _a !== void 0 ? _a : this._unicodeMode && !this._unicodeSetsMode,
            unicodeSets: (_b = context === null || context === void 0 ? void 0 : context.unicodeSets) !== null && _b !== void 0 ? _b : this._unicodeSetsMode
          }, (_c = context === null || context === void 0 ? void 0 : context.index) !== null && _c !== void 0 ? _c : this.index, message);
        }
        eatRegExpBody() {
          const start = this.index;
          let inClass = false;
          let escaped = false;
          for (; ; ) {
            const cp = this.currentCodePoint;
            if (cp === -1 || isLineTerminator(cp)) {
              const kind = inClass ? "character class" : "regular expression";
              this.raise(`Unterminated ${kind}`);
            }
            if (escaped) {
              escaped = false;
            } else if (cp === REVERSE_SOLIDUS) {
              escaped = true;
            } else if (cp === LEFT_SQUARE_BRACKET) {
              inClass = true;
            } else if (cp === RIGHT_SQUARE_BRACKET) {
              inClass = false;
            } else if (cp === SOLIDUS && !inClass || cp === ASTERISK && this.index === start) {
              break;
            }
            this.advance();
          }
          return this.index !== start;
        }
        consumePattern() {
          const start = this.index;
          this._numCapturingParens = this.countCapturingParens();
          this._groupSpecifiers.clear();
          this._backreferenceNames.clear();
          this.onPatternEnter(start);
          this.consumeDisjunction();
          const cp = this.currentCodePoint;
          if (this.currentCodePoint !== -1) {
            if (cp === RIGHT_PARENTHESIS) {
              this.raise("Unmatched ')'");
            }
            if (cp === REVERSE_SOLIDUS) {
              this.raise("\\ at end of pattern");
            }
            if (cp === RIGHT_SQUARE_BRACKET || cp === RIGHT_CURLY_BRACKET) {
              this.raise("Lone quantifier brackets");
            }
            const c = String.fromCodePoint(cp);
            this.raise(`Unexpected character '${c}'`);
          }
          for (const name of this._backreferenceNames) {
            if (!this._groupSpecifiers.hasInPattern(name)) {
              this.raise("Invalid named capture referenced");
            }
          }
          this.onPatternLeave(start, this.index);
        }
        countCapturingParens() {
          const start = this.index;
          let inClass = false;
          let escaped = false;
          let count = 0;
          let cp = 0;
          while ((cp = this.currentCodePoint) !== -1) {
            if (escaped) {
              escaped = false;
            } else if (cp === REVERSE_SOLIDUS) {
              escaped = true;
            } else if (cp === LEFT_SQUARE_BRACKET) {
              inClass = true;
            } else if (cp === RIGHT_SQUARE_BRACKET) {
              inClass = false;
            } else if (cp === LEFT_PARENTHESIS && !inClass && (this.nextCodePoint !== QUESTION_MARK || this.nextCodePoint2 === LESS_THAN_SIGN && this.nextCodePoint3 !== EQUALS_SIGN && this.nextCodePoint3 !== EXCLAMATION_MARK)) {
              count += 1;
            }
            this.advance();
          }
          this.rewind(start);
          return count;
        }
        consumeDisjunction() {
          const start = this.index;
          let i = 0;
          this._groupSpecifiers.enterDisjunction();
          this.onDisjunctionEnter(start);
          do {
            this.consumeAlternative(i++);
          } while (this.eat(VERTICAL_LINE));
          if (this.consumeQuantifier(true)) {
            this.raise("Nothing to repeat");
          }
          if (this.eat(LEFT_CURLY_BRACKET)) {
            this.raise("Lone quantifier brackets");
          }
          this.onDisjunctionLeave(start, this.index);
          this._groupSpecifiers.leaveDisjunction();
        }
        consumeAlternative(i) {
          const start = this.index;
          this._groupSpecifiers.enterAlternative(i);
          this.onAlternativeEnter(start, i);
          while (this.currentCodePoint !== -1 && this.consumeTerm()) {
          }
          this.onAlternativeLeave(start, this.index, i);
        }
        consumeTerm() {
          if (this._unicodeMode || this.strict) {
            return this.consumeAssertion() || this.consumeAtom() && this.consumeOptionalQuantifier();
          }
          return this.consumeAssertion() && (!this._lastAssertionIsQuantifiable || this.consumeOptionalQuantifier()) || this.consumeExtendedAtom() && this.consumeOptionalQuantifier();
        }
        consumeOptionalQuantifier() {
          this.consumeQuantifier();
          return true;
        }
        consumeAssertion() {
          const start = this.index;
          this._lastAssertionIsQuantifiable = false;
          if (this.eat(CIRCUMFLEX_ACCENT)) {
            this.onEdgeAssertion(start, this.index, "start");
            return true;
          }
          if (this.eat(DOLLAR_SIGN)) {
            this.onEdgeAssertion(start, this.index, "end");
            return true;
          }
          if (this.eat2(REVERSE_SOLIDUS, LATIN_CAPITAL_LETTER_B)) {
            this.onWordBoundaryAssertion(start, this.index, "word", true);
            return true;
          }
          if (this.eat2(REVERSE_SOLIDUS, LATIN_SMALL_LETTER_B)) {
            this.onWordBoundaryAssertion(start, this.index, "word", false);
            return true;
          }
          if (this.eat2(LEFT_PARENTHESIS, QUESTION_MARK)) {
            const lookbehind = this.ecmaVersion >= 2018 && this.eat(LESS_THAN_SIGN);
            let negate = false;
            if (this.eat(EQUALS_SIGN) || (negate = this.eat(EXCLAMATION_MARK))) {
              const kind = lookbehind ? "lookbehind" : "lookahead";
              this.onLookaroundAssertionEnter(start, kind, negate);
              this.consumeDisjunction();
              if (!this.eat(RIGHT_PARENTHESIS)) {
                this.raise("Unterminated group");
              }
              this._lastAssertionIsQuantifiable = !lookbehind && !this.strict;
              this.onLookaroundAssertionLeave(start, this.index, kind, negate);
              return true;
            }
            this.rewind(start);
          }
          return false;
        }
        consumeQuantifier(noConsume = false) {
          const start = this.index;
          let min = 0;
          let max = 0;
          let greedy = false;
          if (this.eat(ASTERISK)) {
            min = 0;
            max = Number.POSITIVE_INFINITY;
          } else if (this.eat(PLUS_SIGN)) {
            min = 1;
            max = Number.POSITIVE_INFINITY;
          } else if (this.eat(QUESTION_MARK)) {
            min = 0;
            max = 1;
          } else if (this.eatBracedQuantifier(noConsume)) {
            ({ min, max } = this._lastRange);
          } else {
            return false;
          }
          greedy = !this.eat(QUESTION_MARK);
          if (!noConsume) {
            this.onQuantifier(start, this.index, min, max, greedy);
          }
          return true;
        }
        eatBracedQuantifier(noError) {
          const start = this.index;
          if (this.eat(LEFT_CURLY_BRACKET)) {
            if (this.eatDecimalDigits()) {
              const min = this._lastIntValue;
              let max = min;
              if (this.eat(COMMA)) {
                max = this.eatDecimalDigits() ? this._lastIntValue : Number.POSITIVE_INFINITY;
              }
              if (this.eat(RIGHT_CURLY_BRACKET)) {
                if (!noError && max < min) {
                  this.raise("numbers out of order in {} quantifier");
                }
                this._lastRange = { min, max };
                return true;
              }
            }
            if (!noError && (this._unicodeMode || this.strict)) {
              this.raise("Incomplete quantifier");
            }
            this.rewind(start);
          }
          return false;
        }
        consumeAtom() {
          return this.consumePatternCharacter() || this.consumeDot() || this.consumeReverseSolidusAtomEscape() || Boolean(this.consumeCharacterClass()) || this.consumeCapturingGroup() || this.consumeUncapturingGroup();
        }
        consumeDot() {
          if (this.eat(FULL_STOP)) {
            this.onAnyCharacterSet(this.index - 1, this.index, "any");
            return true;
          }
          return false;
        }
        consumeReverseSolidusAtomEscape() {
          const start = this.index;
          if (this.eat(REVERSE_SOLIDUS)) {
            if (this.consumeAtomEscape()) {
              return true;
            }
            this.rewind(start);
          }
          return false;
        }
        consumeUncapturingGroup() {
          const start = this.index;
          if (this.eat2(LEFT_PARENTHESIS, QUESTION_MARK)) {
            this.onGroupEnter(start);
            if (this.ecmaVersion >= 2025) {
              this.consumeModifiers();
            }
            if (!this.eat(COLON)) {
              this.rewind(start + 1);
              this.raise("Invalid group");
            }
            this.consumeDisjunction();
            if (!this.eat(RIGHT_PARENTHESIS)) {
              this.raise("Unterminated group");
            }
            this.onGroupLeave(start, this.index);
            return true;
          }
          return false;
        }
        consumeModifiers() {
          const start = this.index;
          const hasAddModifiers = this.eatModifiers();
          const addModifiersEnd = this.index;
          const hasHyphen = this.eat(HYPHEN_MINUS);
          if (!hasAddModifiers && !hasHyphen) {
            return false;
          }
          this.onModifiersEnter(start);
          const addModifiers = this.parseModifiers(start, addModifiersEnd);
          this.onAddModifiers(start, addModifiersEnd, addModifiers);
          if (hasHyphen) {
            const modifiersStart = this.index;
            if (!this.eatModifiers() && !hasAddModifiers && this.currentCodePoint === COLON) {
              this.raise("Invalid empty flags");
            }
            const modifiers = this.parseModifiers(modifiersStart, this.index);
            for (const [flagName] of Object.entries(modifiers).filter(([, enable]) => enable)) {
              if (addModifiers[flagName]) {
                this.raise(`Duplicated flag '${String.fromCodePoint(FLAG_PROP_TO_CODEPOINT[flagName])}'`);
              }
            }
            this.onRemoveModifiers(modifiersStart, this.index, modifiers);
          }
          this.onModifiersLeave(start, this.index);
          return true;
        }
        consumeCapturingGroup() {
          const start = this.index;
          if (this.eat(LEFT_PARENTHESIS)) {
            let name = null;
            if (this.ecmaVersion >= 2018) {
              if (this.consumeGroupSpecifier()) {
                name = this._lastStrValue;
              } else if (this.currentCodePoint === QUESTION_MARK) {
                this.rewind(start);
                return false;
              }
            } else if (this.currentCodePoint === QUESTION_MARK) {
              this.rewind(start);
              return false;
            }
            this.onCapturingGroupEnter(start, name);
            this.consumeDisjunction();
            if (!this.eat(RIGHT_PARENTHESIS)) {
              this.raise("Unterminated group");
            }
            this.onCapturingGroupLeave(start, this.index, name);
            return true;
          }
          return false;
        }
        consumeExtendedAtom() {
          return this.consumeDot() || this.consumeReverseSolidusAtomEscape() || this.consumeReverseSolidusFollowedByC() || Boolean(this.consumeCharacterClass()) || this.consumeCapturingGroup() || this.consumeUncapturingGroup() || this.consumeInvalidBracedQuantifier() || this.consumeExtendedPatternCharacter();
        }
        consumeReverseSolidusFollowedByC() {
          const start = this.index;
          if (this.currentCodePoint === REVERSE_SOLIDUS && this.nextCodePoint === LATIN_SMALL_LETTER_C) {
            this._lastIntValue = this.currentCodePoint;
            this.advance();
            this.onCharacter(start, this.index, REVERSE_SOLIDUS);
            return true;
          }
          return false;
        }
        consumeInvalidBracedQuantifier() {
          if (this.eatBracedQuantifier(true)) {
            this.raise("Nothing to repeat");
          }
          return false;
        }
        consumePatternCharacter() {
          const start = this.index;
          const cp = this.currentCodePoint;
          if (cp !== -1 && !isSyntaxCharacter(cp)) {
            this.advance();
            this.onCharacter(start, this.index, cp);
            return true;
          }
          return false;
        }
        consumeExtendedPatternCharacter() {
          const start = this.index;
          const cp = this.currentCodePoint;
          if (cp !== -1 && cp !== CIRCUMFLEX_ACCENT && cp !== DOLLAR_SIGN && cp !== REVERSE_SOLIDUS && cp !== FULL_STOP && cp !== ASTERISK && cp !== PLUS_SIGN && cp !== QUESTION_MARK && cp !== LEFT_PARENTHESIS && cp !== RIGHT_PARENTHESIS && cp !== LEFT_SQUARE_BRACKET && cp !== VERTICAL_LINE) {
            this.advance();
            this.onCharacter(start, this.index, cp);
            return true;
          }
          return false;
        }
        consumeGroupSpecifier() {
          const start = this.index;
          if (this.eat(QUESTION_MARK)) {
            if (this.eatGroupName()) {
              if (!this._groupSpecifiers.hasInScope(this._lastStrValue)) {
                this._groupSpecifiers.addToScope(this._lastStrValue);
                return true;
              }
              this.raise("Duplicate capture group name");
            }
            this.rewind(start);
          }
          return false;
        }
        consumeAtomEscape() {
          if (this.consumeBackreference() || this.consumeCharacterClassEscape() || this.consumeCharacterEscape() || this._nFlag && this.consumeKGroupName()) {
            return true;
          }
          if (this.strict || this._unicodeMode) {
            this.raise("Invalid escape");
          }
          return false;
        }
        consumeBackreference() {
          const start = this.index;
          if (this.eatDecimalEscape()) {
            const n = this._lastIntValue;
            if (n <= this._numCapturingParens) {
              this.onBackreference(start - 1, this.index, n);
              return true;
            }
            if (this.strict || this._unicodeMode) {
              this.raise("Invalid escape");
            }
            this.rewind(start);
          }
          return false;
        }
        consumeCharacterClassEscape() {
          var _a;
          const start = this.index;
          if (this.eat(LATIN_SMALL_LETTER_D)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "digit", false);
            return {};
          }
          if (this.eat(LATIN_CAPITAL_LETTER_D)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "digit", true);
            return {};
          }
          if (this.eat(LATIN_SMALL_LETTER_S)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "space", false);
            return {};
          }
          if (this.eat(LATIN_CAPITAL_LETTER_S)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "space", true);
            return {};
          }
          if (this.eat(LATIN_SMALL_LETTER_W)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "word", false);
            return {};
          }
          if (this.eat(LATIN_CAPITAL_LETTER_W)) {
            this._lastIntValue = -1;
            this.onEscapeCharacterSet(start - 1, this.index, "word", true);
            return {};
          }
          let negate = false;
          if (this._unicodeMode && this.ecmaVersion >= 2018 && (this.eat(LATIN_SMALL_LETTER_P) || (negate = this.eat(LATIN_CAPITAL_LETTER_P)))) {
            this._lastIntValue = -1;
            let result = null;
            if (this.eat(LEFT_CURLY_BRACKET) && (result = this.eatUnicodePropertyValueExpression()) && this.eat(RIGHT_CURLY_BRACKET)) {
              if (negate && result.strings) {
                this.raise("Invalid property name");
              }
              this.onUnicodePropertyCharacterSet(start - 1, this.index, "property", result.key, result.value, negate, (_a = result.strings) !== null && _a !== void 0 ? _a : false);
              return { mayContainStrings: result.strings };
            }
            this.raise("Invalid property name");
          }
          return null;
        }
        consumeCharacterEscape() {
          const start = this.index;
          if (this.eatControlEscape() || this.eatCControlLetter() || this.eatZero() || this.eatHexEscapeSequence() || this.eatRegExpUnicodeEscapeSequence() || !this.strict && !this._unicodeMode && this.eatLegacyOctalEscapeSequence() || this.eatIdentityEscape()) {
            this.onCharacter(start - 1, this.index, this._lastIntValue);
            return true;
          }
          return false;
        }
        consumeKGroupName() {
          const start = this.index;
          if (this.eat(LATIN_SMALL_LETTER_K)) {
            if (this.eatGroupName()) {
              const groupName = this._lastStrValue;
              this._backreferenceNames.add(groupName);
              this.onBackreference(start - 1, this.index, groupName);
              return true;
            }
            this.raise("Invalid named reference");
          }
          return false;
        }
        consumeCharacterClass() {
          const start = this.index;
          if (this.eat(LEFT_SQUARE_BRACKET)) {
            const negate = this.eat(CIRCUMFLEX_ACCENT);
            this.onCharacterClassEnter(start, negate, this._unicodeSetsMode);
            const result = this.consumeClassContents();
            if (!this.eat(RIGHT_SQUARE_BRACKET)) {
              if (this.currentCodePoint === -1) {
                this.raise("Unterminated character class");
              }
              this.raise("Invalid character in character class");
            }
            if (negate && result.mayContainStrings) {
              this.raise("Negated character class may contain strings");
            }
            this.onCharacterClassLeave(start, this.index, negate);
            return result;
          }
          return null;
        }
        consumeClassContents() {
          if (this._unicodeSetsMode) {
            if (this.currentCodePoint === RIGHT_SQUARE_BRACKET) {
              return {};
            }
            const result = this.consumeClassSetExpression();
            return result;
          }
          const strict = this.strict || this._unicodeMode;
          for (; ; ) {
            const rangeStart = this.index;
            if (!this.consumeClassAtom()) {
              break;
            }
            const min = this._lastIntValue;
            if (!this.eat(HYPHEN_MINUS)) {
              continue;
            }
            this.onCharacter(this.index - 1, this.index, HYPHEN_MINUS);
            if (!this.consumeClassAtom()) {
              break;
            }
            const max = this._lastIntValue;
            if (min === -1 || max === -1) {
              if (strict) {
                this.raise("Invalid character class");
              }
              continue;
            }
            if (min > max) {
              this.raise("Range out of order in character class");
            }
            this.onCharacterClassRange(rangeStart, this.index, min, max);
          }
          return {};
        }
        consumeClassAtom() {
          const start = this.index;
          const cp = this.currentCodePoint;
          if (cp !== -1 && cp !== REVERSE_SOLIDUS && cp !== RIGHT_SQUARE_BRACKET) {
            this.advance();
            this._lastIntValue = cp;
            this.onCharacter(start, this.index, this._lastIntValue);
            return true;
          }
          if (this.eat(REVERSE_SOLIDUS)) {
            if (this.consumeClassEscape()) {
              return true;
            }
            if (!this.strict && this.currentCodePoint === LATIN_SMALL_LETTER_C) {
              this._lastIntValue = REVERSE_SOLIDUS;
              this.onCharacter(start, this.index, this._lastIntValue);
              return true;
            }
            if (this.strict || this._unicodeMode) {
              this.raise("Invalid escape");
            }
            this.rewind(start);
          }
          return false;
        }
        consumeClassEscape() {
          const start = this.index;
          if (this.eat(LATIN_SMALL_LETTER_B)) {
            this._lastIntValue = BACKSPACE;
            this.onCharacter(start - 1, this.index, this._lastIntValue);
            return true;
          }
          if (this._unicodeMode && this.eat(HYPHEN_MINUS)) {
            this._lastIntValue = HYPHEN_MINUS;
            this.onCharacter(start - 1, this.index, this._lastIntValue);
            return true;
          }
          let cp = 0;
          if (!this.strict && !this._unicodeMode && this.currentCodePoint === LATIN_SMALL_LETTER_C && (isDecimalDigit(cp = this.nextCodePoint) || cp === LOW_LINE)) {
            this.advance();
            this.advance();
            this._lastIntValue = cp % 32;
            this.onCharacter(start - 1, this.index, this._lastIntValue);
            return true;
          }
          return Boolean(this.consumeCharacterClassEscape()) || this.consumeCharacterEscape();
        }
        consumeClassSetExpression() {
          const start = this.index;
          let mayContainStrings = false;
          let result = null;
          if (this.consumeClassSetCharacter()) {
            if (this.consumeClassSetRangeFromOperator(start)) {
              this.consumeClassUnionRight({});
              return {};
            }
            mayContainStrings = false;
          } else if (result = this.consumeClassSetOperand()) {
            mayContainStrings = result.mayContainStrings;
          } else {
            const cp = this.currentCodePoint;
            if (cp === REVERSE_SOLIDUS) {
              this.advance();
              this.raise("Invalid escape");
            }
            if (cp === this.nextCodePoint && isClassSetReservedDoublePunctuatorCharacter(cp)) {
              this.raise("Invalid set operation in character class");
            }
            this.raise("Invalid character in character class");
          }
          if (this.eat2(AMPERSAND, AMPERSAND)) {
            while (this.currentCodePoint !== AMPERSAND && (result = this.consumeClassSetOperand())) {
              this.onClassIntersection(start, this.index);
              if (!result.mayContainStrings) {
                mayContainStrings = false;
              }
              if (this.eat2(AMPERSAND, AMPERSAND)) {
                continue;
              }
              return { mayContainStrings };
            }
            this.raise("Invalid character in character class");
          }
          if (this.eat2(HYPHEN_MINUS, HYPHEN_MINUS)) {
            while (this.consumeClassSetOperand()) {
              this.onClassSubtraction(start, this.index);
              if (this.eat2(HYPHEN_MINUS, HYPHEN_MINUS)) {
                continue;
              }
              return { mayContainStrings };
            }
            this.raise("Invalid character in character class");
          }
          return this.consumeClassUnionRight({ mayContainStrings });
        }
        consumeClassUnionRight(leftResult) {
          let mayContainStrings = leftResult.mayContainStrings;
          for (; ; ) {
            const start = this.index;
            if (this.consumeClassSetCharacter()) {
              this.consumeClassSetRangeFromOperator(start);
              continue;
            }
            const result = this.consumeClassSetOperand();
            if (result) {
              if (result.mayContainStrings) {
                mayContainStrings = true;
              }
              continue;
            }
            break;
          }
          return { mayContainStrings };
        }
        consumeClassSetRangeFromOperator(start) {
          const currentStart = this.index;
          const min = this._lastIntValue;
          if (this.eat(HYPHEN_MINUS)) {
            if (this.consumeClassSetCharacter()) {
              const max = this._lastIntValue;
              if (min === -1 || max === -1) {
                this.raise("Invalid character class");
              }
              if (min > max) {
                this.raise("Range out of order in character class");
              }
              this.onCharacterClassRange(start, this.index, min, max);
              return true;
            }
            this.rewind(currentStart);
          }
          return false;
        }
        consumeClassSetOperand() {
          let result = null;
          if (result = this.consumeNestedClass()) {
            return result;
          }
          if (result = this.consumeClassStringDisjunction()) {
            return result;
          }
          if (this.consumeClassSetCharacter()) {
            return {};
          }
          return null;
        }
        consumeNestedClass() {
          const start = this.index;
          if (this.eat(LEFT_SQUARE_BRACKET)) {
            const negate = this.eat(CIRCUMFLEX_ACCENT);
            this.onCharacterClassEnter(start, negate, true);
            const result = this.consumeClassContents();
            if (!this.eat(RIGHT_SQUARE_BRACKET)) {
              this.raise("Unterminated character class");
            }
            if (negate && result.mayContainStrings) {
              this.raise("Negated character class may contain strings");
            }
            this.onCharacterClassLeave(start, this.index, negate);
            return result;
          }
          if (this.eat(REVERSE_SOLIDUS)) {
            const result = this.consumeCharacterClassEscape();
            if (result) {
              return result;
            }
            this.rewind(start);
          }
          return null;
        }
        consumeClassStringDisjunction() {
          const start = this.index;
          if (this.eat3(REVERSE_SOLIDUS, LATIN_SMALL_LETTER_Q, LEFT_CURLY_BRACKET)) {
            this.onClassStringDisjunctionEnter(start);
            let i = 0;
            let mayContainStrings = false;
            do {
              if (this.consumeClassString(i++).mayContainStrings) {
                mayContainStrings = true;
              }
            } while (this.eat(VERTICAL_LINE));
            if (this.eat(RIGHT_CURLY_BRACKET)) {
              this.onClassStringDisjunctionLeave(start, this.index);
              return { mayContainStrings };
            }
            this.raise("Unterminated class string disjunction");
          }
          return null;
        }
        consumeClassString(i) {
          const start = this.index;
          let count = 0;
          this.onStringAlternativeEnter(start, i);
          while (this.currentCodePoint !== -1 && this.consumeClassSetCharacter()) {
            count++;
          }
          this.onStringAlternativeLeave(start, this.index, i);
          return { mayContainStrings: count !== 1 };
        }
        consumeClassSetCharacter() {
          const start = this.index;
          const cp = this.currentCodePoint;
          if (cp !== this.nextCodePoint || !isClassSetReservedDoublePunctuatorCharacter(cp)) {
            if (cp !== -1 && !isClassSetSyntaxCharacter(cp)) {
              this._lastIntValue = cp;
              this.advance();
              this.onCharacter(start, this.index, this._lastIntValue);
              return true;
            }
          }
          if (this.eat(REVERSE_SOLIDUS)) {
            if (this.consumeCharacterEscape()) {
              return true;
            }
            if (isClassSetReservedPunctuator(this.currentCodePoint)) {
              this._lastIntValue = this.currentCodePoint;
              this.advance();
              this.onCharacter(start, this.index, this._lastIntValue);
              return true;
            }
            if (this.eat(LATIN_SMALL_LETTER_B)) {
              this._lastIntValue = BACKSPACE;
              this.onCharacter(start, this.index, this._lastIntValue);
              return true;
            }
            this.rewind(start);
          }
          return false;
        }
        eatGroupName() {
          if (this.eat(LESS_THAN_SIGN)) {
            if (this.eatRegExpIdentifierName() && this.eat(GREATER_THAN_SIGN)) {
              return true;
            }
            this.raise("Invalid capture group name");
          }
          return false;
        }
        eatRegExpIdentifierName() {
          if (this.eatRegExpIdentifierStart()) {
            this._lastStrValue = String.fromCodePoint(this._lastIntValue);
            while (this.eatRegExpIdentifierPart()) {
              this._lastStrValue += String.fromCodePoint(this._lastIntValue);
            }
            return true;
          }
          return false;
        }
        eatRegExpIdentifierStart() {
          const start = this.index;
          const forceUFlag = !this._unicodeMode && this.ecmaVersion >= 2020;
          let cp = this.currentCodePoint;
          this.advance();
          if (cp === REVERSE_SOLIDUS && this.eatRegExpUnicodeEscapeSequence(forceUFlag)) {
            cp = this._lastIntValue;
          } else if (forceUFlag && isLeadSurrogate(cp) && isTrailSurrogate(this.currentCodePoint)) {
            cp = combineSurrogatePair(cp, this.currentCodePoint);
            this.advance();
          }
          if (isIdentifierStartChar(cp)) {
            this._lastIntValue = cp;
            return true;
          }
          if (this.index !== start) {
            this.rewind(start);
          }
          return false;
        }
        eatRegExpIdentifierPart() {
          const start = this.index;
          const forceUFlag = !this._unicodeMode && this.ecmaVersion >= 2020;
          let cp = this.currentCodePoint;
          this.advance();
          if (cp === REVERSE_SOLIDUS && this.eatRegExpUnicodeEscapeSequence(forceUFlag)) {
            cp = this._lastIntValue;
          } else if (forceUFlag && isLeadSurrogate(cp) && isTrailSurrogate(this.currentCodePoint)) {
            cp = combineSurrogatePair(cp, this.currentCodePoint);
            this.advance();
          }
          if (isIdentifierPartChar(cp)) {
            this._lastIntValue = cp;
            return true;
          }
          if (this.index !== start) {
            this.rewind(start);
          }
          return false;
        }
        eatCControlLetter() {
          const start = this.index;
          if (this.eat(LATIN_SMALL_LETTER_C)) {
            if (this.eatControlLetter()) {
              return true;
            }
            this.rewind(start);
          }
          return false;
        }
        eatZero() {
          if (this.currentCodePoint === DIGIT_ZERO && !isDecimalDigit(this.nextCodePoint)) {
            this._lastIntValue = 0;
            this.advance();
            return true;
          }
          return false;
        }
        eatControlEscape() {
          if (this.eat(LATIN_SMALL_LETTER_F)) {
            this._lastIntValue = FORM_FEED;
            return true;
          }
          if (this.eat(LATIN_SMALL_LETTER_N)) {
            this._lastIntValue = LINE_FEED;
            return true;
          }
          if (this.eat(LATIN_SMALL_LETTER_R)) {
            this._lastIntValue = CARRIAGE_RETURN;
            return true;
          }
          if (this.eat(LATIN_SMALL_LETTER_T)) {
            this._lastIntValue = CHARACTER_TABULATION;
            return true;
          }
          if (this.eat(LATIN_SMALL_LETTER_V)) {
            this._lastIntValue = LINE_TABULATION;
            return true;
          }
          return false;
        }
        eatControlLetter() {
          const cp = this.currentCodePoint;
          if (isLatinLetter(cp)) {
            this.advance();
            this._lastIntValue = cp % 32;
            return true;
          }
          return false;
        }
        eatRegExpUnicodeEscapeSequence(forceUFlag = false) {
          const start = this.index;
          const uFlag = forceUFlag || this._unicodeMode;
          if (this.eat(LATIN_SMALL_LETTER_U)) {
            if (uFlag && this.eatRegExpUnicodeSurrogatePairEscape() || this.eatFixedHexDigits(4) || uFlag && this.eatRegExpUnicodeCodePointEscape()) {
              return true;
            }
            if (this.strict || uFlag) {
              this.raise("Invalid unicode escape");
            }
            this.rewind(start);
          }
          return false;
        }
        eatRegExpUnicodeSurrogatePairEscape() {
          const start = this.index;
          if (this.eatFixedHexDigits(4)) {
            const lead = this._lastIntValue;
            if (isLeadSurrogate(lead) && this.eat(REVERSE_SOLIDUS) && this.eat(LATIN_SMALL_LETTER_U) && this.eatFixedHexDigits(4)) {
              const trail = this._lastIntValue;
              if (isTrailSurrogate(trail)) {
                this._lastIntValue = combineSurrogatePair(lead, trail);
                return true;
              }
            }
            this.rewind(start);
          }
          return false;
        }
        eatRegExpUnicodeCodePointEscape() {
          const start = this.index;
          if (this.eat(LEFT_CURLY_BRACKET) && this.eatHexDigits() && this.eat(RIGHT_CURLY_BRACKET) && isValidUnicode(this._lastIntValue)) {
            return true;
          }
          this.rewind(start);
          return false;
        }
        eatIdentityEscape() {
          const cp = this.currentCodePoint;
          if (this.isValidIdentityEscape(cp)) {
            this._lastIntValue = cp;
            this.advance();
            return true;
          }
          return false;
        }
        isValidIdentityEscape(cp) {
          if (cp === -1) {
            return false;
          }
          if (this._unicodeMode) {
            return isSyntaxCharacter(cp) || cp === SOLIDUS;
          }
          if (this.strict) {
            return !isIdContinue(cp);
          }
          if (this._nFlag) {
            return !(cp === LATIN_SMALL_LETTER_C || cp === LATIN_SMALL_LETTER_K);
          }
          return cp !== LATIN_SMALL_LETTER_C;
        }
        eatDecimalEscape() {
          this._lastIntValue = 0;
          let cp = this.currentCodePoint;
          if (cp >= DIGIT_ONE && cp <= DIGIT_NINE) {
            do {
              this._lastIntValue = 10 * this._lastIntValue + (cp - DIGIT_ZERO);
              this.advance();
            } while ((cp = this.currentCodePoint) >= DIGIT_ZERO && cp <= DIGIT_NINE);
            return true;
          }
          return false;
        }
        eatUnicodePropertyValueExpression() {
          const start = this.index;
          if (this.eatUnicodePropertyName() && this.eat(EQUALS_SIGN)) {
            const key = this._lastStrValue;
            if (this.eatUnicodePropertyValue()) {
              const value = this._lastStrValue;
              if (isValidUnicodeProperty(this.ecmaVersion, key, value)) {
                return {
                  key,
                  value: value || null
                };
              }
              this.raise("Invalid property name");
            }
          }
          this.rewind(start);
          if (this.eatLoneUnicodePropertyNameOrValue()) {
            const nameOrValue = this._lastStrValue;
            if (isValidUnicodeProperty(this.ecmaVersion, "General_Category", nameOrValue)) {
              return {
                key: "General_Category",
                value: nameOrValue || null
              };
            }
            if (isValidLoneUnicodeProperty(this.ecmaVersion, nameOrValue)) {
              return {
                key: nameOrValue,
                value: null
              };
            }
            if (this._unicodeSetsMode && isValidLoneUnicodePropertyOfString(this.ecmaVersion, nameOrValue)) {
              return {
                key: nameOrValue,
                value: null,
                strings: true
              };
            }
            this.raise("Invalid property name");
          }
          return null;
        }
        eatUnicodePropertyName() {
          this._lastStrValue = "";
          while (isUnicodePropertyNameCharacter(this.currentCodePoint)) {
            this._lastStrValue += String.fromCodePoint(this.currentCodePoint);
            this.advance();
          }
          return this._lastStrValue !== "";
        }
        eatUnicodePropertyValue() {
          this._lastStrValue = "";
          while (isUnicodePropertyValueCharacter(this.currentCodePoint)) {
            this._lastStrValue += String.fromCodePoint(this.currentCodePoint);
            this.advance();
          }
          return this._lastStrValue !== "";
        }
        eatLoneUnicodePropertyNameOrValue() {
          return this.eatUnicodePropertyValue();
        }
        eatHexEscapeSequence() {
          const start = this.index;
          if (this.eat(LATIN_SMALL_LETTER_X)) {
            if (this.eatFixedHexDigits(2)) {
              return true;
            }
            if (this._unicodeMode || this.strict) {
              this.raise("Invalid escape");
            }
            this.rewind(start);
          }
          return false;
        }
        eatDecimalDigits() {
          const start = this.index;
          this._lastIntValue = 0;
          while (isDecimalDigit(this.currentCodePoint)) {
            this._lastIntValue = 10 * this._lastIntValue + digitToInt(this.currentCodePoint);
            this.advance();
          }
          return this.index !== start;
        }
        eatHexDigits() {
          const start = this.index;
          this._lastIntValue = 0;
          while (isHexDigit(this.currentCodePoint)) {
            this._lastIntValue = 16 * this._lastIntValue + digitToInt(this.currentCodePoint);
            this.advance();
          }
          return this.index !== start;
        }
        eatLegacyOctalEscapeSequence() {
          if (this.eatOctalDigit()) {
            const n1 = this._lastIntValue;
            if (this.eatOctalDigit()) {
              const n2 = this._lastIntValue;
              if (n1 <= 3 && this.eatOctalDigit()) {
                this._lastIntValue = n1 * 64 + n2 * 8 + this._lastIntValue;
              } else {
                this._lastIntValue = n1 * 8 + n2;
              }
            } else {
              this._lastIntValue = n1;
            }
            return true;
          }
          return false;
        }
        eatOctalDigit() {
          const cp = this.currentCodePoint;
          if (isOctalDigit(cp)) {
            this.advance();
            this._lastIntValue = cp - DIGIT_ZERO;
            return true;
          }
          this._lastIntValue = 0;
          return false;
        }
        eatFixedHexDigits(length) {
          const start = this.index;
          this._lastIntValue = 0;
          for (let i = 0; i < length; ++i) {
            const cp = this.currentCodePoint;
            if (!isHexDigit(cp)) {
              this.rewind(start);
              return false;
            }
            this._lastIntValue = 16 * this._lastIntValue + digitToInt(cp);
            this.advance();
          }
          return true;
        }
        eatModifiers() {
          let ate = false;
          while (isRegularExpressionModifier(this.currentCodePoint)) {
            this.advance();
            ate = true;
          }
          return ate;
        }
        parseModifiers(start, end) {
          const { ignoreCase, multiline, dotAll } = this.parseFlags(this._reader.source, start, end);
          return { ignoreCase, multiline, dotAll };
        }
        parseFlags(source, start, end) {
          const flags = {
            global: false,
            ignoreCase: false,
            multiline: false,
            unicode: false,
            sticky: false,
            dotAll: false,
            hasIndices: false,
            unicodeSets: false
          };
          const validFlags = /* @__PURE__ */ new Set();
          validFlags.add(LATIN_SMALL_LETTER_G);
          validFlags.add(LATIN_SMALL_LETTER_I);
          validFlags.add(LATIN_SMALL_LETTER_M);
          if (this.ecmaVersion >= 2015) {
            validFlags.add(LATIN_SMALL_LETTER_U);
            validFlags.add(LATIN_SMALL_LETTER_Y);
            if (this.ecmaVersion >= 2018) {
              validFlags.add(LATIN_SMALL_LETTER_S);
              if (this.ecmaVersion >= 2022) {
                validFlags.add(LATIN_SMALL_LETTER_D);
                if (this.ecmaVersion >= 2024) {
                  validFlags.add(LATIN_SMALL_LETTER_V);
                }
              }
            }
          }
          for (let i = start; i < end; ++i) {
            const flag = source.charCodeAt(i);
            if (validFlags.has(flag)) {
              const prop = FLAG_CODEPOINT_TO_PROP[flag];
              if (flags[prop]) {
                this.raise(`Duplicated flag '${source[i]}'`, {
                  index: start
                });
              }
              flags[prop] = true;
            } else {
              this.raise(`Invalid flag '${source[i]}'`, { index: start });
            }
          }
          return flags;
        }
      };
      DUMMY_PATTERN = {};
      DUMMY_FLAGS = {};
      DUMMY_CAPTURING_GROUP = {};
      RegExpParserState = class {
        constructor(options) {
          var _a;
          this._node = DUMMY_PATTERN;
          this._expressionBufferMap = /* @__PURE__ */ new Map();
          this._flags = DUMMY_FLAGS;
          this._backreferences = [];
          this._capturingGroups = [];
          this.source = "";
          this.strict = Boolean(options === null || options === void 0 ? void 0 : options.strict);
          this.ecmaVersion = (_a = options === null || options === void 0 ? void 0 : options.ecmaVersion) !== null && _a !== void 0 ? _a : latestEcmaVersion;
        }
        get pattern() {
          if (this._node.type !== "Pattern") {
            throw new Error("UnknownError");
          }
          return this._node;
        }
        get flags() {
          if (this._flags.type !== "Flags") {
            throw new Error("UnknownError");
          }
          return this._flags;
        }
        onRegExpFlags(start, end, { global, ignoreCase, multiline, unicode, sticky, dotAll, hasIndices, unicodeSets }) {
          this._flags = {
            type: "Flags",
            parent: null,
            start,
            end,
            raw: this.source.slice(start, end),
            global,
            ignoreCase,
            multiline,
            unicode,
            sticky,
            dotAll,
            hasIndices,
            unicodeSets
          };
        }
        onPatternEnter(start) {
          this._node = {
            type: "Pattern",
            parent: null,
            start,
            end: start,
            raw: "",
            alternatives: []
          };
          this._backreferences.length = 0;
          this._capturingGroups.length = 0;
        }
        onPatternLeave(start, end) {
          this._node.end = end;
          this._node.raw = this.source.slice(start, end);
          for (const reference of this._backreferences) {
            const ref = reference.ref;
            const groups = typeof ref === "number" ? [this._capturingGroups[ref - 1]] : this._capturingGroups.filter((g) => g.name === ref);
            if (groups.length === 1) {
              const group = groups[0];
              reference.ambiguous = false;
              reference.resolved = group;
            } else {
              reference.ambiguous = true;
              reference.resolved = groups;
            }
            for (const group of groups) {
              group.references.push(reference);
            }
          }
        }
        onAlternativeEnter(start) {
          const parent = this._node;
          if (parent.type !== "Assertion" && parent.type !== "CapturingGroup" && parent.type !== "Group" && parent.type !== "Pattern") {
            throw new Error("UnknownError");
          }
          this._node = {
            type: "Alternative",
            parent,
            start,
            end: start,
            raw: "",
            elements: []
          };
          parent.alternatives.push(this._node);
        }
        onAlternativeLeave(start, end) {
          const node = this._node;
          if (node.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onGroupEnter(start) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          const group = {
            type: "Group",
            parent,
            start,
            end: start,
            raw: "",
            modifiers: null,
            alternatives: []
          };
          this._node = group;
          parent.elements.push(this._node);
        }
        onGroupLeave(start, end) {
          const node = this._node;
          if (node.type !== "Group" || node.parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onModifiersEnter(start) {
          const parent = this._node;
          if (parent.type !== "Group") {
            throw new Error("UnknownError");
          }
          this._node = {
            type: "Modifiers",
            parent,
            start,
            end: start,
            raw: "",
            add: null,
            remove: null
          };
          parent.modifiers = this._node;
        }
        onModifiersLeave(start, end) {
          const node = this._node;
          if (node.type !== "Modifiers" || node.parent.type !== "Group") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onAddModifiers(start, end, { ignoreCase, multiline, dotAll }) {
          const parent = this._node;
          if (parent.type !== "Modifiers") {
            throw new Error("UnknownError");
          }
          parent.add = {
            type: "ModifierFlags",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            ignoreCase,
            multiline,
            dotAll
          };
        }
        onRemoveModifiers(start, end, { ignoreCase, multiline, dotAll }) {
          const parent = this._node;
          if (parent.type !== "Modifiers") {
            throw new Error("UnknownError");
          }
          parent.remove = {
            type: "ModifierFlags",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            ignoreCase,
            multiline,
            dotAll
          };
        }
        onCapturingGroupEnter(start, name) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          this._node = {
            type: "CapturingGroup",
            parent,
            start,
            end: start,
            raw: "",
            name,
            alternatives: [],
            references: []
          };
          parent.elements.push(this._node);
          this._capturingGroups.push(this._node);
        }
        onCapturingGroupLeave(start, end) {
          const node = this._node;
          if (node.type !== "CapturingGroup" || node.parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onQuantifier(start, end, min, max, greedy) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          const element = parent.elements.pop();
          if (element == null || element.type === "Quantifier" || element.type === "Assertion" && element.kind !== "lookahead") {
            throw new Error("UnknownError");
          }
          const node = {
            type: "Quantifier",
            parent,
            start: element.start,
            end,
            raw: this.source.slice(element.start, end),
            min,
            max,
            greedy,
            element
          };
          parent.elements.push(node);
          element.parent = node;
        }
        onLookaroundAssertionEnter(start, kind, negate) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          const node = this._node = {
            type: "Assertion",
            parent,
            start,
            end: start,
            raw: "",
            kind,
            negate,
            alternatives: []
          };
          parent.elements.push(node);
        }
        onLookaroundAssertionLeave(start, end) {
          const node = this._node;
          if (node.type !== "Assertion" || node.parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onEdgeAssertion(start, end, kind) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          parent.elements.push({
            type: "Assertion",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            kind
          });
        }
        onWordBoundaryAssertion(start, end, kind, negate) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          parent.elements.push({
            type: "Assertion",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            kind,
            negate
          });
        }
        onAnyCharacterSet(start, end, kind) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          parent.elements.push({
            type: "CharacterSet",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            kind
          });
        }
        onEscapeCharacterSet(start, end, kind, negate) {
          const parent = this._node;
          if (parent.type !== "Alternative" && parent.type !== "CharacterClass") {
            throw new Error("UnknownError");
          }
          parent.elements.push({
            type: "CharacterSet",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            kind,
            negate
          });
        }
        onUnicodePropertyCharacterSet(start, end, kind, key, value, negate, strings) {
          const parent = this._node;
          if (parent.type !== "Alternative" && parent.type !== "CharacterClass") {
            throw new Error("UnknownError");
          }
          const base = {
            type: "CharacterSet",
            parent: null,
            start,
            end,
            raw: this.source.slice(start, end),
            kind,
            strings: null,
            key
          };
          if (strings) {
            if (parent.type === "CharacterClass" && !parent.unicodeSets || negate || value !== null) {
              throw new Error("UnknownError");
            }
            parent.elements.push(Object.assign(Object.assign({}, base), { parent, strings, value, negate }));
          } else {
            parent.elements.push(Object.assign(Object.assign({}, base), { parent, strings, value, negate }));
          }
        }
        onCharacter(start, end, value) {
          const parent = this._node;
          if (parent.type !== "Alternative" && parent.type !== "CharacterClass" && parent.type !== "StringAlternative") {
            throw new Error("UnknownError");
          }
          parent.elements.push({
            type: "Character",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            value
          });
        }
        onBackreference(start, end, ref) {
          const parent = this._node;
          if (parent.type !== "Alternative") {
            throw new Error("UnknownError");
          }
          const node = {
            type: "Backreference",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            ref,
            ambiguous: false,
            resolved: DUMMY_CAPTURING_GROUP
          };
          parent.elements.push(node);
          this._backreferences.push(node);
        }
        onCharacterClassEnter(start, negate, unicodeSets) {
          const parent = this._node;
          const base = {
            type: "CharacterClass",
            parent,
            start,
            end: start,
            raw: "",
            unicodeSets,
            negate,
            elements: []
          };
          if (parent.type === "Alternative") {
            const node = Object.assign(Object.assign({}, base), { parent });
            this._node = node;
            parent.elements.push(node);
          } else if (parent.type === "CharacterClass" && parent.unicodeSets && unicodeSets) {
            const node = Object.assign(Object.assign({}, base), {
              parent,
              unicodeSets
            });
            this._node = node;
            parent.elements.push(node);
          } else {
            throw new Error("UnknownError");
          }
        }
        onCharacterClassLeave(start, end) {
          const node = this._node;
          if (node.type !== "CharacterClass" || node.parent.type !== "Alternative" && node.parent.type !== "CharacterClass") {
            throw new Error("UnknownError");
          }
          const parent = node.parent;
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = parent;
          const expression = this._expressionBufferMap.get(node);
          if (!expression) {
            return;
          }
          if (node.elements.length > 0) {
            throw new Error("UnknownError");
          }
          this._expressionBufferMap.delete(node);
          const newNode = {
            type: "ExpressionCharacterClass",
            parent,
            start: node.start,
            end: node.end,
            raw: node.raw,
            negate: node.negate,
            expression
          };
          expression.parent = newNode;
          if (node !== parent.elements.pop()) {
            throw new Error("UnknownError");
          }
          parent.elements.push(newNode);
        }
        onCharacterClassRange(start, end) {
          const parent = this._node;
          if (parent.type !== "CharacterClass") {
            throw new Error("UnknownError");
          }
          const elements = parent.elements;
          const max = elements.pop();
          if (!max || max.type !== "Character") {
            throw new Error("UnknownError");
          }
          if (!parent.unicodeSets) {
            const hyphen = elements.pop();
            if (!hyphen || hyphen.type !== "Character" || hyphen.value !== HYPHEN_MINUS) {
              throw new Error("UnknownError");
            }
          }
          const min = elements.pop();
          if (!min || min.type !== "Character") {
            throw new Error("UnknownError");
          }
          const node = {
            type: "CharacterClassRange",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            min,
            max
          };
          min.parent = node;
          max.parent = node;
          elements.push(node);
        }
        onClassIntersection(start, end) {
          var _a;
          const parent = this._node;
          if (parent.type !== "CharacterClass" || !parent.unicodeSets) {
            throw new Error("UnknownError");
          }
          const right = parent.elements.pop();
          const left = (_a = this._expressionBufferMap.get(parent)) !== null && _a !== void 0 ? _a : parent.elements.pop();
          if (!left || !right || left.type === "ClassSubtraction" || left.type !== "ClassIntersection" && !isClassSetOperand(left) || !isClassSetOperand(right)) {
            throw new Error("UnknownError");
          }
          const node = {
            type: "ClassIntersection",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            left,
            right
          };
          left.parent = node;
          right.parent = node;
          this._expressionBufferMap.set(parent, node);
        }
        onClassSubtraction(start, end) {
          var _a;
          const parent = this._node;
          if (parent.type !== "CharacterClass" || !parent.unicodeSets) {
            throw new Error("UnknownError");
          }
          const right = parent.elements.pop();
          const left = (_a = this._expressionBufferMap.get(parent)) !== null && _a !== void 0 ? _a : parent.elements.pop();
          if (!left || !right || left.type === "ClassIntersection" || left.type !== "ClassSubtraction" && !isClassSetOperand(left) || !isClassSetOperand(right)) {
            throw new Error("UnknownError");
          }
          const node = {
            type: "ClassSubtraction",
            parent,
            start,
            end,
            raw: this.source.slice(start, end),
            left,
            right
          };
          left.parent = node;
          right.parent = node;
          this._expressionBufferMap.set(parent, node);
        }
        onClassStringDisjunctionEnter(start) {
          const parent = this._node;
          if (parent.type !== "CharacterClass" || !parent.unicodeSets) {
            throw new Error("UnknownError");
          }
          this._node = {
            type: "ClassStringDisjunction",
            parent,
            start,
            end: start,
            raw: "",
            alternatives: []
          };
          parent.elements.push(this._node);
        }
        onClassStringDisjunctionLeave(start, end) {
          const node = this._node;
          if (node.type !== "ClassStringDisjunction" || node.parent.type !== "CharacterClass") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
        onStringAlternativeEnter(start) {
          const parent = this._node;
          if (parent.type !== "ClassStringDisjunction") {
            throw new Error("UnknownError");
          }
          this._node = {
            type: "StringAlternative",
            parent,
            start,
            end: start,
            raw: "",
            elements: []
          };
          parent.alternatives.push(this._node);
        }
        onStringAlternativeLeave(start, end) {
          const node = this._node;
          if (node.type !== "StringAlternative") {
            throw new Error("UnknownError");
          }
          node.end = end;
          node.raw = this.source.slice(start, end);
          this._node = node.parent;
        }
      };
      RegExpParser = class {
        constructor(options) {
          this._state = new RegExpParserState(options);
          this._validator = new RegExpValidator(this._state);
        }
        parseLiteral(source, start = 0, end = source.length) {
          this._state.source = source;
          this._validator.validateLiteral(source, start, end);
          const pattern = this._state.pattern;
          const flags = this._state.flags;
          const literal = {
            type: "RegExpLiteral",
            parent: null,
            start,
            end,
            raw: source,
            pattern,
            flags
          };
          pattern.parent = literal;
          flags.parent = literal;
          return literal;
        }
        parseFlags(source, start = 0, end = source.length) {
          this._state.source = source;
          this._validator.validateFlags(source, start, end);
          return this._state.flags;
        }
        parsePattern(source, start = 0, end = source.length, uFlagOrFlags = void 0) {
          this._state.source = source;
          this._validator.validatePattern(source, start, end, uFlagOrFlags);
          return this._state.pattern;
        }
      };
      RegExpVisitor = class {
        constructor(handlers) {
          this._handlers = handlers;
        }
        visit(node) {
          switch (node.type) {
            case "Alternative":
              this.visitAlternative(node);
              break;
            case "Assertion":
              this.visitAssertion(node);
              break;
            case "Backreference":
              this.visitBackreference(node);
              break;
            case "CapturingGroup":
              this.visitCapturingGroup(node);
              break;
            case "Character":
              this.visitCharacter(node);
              break;
            case "CharacterClass":
              this.visitCharacterClass(node);
              break;
            case "CharacterClassRange":
              this.visitCharacterClassRange(node);
              break;
            case "CharacterSet":
              this.visitCharacterSet(node);
              break;
            case "ClassIntersection":
              this.visitClassIntersection(node);
              break;
            case "ClassStringDisjunction":
              this.visitClassStringDisjunction(node);
              break;
            case "ClassSubtraction":
              this.visitClassSubtraction(node);
              break;
            case "ExpressionCharacterClass":
              this.visitExpressionCharacterClass(node);
              break;
            case "Flags":
              this.visitFlags(node);
              break;
            case "Group":
              this.visitGroup(node);
              break;
            case "Modifiers":
              this.visitModifiers(node);
              break;
            case "ModifierFlags":
              this.visitModifierFlags(node);
              break;
            case "Pattern":
              this.visitPattern(node);
              break;
            case "Quantifier":
              this.visitQuantifier(node);
              break;
            case "RegExpLiteral":
              this.visitRegExpLiteral(node);
              break;
            case "StringAlternative":
              this.visitStringAlternative(node);
              break;
            default:
              throw new Error(`Unknown type: ${node.type}`);
          }
        }
        visitAlternative(node) {
          if (this._handlers.onAlternativeEnter) {
            this._handlers.onAlternativeEnter(node);
          }
          node.elements.forEach(this.visit, this);
          if (this._handlers.onAlternativeLeave) {
            this._handlers.onAlternativeLeave(node);
          }
        }
        visitAssertion(node) {
          if (this._handlers.onAssertionEnter) {
            this._handlers.onAssertionEnter(node);
          }
          if (node.kind === "lookahead" || node.kind === "lookbehind") {
            node.alternatives.forEach(this.visit, this);
          }
          if (this._handlers.onAssertionLeave) {
            this._handlers.onAssertionLeave(node);
          }
        }
        visitBackreference(node) {
          if (this._handlers.onBackreferenceEnter) {
            this._handlers.onBackreferenceEnter(node);
          }
          if (this._handlers.onBackreferenceLeave) {
            this._handlers.onBackreferenceLeave(node);
          }
        }
        visitCapturingGroup(node) {
          if (this._handlers.onCapturingGroupEnter) {
            this._handlers.onCapturingGroupEnter(node);
          }
          node.alternatives.forEach(this.visit, this);
          if (this._handlers.onCapturingGroupLeave) {
            this._handlers.onCapturingGroupLeave(node);
          }
        }
        visitCharacter(node) {
          if (this._handlers.onCharacterEnter) {
            this._handlers.onCharacterEnter(node);
          }
          if (this._handlers.onCharacterLeave) {
            this._handlers.onCharacterLeave(node);
          }
        }
        visitCharacterClass(node) {
          if (this._handlers.onCharacterClassEnter) {
            this._handlers.onCharacterClassEnter(node);
          }
          node.elements.forEach(this.visit, this);
          if (this._handlers.onCharacterClassLeave) {
            this._handlers.onCharacterClassLeave(node);
          }
        }
        visitCharacterClassRange(node) {
          if (this._handlers.onCharacterClassRangeEnter) {
            this._handlers.onCharacterClassRangeEnter(node);
          }
          this.visitCharacter(node.min);
          this.visitCharacter(node.max);
          if (this._handlers.onCharacterClassRangeLeave) {
            this._handlers.onCharacterClassRangeLeave(node);
          }
        }
        visitCharacterSet(node) {
          if (this._handlers.onCharacterSetEnter) {
            this._handlers.onCharacterSetEnter(node);
          }
          if (this._handlers.onCharacterSetLeave) {
            this._handlers.onCharacterSetLeave(node);
          }
        }
        visitClassIntersection(node) {
          if (this._handlers.onClassIntersectionEnter) {
            this._handlers.onClassIntersectionEnter(node);
          }
          this.visit(node.left);
          this.visit(node.right);
          if (this._handlers.onClassIntersectionLeave) {
            this._handlers.onClassIntersectionLeave(node);
          }
        }
        visitClassStringDisjunction(node) {
          if (this._handlers.onClassStringDisjunctionEnter) {
            this._handlers.onClassStringDisjunctionEnter(node);
          }
          node.alternatives.forEach(this.visit, this);
          if (this._handlers.onClassStringDisjunctionLeave) {
            this._handlers.onClassStringDisjunctionLeave(node);
          }
        }
        visitClassSubtraction(node) {
          if (this._handlers.onClassSubtractionEnter) {
            this._handlers.onClassSubtractionEnter(node);
          }
          this.visit(node.left);
          this.visit(node.right);
          if (this._handlers.onClassSubtractionLeave) {
            this._handlers.onClassSubtractionLeave(node);
          }
        }
        visitExpressionCharacterClass(node) {
          if (this._handlers.onExpressionCharacterClassEnter) {
            this._handlers.onExpressionCharacterClassEnter(node);
          }
          this.visit(node.expression);
          if (this._handlers.onExpressionCharacterClassLeave) {
            this._handlers.onExpressionCharacterClassLeave(node);
          }
        }
        visitFlags(node) {
          if (this._handlers.onFlagsEnter) {
            this._handlers.onFlagsEnter(node);
          }
          if (this._handlers.onFlagsLeave) {
            this._handlers.onFlagsLeave(node);
          }
        }
        visitGroup(node) {
          if (this._handlers.onGroupEnter) {
            this._handlers.onGroupEnter(node);
          }
          if (node.modifiers) {
            this.visit(node.modifiers);
          }
          node.alternatives.forEach(this.visit, this);
          if (this._handlers.onGroupLeave) {
            this._handlers.onGroupLeave(node);
          }
        }
        visitModifiers(node) {
          if (this._handlers.onModifiersEnter) {
            this._handlers.onModifiersEnter(node);
          }
          if (node.add) {
            this.visit(node.add);
          }
          if (node.remove) {
            this.visit(node.remove);
          }
          if (this._handlers.onModifiersLeave) {
            this._handlers.onModifiersLeave(node);
          }
        }
        visitModifierFlags(node) {
          if (this._handlers.onModifierFlagsEnter) {
            this._handlers.onModifierFlagsEnter(node);
          }
          if (this._handlers.onModifierFlagsLeave) {
            this._handlers.onModifierFlagsLeave(node);
          }
        }
        visitPattern(node) {
          if (this._handlers.onPatternEnter) {
            this._handlers.onPatternEnter(node);
          }
          node.alternatives.forEach(this.visit, this);
          if (this._handlers.onPatternLeave) {
            this._handlers.onPatternLeave(node);
          }
        }
        visitQuantifier(node) {
          if (this._handlers.onQuantifierEnter) {
            this._handlers.onQuantifierEnter(node);
          }
          this.visit(node.element);
          if (this._handlers.onQuantifierLeave) {
            this._handlers.onQuantifierLeave(node);
          }
        }
        visitRegExpLiteral(node) {
          if (this._handlers.onRegExpLiteralEnter) {
            this._handlers.onRegExpLiteralEnter(node);
          }
          this.visitPattern(node.pattern);
          this.visitFlags(node.flags);
          if (this._handlers.onRegExpLiteralLeave) {
            this._handlers.onRegExpLiteralLeave(node);
          }
        }
        visitStringAlternative(node) {
          if (this._handlers.onStringAlternativeEnter) {
            this._handlers.onStringAlternativeEnter(node);
          }
          node.elements.forEach(this.visit, this);
          if (this._handlers.onStringAlternativeLeave) {
            this._handlers.onStringAlternativeLeave(node);
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/code.js
  var require_code = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/code.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.regexpCode = exports.getEsmExportName = exports.getProperty = exports.safeStringify = exports.stringify = exports.strConcat = exports.addCodeArg = exports.str = exports._ = exports.nil = exports._Code = exports.Name = exports.IDENTIFIER = exports._CodeOrName = void 0;
      var _CodeOrName = class {
      };
      exports._CodeOrName = _CodeOrName;
      exports.IDENTIFIER = /^[a-z$_][a-z$_0-9]*$/i;
      var Name = class extends _CodeOrName {
        constructor(s) {
          super();
          if (!exports.IDENTIFIER.test(s))
            throw new Error("CodeGen: name must be a valid identifier");
          this.str = s;
        }
        toString() {
          return this.str;
        }
        emptyStr() {
          return false;
        }
        get names() {
          return { [this.str]: 1 };
        }
      };
      exports.Name = Name;
      var _Code = class extends _CodeOrName {
        constructor(code) {
          super();
          this._items = typeof code === "string" ? [code] : code;
        }
        toString() {
          return this.str;
        }
        emptyStr() {
          if (this._items.length > 1)
            return false;
          const item = this._items[0];
          return item === "" || item === '""';
        }
        get str() {
          var _a;
          return (_a = this._str) !== null && _a !== void 0 ? _a : this._str = this._items.reduce((s, c) => `${s}${c}`, "");
        }
        get names() {
          var _a;
          return (_a = this._names) !== null && _a !== void 0 ? _a : this._names = this._items.reduce((names, c) => {
            if (c instanceof Name)
              names[c.str] = (names[c.str] || 0) + 1;
            return names;
          }, {});
        }
      };
      exports._Code = _Code;
      exports.nil = new _Code("");
      function _(strs, ...args) {
        const code = [strs[0]];
        let i = 0;
        while (i < args.length) {
          addCodeArg(code, args[i]);
          code.push(strs[++i]);
        }
        return new _Code(code);
      }
      exports._ = _;
      var plus = new _Code("+");
      function str(strs, ...args) {
        const expr = [safeStringify(strs[0])];
        let i = 0;
        while (i < args.length) {
          expr.push(plus);
          addCodeArg(expr, args[i]);
          expr.push(plus, safeStringify(strs[++i]));
        }
        optimize(expr);
        return new _Code(expr);
      }
      exports.str = str;
      function addCodeArg(code, arg) {
        if (arg instanceof _Code)
          code.push(...arg._items);
        else if (arg instanceof Name)
          code.push(arg);
        else
          code.push(interpolate(arg));
      }
      exports.addCodeArg = addCodeArg;
      function optimize(expr) {
        let i = 1;
        while (i < expr.length - 1) {
          if (expr[i] === plus) {
            const res = mergeExprItems(expr[i - 1], expr[i + 1]);
            if (res !== void 0) {
              expr.splice(i - 1, 3, res);
              continue;
            }
            expr[i++] = "+";
          }
          i++;
        }
      }
      function mergeExprItems(a, b) {
        if (b === '""')
          return a;
        if (a === '""')
          return b;
        if (typeof a == "string") {
          if (b instanceof Name || a[a.length - 1] !== '"')
            return;
          if (typeof b != "string")
            return `${a.slice(0, -1)}${b}"`;
          if (b[0] === '"')
            return a.slice(0, -1) + b.slice(1);
          return;
        }
        if (typeof b == "string" && b[0] === '"' && !(a instanceof Name))
          return `"${a}${b.slice(1)}`;
        return;
      }
      function strConcat(c1, c2) {
        return c2.emptyStr() ? c1 : c1.emptyStr() ? c2 : str`${c1}${c2}`;
      }
      exports.strConcat = strConcat;
      function interpolate(x) {
        return typeof x == "number" || typeof x == "boolean" || x === null ? x : safeStringify(Array.isArray(x) ? x.join(",") : x);
      }
      function stringify(x) {
        return new _Code(safeStringify(x));
      }
      exports.stringify = stringify;
      function safeStringify(x) {
        return JSON.stringify(x).replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
      }
      exports.safeStringify = safeStringify;
      function getProperty(key) {
        return typeof key == "string" && exports.IDENTIFIER.test(key) ? new _Code(`.${key}`) : _`[${key}]`;
      }
      exports.getProperty = getProperty;
      function getEsmExportName(key) {
        if (typeof key == "string" && exports.IDENTIFIER.test(key)) {
          return new _Code(`${key}`);
        }
        throw new Error(`CodeGen: invalid export name: ${key}, use explicit $id name mapping`);
      }
      exports.getEsmExportName = getEsmExportName;
      function regexpCode(rx) {
        return new _Code(rx.toString());
      }
      exports.regexpCode = regexpCode;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/scope.js
  var require_scope = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/scope.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.ValueScope = exports.ValueScopeName = exports.Scope = exports.varKinds = exports.UsedValueState = void 0;
      var code_1 = require_code();
      var ValueError = class extends Error {
        constructor(name) {
          super(`CodeGen: "code" for ${name} not defined`);
          this.value = name.value;
        }
      };
      var UsedValueState;
      (function(UsedValueState2) {
        UsedValueState2[UsedValueState2["Started"] = 0] = "Started";
        UsedValueState2[UsedValueState2["Completed"] = 1] = "Completed";
      })(UsedValueState || (exports.UsedValueState = UsedValueState = {}));
      exports.varKinds = {
        const: new code_1.Name("const"),
        let: new code_1.Name("let"),
        var: new code_1.Name("var")
      };
      var Scope = class {
        constructor({ prefixes, parent } = {}) {
          this._names = {};
          this._prefixes = prefixes;
          this._parent = parent;
        }
        toName(nameOrPrefix) {
          return nameOrPrefix instanceof code_1.Name ? nameOrPrefix : this.name(nameOrPrefix);
        }
        name(prefix) {
          return new code_1.Name(this._newName(prefix));
        }
        _newName(prefix) {
          const ng = this._names[prefix] || this._nameGroup(prefix);
          return `${prefix}${ng.index++}`;
        }
        _nameGroup(prefix) {
          var _a, _b;
          if (((_b = (_a = this._parent) === null || _a === void 0 ? void 0 : _a._prefixes) === null || _b === void 0 ? void 0 : _b.has(prefix)) || this._prefixes && !this._prefixes.has(prefix)) {
            throw new Error(`CodeGen: prefix "${prefix}" is not allowed in this scope`);
          }
          return this._names[prefix] = { prefix, index: 0 };
        }
      };
      exports.Scope = Scope;
      var ValueScopeName = class extends code_1.Name {
        constructor(prefix, nameStr) {
          super(nameStr);
          this.prefix = prefix;
        }
        setValue(value, { property, itemIndex }) {
          this.value = value;
          this.scopePath = (0, code_1._)`.${new code_1.Name(property)}[${itemIndex}]`;
        }
      };
      exports.ValueScopeName = ValueScopeName;
      var line = (0, code_1._)`\n`;
      var ValueScope = class extends Scope {
        constructor(opts) {
          super(opts);
          this._values = {};
          this._scope = opts.scope;
          this.opts = { ...opts, _n: opts.lines ? line : code_1.nil };
        }
        get() {
          return this._scope;
        }
        name(prefix) {
          return new ValueScopeName(prefix, this._newName(prefix));
        }
        value(nameOrPrefix, value) {
          var _a;
          if (value.ref === void 0)
            throw new Error("CodeGen: ref must be passed in value");
          const name = this.toName(nameOrPrefix);
          const { prefix } = name;
          const valueKey = (_a = value.key) !== null && _a !== void 0 ? _a : value.ref;
          let vs = this._values[prefix];
          if (vs) {
            const _name = vs.get(valueKey);
            if (_name)
              return _name;
          } else {
            vs = this._values[prefix] = /* @__PURE__ */ new Map();
          }
          vs.set(valueKey, name);
          const s = this._scope[prefix] || (this._scope[prefix] = []);
          const itemIndex = s.length;
          s[itemIndex] = value.ref;
          name.setValue(value, { property: prefix, itemIndex });
          return name;
        }
        getValue(prefix, keyOrRef) {
          const vs = this._values[prefix];
          if (!vs)
            return;
          return vs.get(keyOrRef);
        }
        scopeRefs(scopeName, values = this._values) {
          return this._reduceValues(values, (name) => {
            if (name.scopePath === void 0)
              throw new Error(`CodeGen: name "${name}" has no value`);
            return (0, code_1._)`${scopeName}${name.scopePath}`;
          });
        }
        scopeCode(values = this._values, usedValues, getCode) {
          return this._reduceValues(values, (name) => {
            if (name.value === void 0)
              throw new Error(`CodeGen: name "${name}" has no value`);
            return name.value.code;
          }, usedValues, getCode);
        }
        _reduceValues(values, valueCode, usedValues = {}, getCode) {
          let code = code_1.nil;
          for (const prefix in values) {
            const vs = values[prefix];
            if (!vs)
              continue;
            const nameSet = usedValues[prefix] = usedValues[prefix] || /* @__PURE__ */ new Map();
            vs.forEach((name) => {
              if (nameSet.has(name))
                return;
              nameSet.set(name, UsedValueState.Started);
              let c = valueCode(name);
              if (c) {
                const def = this.opts.es5 ? exports.varKinds.var : exports.varKinds.const;
                code = (0, code_1._)`${code}${def} ${name} = ${c};${this.opts._n}`;
              } else if (c = getCode === null || getCode === void 0 ? void 0 : getCode(name)) {
                code = (0, code_1._)`${code}${c}${this.opts._n}`;
              } else {
                throw new ValueError(name);
              }
              nameSet.set(name, UsedValueState.Completed);
            });
          }
          return code;
        }
      };
      exports.ValueScope = ValueScope;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/index.js
  var require_codegen = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/codegen/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.or = exports.and = exports.not = exports.CodeGen = exports.operators = exports.varKinds = exports.ValueScopeName = exports.ValueScope = exports.Scope = exports.Name = exports.regexpCode = exports.stringify = exports.getProperty = exports.nil = exports.strConcat = exports.str = exports._ = void 0;
      var code_1 = require_code();
      var scope_1 = require_scope();
      var code_2 = require_code();
      Object.defineProperty(exports, "_", { enumerable: true, get: function() {
        return code_2._;
      } });
      Object.defineProperty(exports, "str", { enumerable: true, get: function() {
        return code_2.str;
      } });
      Object.defineProperty(exports, "strConcat", { enumerable: true, get: function() {
        return code_2.strConcat;
      } });
      Object.defineProperty(exports, "nil", { enumerable: true, get: function() {
        return code_2.nil;
      } });
      Object.defineProperty(exports, "getProperty", { enumerable: true, get: function() {
        return code_2.getProperty;
      } });
      Object.defineProperty(exports, "stringify", { enumerable: true, get: function() {
        return code_2.stringify;
      } });
      Object.defineProperty(exports, "regexpCode", { enumerable: true, get: function() {
        return code_2.regexpCode;
      } });
      Object.defineProperty(exports, "Name", { enumerable: true, get: function() {
        return code_2.Name;
      } });
      var scope_2 = require_scope();
      Object.defineProperty(exports, "Scope", { enumerable: true, get: function() {
        return scope_2.Scope;
      } });
      Object.defineProperty(exports, "ValueScope", { enumerable: true, get: function() {
        return scope_2.ValueScope;
      } });
      Object.defineProperty(exports, "ValueScopeName", { enumerable: true, get: function() {
        return scope_2.ValueScopeName;
      } });
      Object.defineProperty(exports, "varKinds", { enumerable: true, get: function() {
        return scope_2.varKinds;
      } });
      exports.operators = {
        GT: new code_1._Code(">"),
        GTE: new code_1._Code(">="),
        LT: new code_1._Code("<"),
        LTE: new code_1._Code("<="),
        EQ: new code_1._Code("==="),
        NEQ: new code_1._Code("!=="),
        NOT: new code_1._Code("!"),
        OR: new code_1._Code("||"),
        AND: new code_1._Code("&&"),
        ADD: new code_1._Code("+")
      };
      var Node = class {
        optimizeNodes() {
          return this;
        }
        optimizeNames(_names, _constants) {
          return this;
        }
      };
      var Def = class extends Node {
        constructor(varKind, name, rhs) {
          super();
          this.varKind = varKind;
          this.name = name;
          this.rhs = rhs;
        }
        render({ es5, _n }) {
          const varKind = es5 ? scope_1.varKinds.var : this.varKind;
          const rhs = this.rhs === void 0 ? "" : ` = ${this.rhs}`;
          return `${varKind} ${this.name}${rhs};` + _n;
        }
        optimizeNames(names, constants) {
          if (!names[this.name.str])
            return;
          if (this.rhs)
            this.rhs = optimizeExpr(this.rhs, names, constants);
          return this;
        }
        get names() {
          return this.rhs instanceof code_1._CodeOrName ? this.rhs.names : {};
        }
      };
      var Assign = class extends Node {
        constructor(lhs, rhs, sideEffects) {
          super();
          this.lhs = lhs;
          this.rhs = rhs;
          this.sideEffects = sideEffects;
        }
        render({ _n }) {
          return `${this.lhs} = ${this.rhs};` + _n;
        }
        optimizeNames(names, constants) {
          if (this.lhs instanceof code_1.Name && !names[this.lhs.str] && !this.sideEffects)
            return;
          this.rhs = optimizeExpr(this.rhs, names, constants);
          return this;
        }
        get names() {
          const names = this.lhs instanceof code_1.Name ? {} : { ...this.lhs.names };
          return addExprNames(names, this.rhs);
        }
      };
      var AssignOp = class extends Assign {
        constructor(lhs, op, rhs, sideEffects) {
          super(lhs, rhs, sideEffects);
          this.op = op;
        }
        render({ _n }) {
          return `${this.lhs} ${this.op}= ${this.rhs};` + _n;
        }
      };
      var Label = class extends Node {
        constructor(label) {
          super();
          this.label = label;
          this.names = {};
        }
        render({ _n }) {
          return `${this.label}:` + _n;
        }
      };
      var Break = class extends Node {
        constructor(label) {
          super();
          this.label = label;
          this.names = {};
        }
        render({ _n }) {
          const label = this.label ? ` ${this.label}` : "";
          return `break${label};` + _n;
        }
      };
      var Throw = class extends Node {
        constructor(error) {
          super();
          this.error = error;
        }
        render({ _n }) {
          return `throw ${this.error};` + _n;
        }
        get names() {
          return this.error.names;
        }
      };
      var AnyCode = class extends Node {
        constructor(code) {
          super();
          this.code = code;
        }
        render({ _n }) {
          return `${this.code};` + _n;
        }
        optimizeNodes() {
          return `${this.code}` ? this : void 0;
        }
        optimizeNames(names, constants) {
          this.code = optimizeExpr(this.code, names, constants);
          return this;
        }
        get names() {
          return this.code instanceof code_1._CodeOrName ? this.code.names : {};
        }
      };
      var ParentNode = class extends Node {
        constructor(nodes = []) {
          super();
          this.nodes = nodes;
        }
        render(opts) {
          return this.nodes.reduce((code, n) => code + n.render(opts), "");
        }
        optimizeNodes() {
          const { nodes } = this;
          let i = nodes.length;
          while (i--) {
            const n = nodes[i].optimizeNodes();
            if (Array.isArray(n))
              nodes.splice(i, 1, ...n);
            else if (n)
              nodes[i] = n;
            else
              nodes.splice(i, 1);
          }
          return nodes.length > 0 ? this : void 0;
        }
        optimizeNames(names, constants) {
          const { nodes } = this;
          let i = nodes.length;
          while (i--) {
            const n = nodes[i];
            if (n.optimizeNames(names, constants))
              continue;
            subtractNames(names, n.names);
            nodes.splice(i, 1);
          }
          return nodes.length > 0 ? this : void 0;
        }
        get names() {
          return this.nodes.reduce((names, n) => addNames(names, n.names), {});
        }
      };
      var BlockNode = class extends ParentNode {
        render(opts) {
          return "{" + opts._n + super.render(opts) + "}" + opts._n;
        }
      };
      var Root = class extends ParentNode {
      };
      var Else = class extends BlockNode {
      };
      Else.kind = "else";
      var If = class _If extends BlockNode {
        constructor(condition, nodes) {
          super(nodes);
          this.condition = condition;
        }
        render(opts) {
          let code = `if(${this.condition})` + super.render(opts);
          if (this.else)
            code += "else " + this.else.render(opts);
          return code;
        }
        optimizeNodes() {
          super.optimizeNodes();
          const cond = this.condition;
          if (cond === true)
            return this.nodes;
          let e = this.else;
          if (e) {
            const ns = e.optimizeNodes();
            e = this.else = Array.isArray(ns) ? new Else(ns) : ns;
          }
          if (e) {
            if (cond === false)
              return e instanceof _If ? e : e.nodes;
            if (this.nodes.length)
              return this;
            return new _If(not(cond), e instanceof _If ? [e] : e.nodes);
          }
          if (cond === false || !this.nodes.length)
            return void 0;
          return this;
        }
        optimizeNames(names, constants) {
          var _a;
          this.else = (_a = this.else) === null || _a === void 0 ? void 0 : _a.optimizeNames(names, constants);
          if (!(super.optimizeNames(names, constants) || this.else))
            return;
          this.condition = optimizeExpr(this.condition, names, constants);
          return this;
        }
        get names() {
          const names = super.names;
          addExprNames(names, this.condition);
          if (this.else)
            addNames(names, this.else.names);
          return names;
        }
      };
      If.kind = "if";
      var For = class extends BlockNode {
      };
      For.kind = "for";
      var ForLoop = class extends For {
        constructor(iteration) {
          super();
          this.iteration = iteration;
        }
        render(opts) {
          return `for(${this.iteration})` + super.render(opts);
        }
        optimizeNames(names, constants) {
          if (!super.optimizeNames(names, constants))
            return;
          this.iteration = optimizeExpr(this.iteration, names, constants);
          return this;
        }
        get names() {
          return addNames(super.names, this.iteration.names);
        }
      };
      var ForRange = class extends For {
        constructor(varKind, name, from, to) {
          super();
          this.varKind = varKind;
          this.name = name;
          this.from = from;
          this.to = to;
        }
        render(opts) {
          const varKind = opts.es5 ? scope_1.varKinds.var : this.varKind;
          const { name, from, to } = this;
          return `for(${varKind} ${name}=${from}; ${name}<${to}; ${name}++)` + super.render(opts);
        }
        get names() {
          const names = addExprNames(super.names, this.from);
          return addExprNames(names, this.to);
        }
      };
      var ForIter = class extends For {
        constructor(loop, varKind, name, iterable) {
          super();
          this.loop = loop;
          this.varKind = varKind;
          this.name = name;
          this.iterable = iterable;
        }
        render(opts) {
          return `for(${this.varKind} ${this.name} ${this.loop} ${this.iterable})` + super.render(opts);
        }
        optimizeNames(names, constants) {
          if (!super.optimizeNames(names, constants))
            return;
          this.iterable = optimizeExpr(this.iterable, names, constants);
          return this;
        }
        get names() {
          return addNames(super.names, this.iterable.names);
        }
      };
      var Func = class extends BlockNode {
        constructor(name, args, async) {
          super();
          this.name = name;
          this.args = args;
          this.async = async;
        }
        render(opts) {
          const _async = this.async ? "async " : "";
          return `${_async}function ${this.name}(${this.args})` + super.render(opts);
        }
      };
      Func.kind = "func";
      var Return = class extends ParentNode {
        render(opts) {
          return "return " + super.render(opts);
        }
      };
      Return.kind = "return";
      var Try = class extends BlockNode {
        render(opts) {
          let code = "try" + super.render(opts);
          if (this.catch)
            code += this.catch.render(opts);
          if (this.finally)
            code += this.finally.render(opts);
          return code;
        }
        optimizeNodes() {
          var _a, _b;
          super.optimizeNodes();
          (_a = this.catch) === null || _a === void 0 ? void 0 : _a.optimizeNodes();
          (_b = this.finally) === null || _b === void 0 ? void 0 : _b.optimizeNodes();
          return this;
        }
        optimizeNames(names, constants) {
          var _a, _b;
          super.optimizeNames(names, constants);
          (_a = this.catch) === null || _a === void 0 ? void 0 : _a.optimizeNames(names, constants);
          (_b = this.finally) === null || _b === void 0 ? void 0 : _b.optimizeNames(names, constants);
          return this;
        }
        get names() {
          const names = super.names;
          if (this.catch)
            addNames(names, this.catch.names);
          if (this.finally)
            addNames(names, this.finally.names);
          return names;
        }
      };
      var Catch = class extends BlockNode {
        constructor(error) {
          super();
          this.error = error;
        }
        render(opts) {
          return `catch(${this.error})` + super.render(opts);
        }
      };
      Catch.kind = "catch";
      var Finally = class extends BlockNode {
        render(opts) {
          return "finally" + super.render(opts);
        }
      };
      Finally.kind = "finally";
      var CodeGen = class {
        constructor(extScope, opts = {}) {
          this._values = {};
          this._blockStarts = [];
          this._constants = {};
          this.opts = { ...opts, _n: opts.lines ? "\n" : "" };
          this._extScope = extScope;
          this._scope = new scope_1.Scope({ parent: extScope });
          this._nodes = [new Root()];
        }
        toString() {
          return this._root.render(this.opts);
        }
        // returns unique name in the internal scope
        name(prefix) {
          return this._scope.name(prefix);
        }
        // reserves unique name in the external scope
        scopeName(prefix) {
          return this._extScope.name(prefix);
        }
        // reserves unique name in the external scope and assigns value to it
        scopeValue(prefixOrName, value) {
          const name = this._extScope.value(prefixOrName, value);
          const vs = this._values[name.prefix] || (this._values[name.prefix] = /* @__PURE__ */ new Set());
          vs.add(name);
          return name;
        }
        getScopeValue(prefix, keyOrRef) {
          return this._extScope.getValue(prefix, keyOrRef);
        }
        // return code that assigns values in the external scope to the names that are used internally
        // (same names that were returned by gen.scopeName or gen.scopeValue)
        scopeRefs(scopeName) {
          return this._extScope.scopeRefs(scopeName, this._values);
        }
        scopeCode() {
          return this._extScope.scopeCode(this._values);
        }
        _def(varKind, nameOrPrefix, rhs, constant2) {
          const name = this._scope.toName(nameOrPrefix);
          if (rhs !== void 0 && constant2)
            this._constants[name.str] = rhs;
          this._leafNode(new Def(varKind, name, rhs));
          return name;
        }
        // `const` declaration (`var` in es5 mode)
        const(nameOrPrefix, rhs, _constant) {
          return this._def(scope_1.varKinds.const, nameOrPrefix, rhs, _constant);
        }
        // `let` declaration with optional assignment (`var` in es5 mode)
        let(nameOrPrefix, rhs, _constant) {
          return this._def(scope_1.varKinds.let, nameOrPrefix, rhs, _constant);
        }
        // `var` declaration with optional assignment
        var(nameOrPrefix, rhs, _constant) {
          return this._def(scope_1.varKinds.var, nameOrPrefix, rhs, _constant);
        }
        // assignment code
        assign(lhs, rhs, sideEffects) {
          return this._leafNode(new Assign(lhs, rhs, sideEffects));
        }
        // `+=` code
        add(lhs, rhs) {
          return this._leafNode(new AssignOp(lhs, exports.operators.ADD, rhs));
        }
        // appends passed SafeExpr to code or executes Block
        code(c) {
          if (typeof c == "function")
            c();
          else if (c !== code_1.nil)
            this._leafNode(new AnyCode(c));
          return this;
        }
        // returns code for object literal for the passed argument list of key-value pairs
        object(...keyValues) {
          const code = ["{"];
          for (const [key, value] of keyValues) {
            if (code.length > 1)
              code.push(",");
            code.push(key);
            if (key !== value || this.opts.es5) {
              code.push(":");
              (0, code_1.addCodeArg)(code, value);
            }
          }
          code.push("}");
          return new code_1._Code(code);
        }
        // `if` clause (or statement if `thenBody` and, optionally, `elseBody` are passed)
        if(condition, thenBody, elseBody) {
          this._blockNode(new If(condition));
          if (thenBody && elseBody) {
            this.code(thenBody).else().code(elseBody).endIf();
          } else if (thenBody) {
            this.code(thenBody).endIf();
          } else if (elseBody) {
            throw new Error('CodeGen: "else" body without "then" body');
          }
          return this;
        }
        // `else if` clause - invalid without `if` or after `else` clauses
        elseIf(condition) {
          return this._elseNode(new If(condition));
        }
        // `else` clause - only valid after `if` or `else if` clauses
        else() {
          return this._elseNode(new Else());
        }
        // end `if` statement (needed if gen.if was used only with condition)
        endIf() {
          return this._endBlockNode(If, Else);
        }
        _for(node, forBody) {
          this._blockNode(node);
          if (forBody)
            this.code(forBody).endFor();
          return this;
        }
        // a generic `for` clause (or statement if `forBody` is passed)
        for(iteration, forBody) {
          return this._for(new ForLoop(iteration), forBody);
        }
        // `for` statement for a range of values
        forRange(nameOrPrefix, from, to, forBody, varKind = this.opts.es5 ? scope_1.varKinds.var : scope_1.varKinds.let) {
          const name = this._scope.toName(nameOrPrefix);
          return this._for(new ForRange(varKind, name, from, to), () => forBody(name));
        }
        // `for-of` statement (in es5 mode replace with a normal for loop)
        forOf(nameOrPrefix, iterable, forBody, varKind = scope_1.varKinds.const) {
          const name = this._scope.toName(nameOrPrefix);
          if (this.opts.es5) {
            const arr = iterable instanceof code_1.Name ? iterable : this.var("_arr", iterable);
            return this.forRange("_i", 0, (0, code_1._)`${arr}.length`, (i) => {
              this.var(name, (0, code_1._)`${arr}[${i}]`);
              forBody(name);
            });
          }
          return this._for(new ForIter("of", varKind, name, iterable), () => forBody(name));
        }
        // `for-in` statement.
        // With option `ownProperties` replaced with a `for-of` loop for object keys
        forIn(nameOrPrefix, obj, forBody, varKind = this.opts.es5 ? scope_1.varKinds.var : scope_1.varKinds.const) {
          if (this.opts.ownProperties) {
            return this.forOf(nameOrPrefix, (0, code_1._)`Object.keys(${obj})`, forBody);
          }
          const name = this._scope.toName(nameOrPrefix);
          return this._for(new ForIter("in", varKind, name, obj), () => forBody(name));
        }
        // end `for` loop
        endFor() {
          return this._endBlockNode(For);
        }
        // `label` statement
        label(label) {
          return this._leafNode(new Label(label));
        }
        // `break` statement
        break(label) {
          return this._leafNode(new Break(label));
        }
        // `return` statement
        return(value) {
          const node = new Return();
          this._blockNode(node);
          this.code(value);
          if (node.nodes.length !== 1)
            throw new Error('CodeGen: "return" should have one node');
          return this._endBlockNode(Return);
        }
        // `try` statement
        try(tryBody, catchCode, finallyCode) {
          if (!catchCode && !finallyCode)
            throw new Error('CodeGen: "try" without "catch" and "finally"');
          const node = new Try();
          this._blockNode(node);
          this.code(tryBody);
          if (catchCode) {
            const error = this.name("e");
            this._currNode = node.catch = new Catch(error);
            catchCode(error);
          }
          if (finallyCode) {
            this._currNode = node.finally = new Finally();
            this.code(finallyCode);
          }
          return this._endBlockNode(Catch, Finally);
        }
        // `throw` statement
        throw(error) {
          return this._leafNode(new Throw(error));
        }
        // start self-balancing block
        block(body, nodeCount) {
          this._blockStarts.push(this._nodes.length);
          if (body)
            this.code(body).endBlock(nodeCount);
          return this;
        }
        // end the current self-balancing block
        endBlock(nodeCount) {
          const len = this._blockStarts.pop();
          if (len === void 0)
            throw new Error("CodeGen: not in self-balancing block");
          const toClose = this._nodes.length - len;
          if (toClose < 0 || nodeCount !== void 0 && toClose !== nodeCount) {
            throw new Error(`CodeGen: wrong number of nodes: ${toClose} vs ${nodeCount} expected`);
          }
          this._nodes.length = len;
          return this;
        }
        // `function` heading (or definition if funcBody is passed)
        func(name, args = code_1.nil, async, funcBody) {
          this._blockNode(new Func(name, args, async));
          if (funcBody)
            this.code(funcBody).endFunc();
          return this;
        }
        // end function definition
        endFunc() {
          return this._endBlockNode(Func);
        }
        optimize(n = 1) {
          while (n-- > 0) {
            this._root.optimizeNodes();
            this._root.optimizeNames(this._root.names, this._constants);
          }
        }
        _leafNode(node) {
          this._currNode.nodes.push(node);
          return this;
        }
        _blockNode(node) {
          this._currNode.nodes.push(node);
          this._nodes.push(node);
        }
        _endBlockNode(N1, N2) {
          const n = this._currNode;
          if (n instanceof N1 || N2 && n instanceof N2) {
            this._nodes.pop();
            return this;
          }
          throw new Error(`CodeGen: not in block "${N2 ? `${N1.kind}/${N2.kind}` : N1.kind}"`);
        }
        _elseNode(node) {
          const n = this._currNode;
          if (!(n instanceof If)) {
            throw new Error('CodeGen: "else" without "if"');
          }
          this._currNode = n.else = node;
          return this;
        }
        get _root() {
          return this._nodes[0];
        }
        get _currNode() {
          const ns = this._nodes;
          return ns[ns.length - 1];
        }
        set _currNode(node) {
          const ns = this._nodes;
          ns[ns.length - 1] = node;
        }
      };
      exports.CodeGen = CodeGen;
      function addNames(names, from) {
        for (const n in from)
          names[n] = (names[n] || 0) + (from[n] || 0);
        return names;
      }
      function addExprNames(names, from) {
        return from instanceof code_1._CodeOrName ? addNames(names, from.names) : names;
      }
      function optimizeExpr(expr, names, constants) {
        if (expr instanceof code_1.Name)
          return replaceName(expr);
        if (!canOptimize(expr))
          return expr;
        return new code_1._Code(expr._items.reduce((items, c) => {
          if (c instanceof code_1.Name)
            c = replaceName(c);
          if (c instanceof code_1._Code)
            items.push(...c._items);
          else
            items.push(c);
          return items;
        }, []));
        function replaceName(n) {
          const c = constants[n.str];
          if (c === void 0 || names[n.str] !== 1)
            return n;
          delete names[n.str];
          return c;
        }
        function canOptimize(e) {
          return e instanceof code_1._Code && e._items.some((c) => c instanceof code_1.Name && names[c.str] === 1 && constants[c.str] !== void 0);
        }
      }
      function subtractNames(names, from) {
        for (const n in from)
          names[n] = (names[n] || 0) - (from[n] || 0);
      }
      function not(x) {
        return typeof x == "boolean" || typeof x == "number" || x === null ? !x : (0, code_1._)`!${par(x)}`;
      }
      exports.not = not;
      var andCode = mappend(exports.operators.AND);
      function and(...args) {
        return args.reduce(andCode);
      }
      exports.and = and;
      var orCode = mappend(exports.operators.OR);
      function or(...args) {
        return args.reduce(orCode);
      }
      exports.or = or;
      function mappend(op) {
        return (x, y) => x === code_1.nil ? y : y === code_1.nil ? x : (0, code_1._)`${par(x)} ${op} ${par(y)}`;
      }
      function par(x) {
        return x instanceof code_1.Name ? x : (0, code_1._)`(${x})`;
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/util.js
  var require_util = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/util.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.checkStrictMode = exports.getErrorPath = exports.Type = exports.useFunc = exports.setEvaluated = exports.evaluatedPropsToName = exports.mergeEvaluated = exports.eachItem = exports.unescapeJsonPointer = exports.escapeJsonPointer = exports.escapeFragment = exports.unescapeFragment = exports.schemaRefOrVal = exports.schemaHasRulesButRef = exports.schemaHasRules = exports.checkUnknownRules = exports.alwaysValidSchema = exports.toHash = void 0;
      var codegen_1 = require_codegen();
      var code_1 = require_code();
      function toHash(arr) {
        const hash = {};
        for (const item of arr)
          hash[item] = true;
        return hash;
      }
      exports.toHash = toHash;
      function alwaysValidSchema(it, schema) {
        if (typeof schema == "boolean")
          return schema;
        if (Object.keys(schema).length === 0)
          return true;
        checkUnknownRules(it, schema);
        return !schemaHasRules(schema, it.self.RULES.all);
      }
      exports.alwaysValidSchema = alwaysValidSchema;
      function checkUnknownRules(it, schema = it.schema) {
        const { opts, self } = it;
        if (!opts.strictSchema)
          return;
        if (typeof schema === "boolean")
          return;
        const rules = self.RULES.keywords;
        for (const key in schema) {
          if (!rules[key])
            checkStrictMode(it, `unknown keyword: "${key}"`);
        }
      }
      exports.checkUnknownRules = checkUnknownRules;
      function schemaHasRules(schema, rules) {
        if (typeof schema == "boolean")
          return !schema;
        for (const key in schema)
          if (rules[key])
            return true;
        return false;
      }
      exports.schemaHasRules = schemaHasRules;
      function schemaHasRulesButRef(schema, RULES) {
        if (typeof schema == "boolean")
          return !schema;
        for (const key in schema)
          if (key !== "$ref" && RULES.all[key])
            return true;
        return false;
      }
      exports.schemaHasRulesButRef = schemaHasRulesButRef;
      function schemaRefOrVal({ topSchemaRef, schemaPath }, schema, keyword, $data) {
        if (!$data) {
          if (typeof schema == "number" || typeof schema == "boolean")
            return schema;
          if (typeof schema == "string")
            return (0, codegen_1._)`${schema}`;
        }
        return (0, codegen_1._)`${topSchemaRef}${schemaPath}${(0, codegen_1.getProperty)(keyword)}`;
      }
      exports.schemaRefOrVal = schemaRefOrVal;
      function unescapeFragment(str) {
        return unescapeJsonPointer(decodeURIComponent(str));
      }
      exports.unescapeFragment = unescapeFragment;
      function escapeFragment(str) {
        return encodeURIComponent(escapeJsonPointer(str));
      }
      exports.escapeFragment = escapeFragment;
      function escapeJsonPointer(str) {
        if (typeof str == "number")
          return `${str}`;
        return str.replace(/~/g, "~0").replace(/\//g, "~1");
      }
      exports.escapeJsonPointer = escapeJsonPointer;
      function unescapeJsonPointer(str) {
        return str.replace(/~1/g, "/").replace(/~0/g, "~");
      }
      exports.unescapeJsonPointer = unescapeJsonPointer;
      function eachItem(xs, f) {
        if (Array.isArray(xs)) {
          for (const x of xs)
            f(x);
        } else {
          f(xs);
        }
      }
      exports.eachItem = eachItem;
      function makeMergeEvaluated({ mergeNames, mergeToName, mergeValues, resultToName }) {
        return (gen, from, to, toName) => {
          const res = to === void 0 ? from : to instanceof codegen_1.Name ? (from instanceof codegen_1.Name ? mergeNames(gen, from, to) : mergeToName(gen, from, to), to) : from instanceof codegen_1.Name ? (mergeToName(gen, to, from), from) : mergeValues(from, to);
          return toName === codegen_1.Name && !(res instanceof codegen_1.Name) ? resultToName(gen, res) : res;
        };
      }
      exports.mergeEvaluated = {
        props: makeMergeEvaluated({
          mergeNames: (gen, from, to) => gen.if((0, codegen_1._)`${to} !== true && ${from} !== undefined`, () => {
            gen.if((0, codegen_1._)`${from} === true`, () => gen.assign(to, true), () => gen.assign(to, (0, codegen_1._)`${to} || {}`).code((0, codegen_1._)`Object.assign(${to}, ${from})`));
          }),
          mergeToName: (gen, from, to) => gen.if((0, codegen_1._)`${to} !== true`, () => {
            if (from === true) {
              gen.assign(to, true);
            } else {
              gen.assign(to, (0, codegen_1._)`${to} || {}`);
              setEvaluated(gen, to, from);
            }
          }),
          mergeValues: (from, to) => from === true ? true : { ...from, ...to },
          resultToName: evaluatedPropsToName
        }),
        items: makeMergeEvaluated({
          mergeNames: (gen, from, to) => gen.if((0, codegen_1._)`${to} !== true && ${from} !== undefined`, () => gen.assign(to, (0, codegen_1._)`${from} === true ? true : ${to} > ${from} ? ${to} : ${from}`)),
          mergeToName: (gen, from, to) => gen.if((0, codegen_1._)`${to} !== true`, () => gen.assign(to, from === true ? true : (0, codegen_1._)`${to} > ${from} ? ${to} : ${from}`)),
          mergeValues: (from, to) => from === true ? true : Math.max(from, to),
          resultToName: (gen, items) => gen.var("items", items)
        })
      };
      function evaluatedPropsToName(gen, ps) {
        if (ps === true)
          return gen.var("props", true);
        const props = gen.var("props", (0, codegen_1._)`{}`);
        if (ps !== void 0)
          setEvaluated(gen, props, ps);
        return props;
      }
      exports.evaluatedPropsToName = evaluatedPropsToName;
      function setEvaluated(gen, props, ps) {
        Object.keys(ps).forEach((p) => gen.assign((0, codegen_1._)`${props}${(0, codegen_1.getProperty)(p)}`, true));
      }
      exports.setEvaluated = setEvaluated;
      var snippets = {};
      function useFunc(gen, f) {
        return gen.scopeValue("func", {
          ref: f,
          code: snippets[f.code] || (snippets[f.code] = new code_1._Code(f.code))
        });
      }
      exports.useFunc = useFunc;
      var Type;
      (function(Type2) {
        Type2[Type2["Num"] = 0] = "Num";
        Type2[Type2["Str"] = 1] = "Str";
      })(Type || (exports.Type = Type = {}));
      function getErrorPath(dataProp, dataPropType, jsPropertySyntax) {
        if (dataProp instanceof codegen_1.Name) {
          const isNumber = dataPropType === Type.Num;
          return jsPropertySyntax ? isNumber ? (0, codegen_1._)`"[" + ${dataProp} + "]"` : (0, codegen_1._)`"['" + ${dataProp} + "']"` : isNumber ? (0, codegen_1._)`"/" + ${dataProp}` : (0, codegen_1._)`"/" + ${dataProp}.replace(/~/g, "~0").replace(/\\//g, "~1")`;
        }
        return jsPropertySyntax ? (0, codegen_1.getProperty)(dataProp).toString() : "/" + escapeJsonPointer(dataProp);
      }
      exports.getErrorPath = getErrorPath;
      function checkStrictMode(it, msg, mode = it.opts.strictSchema) {
        if (!mode)
          return;
        msg = `strict mode: ${msg}`;
        if (mode === true)
          throw new Error(msg);
        it.self.logger.warn(msg);
      }
      exports.checkStrictMode = checkStrictMode;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/names.js
  var require_names = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/names.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var names = {
        // validation function arguments
        data: new codegen_1.Name("data"),
        // data passed to validation function
        // args passed from referencing schema
        valCxt: new codegen_1.Name("valCxt"),
        // validation/data context - should not be used directly, it is destructured to the names below
        instancePath: new codegen_1.Name("instancePath"),
        parentData: new codegen_1.Name("parentData"),
        parentDataProperty: new codegen_1.Name("parentDataProperty"),
        rootData: new codegen_1.Name("rootData"),
        // root data - same as the data passed to the first/top validation function
        dynamicAnchors: new codegen_1.Name("dynamicAnchors"),
        // used to support recursiveRef and dynamicRef
        // function scoped variables
        vErrors: new codegen_1.Name("vErrors"),
        // null or array of validation errors
        errors: new codegen_1.Name("errors"),
        // counter of validation errors
        this: new codegen_1.Name("this"),
        // "globals"
        self: new codegen_1.Name("self"),
        scope: new codegen_1.Name("scope"),
        // JTD serialize/parse name for JSON string and position
        json: new codegen_1.Name("json"),
        jsonPos: new codegen_1.Name("jsonPos"),
        jsonLen: new codegen_1.Name("jsonLen"),
        jsonPart: new codegen_1.Name("jsonPart")
      };
      exports.default = names;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/errors.js
  var require_errors = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/errors.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.extendErrors = exports.resetErrorsCount = exports.reportExtraError = exports.reportError = exports.keyword$DataError = exports.keywordError = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var names_1 = require_names();
      exports.keywordError = {
        message: ({ keyword }) => (0, codegen_1.str)`must pass "${keyword}" keyword validation`
      };
      exports.keyword$DataError = {
        message: ({ keyword, schemaType }) => schemaType ? (0, codegen_1.str)`"${keyword}" keyword must be ${schemaType} ($data)` : (0, codegen_1.str)`"${keyword}" keyword is invalid ($data)`
      };
      function reportError(cxt, error = exports.keywordError, errorPaths, overrideAllErrors) {
        const { it } = cxt;
        const { gen, compositeRule, allErrors } = it;
        const errObj = errorObjectCode(cxt, error, errorPaths);
        if (overrideAllErrors !== null && overrideAllErrors !== void 0 ? overrideAllErrors : compositeRule || allErrors) {
          addError(gen, errObj);
        } else {
          returnErrors(it, (0, codegen_1._)`[${errObj}]`);
        }
      }
      exports.reportError = reportError;
      function reportExtraError(cxt, error = exports.keywordError, errorPaths) {
        const { it } = cxt;
        const { gen, compositeRule, allErrors } = it;
        const errObj = errorObjectCode(cxt, error, errorPaths);
        addError(gen, errObj);
        if (!(compositeRule || allErrors)) {
          returnErrors(it, names_1.default.vErrors);
        }
      }
      exports.reportExtraError = reportExtraError;
      function resetErrorsCount(gen, errsCount) {
        gen.assign(names_1.default.errors, errsCount);
        gen.if((0, codegen_1._)`${names_1.default.vErrors} !== null`, () => gen.if(errsCount, () => gen.assign((0, codegen_1._)`${names_1.default.vErrors}.length`, errsCount), () => gen.assign(names_1.default.vErrors, null)));
      }
      exports.resetErrorsCount = resetErrorsCount;
      function extendErrors({ gen, keyword, schemaValue, data, errsCount, it }) {
        if (errsCount === void 0)
          throw new Error("ajv implementation error");
        const err = gen.name("err");
        gen.forRange("i", errsCount, names_1.default.errors, (i) => {
          gen.const(err, (0, codegen_1._)`${names_1.default.vErrors}[${i}]`);
          gen.if((0, codegen_1._)`${err}.instancePath === undefined`, () => gen.assign((0, codegen_1._)`${err}.instancePath`, (0, codegen_1.strConcat)(names_1.default.instancePath, it.errorPath)));
          gen.assign((0, codegen_1._)`${err}.schemaPath`, (0, codegen_1.str)`${it.errSchemaPath}/${keyword}`);
          if (it.opts.verbose) {
            gen.assign((0, codegen_1._)`${err}.schema`, schemaValue);
            gen.assign((0, codegen_1._)`${err}.data`, data);
          }
        });
      }
      exports.extendErrors = extendErrors;
      function addError(gen, errObj) {
        const err = gen.const("err", errObj);
        gen.if((0, codegen_1._)`${names_1.default.vErrors} === null`, () => gen.assign(names_1.default.vErrors, (0, codegen_1._)`[${err}]`), (0, codegen_1._)`${names_1.default.vErrors}.push(${err})`);
        gen.code((0, codegen_1._)`${names_1.default.errors}++`);
      }
      function returnErrors(it, errs) {
        const { gen, validateName, schemaEnv } = it;
        if (schemaEnv.$async) {
          gen.throw((0, codegen_1._)`new ${it.ValidationError}(${errs})`);
        } else {
          gen.assign((0, codegen_1._)`${validateName}.errors`, errs);
          gen.return(false);
        }
      }
      var E = {
        keyword: new codegen_1.Name("keyword"),
        schemaPath: new codegen_1.Name("schemaPath"),
        // also used in JTD errors
        params: new codegen_1.Name("params"),
        propertyName: new codegen_1.Name("propertyName"),
        message: new codegen_1.Name("message"),
        schema: new codegen_1.Name("schema"),
        parentSchema: new codegen_1.Name("parentSchema")
      };
      function errorObjectCode(cxt, error, errorPaths) {
        const { createErrors } = cxt.it;
        if (createErrors === false)
          return (0, codegen_1._)`{}`;
        return errorObject(cxt, error, errorPaths);
      }
      function errorObject(cxt, error, errorPaths = {}) {
        const { gen, it } = cxt;
        const keyValues = [
          errorInstancePath(it, errorPaths),
          errorSchemaPath(cxt, errorPaths)
        ];
        extraErrorProps(cxt, error, keyValues);
        return gen.object(...keyValues);
      }
      function errorInstancePath({ errorPath }, { instancePath }) {
        const instPath = instancePath ? (0, codegen_1.str)`${errorPath}${(0, util_1.getErrorPath)(instancePath, util_1.Type.Str)}` : errorPath;
        return [names_1.default.instancePath, (0, codegen_1.strConcat)(names_1.default.instancePath, instPath)];
      }
      function errorSchemaPath({ keyword, it: { errSchemaPath } }, { schemaPath, parentSchema }) {
        let schPath = parentSchema ? errSchemaPath : (0, codegen_1.str)`${errSchemaPath}/${keyword}`;
        if (schemaPath) {
          schPath = (0, codegen_1.str)`${schPath}${(0, util_1.getErrorPath)(schemaPath, util_1.Type.Str)}`;
        }
        return [E.schemaPath, schPath];
      }
      function extraErrorProps(cxt, { params, message }, keyValues) {
        const { keyword, data, schemaValue, it } = cxt;
        const { opts, propertyName, topSchemaRef, schemaPath } = it;
        keyValues.push([E.keyword, keyword], [E.params, typeof params == "function" ? params(cxt) : params || (0, codegen_1._)`{}`]);
        if (opts.messages) {
          keyValues.push([E.message, typeof message == "function" ? message(cxt) : message]);
        }
        if (opts.verbose) {
          keyValues.push([E.schema, schemaValue], [E.parentSchema, (0, codegen_1._)`${topSchemaRef}${schemaPath}`], [names_1.default.data, data]);
        }
        if (propertyName)
          keyValues.push([E.propertyName, propertyName]);
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/boolSchema.js
  var require_boolSchema = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/boolSchema.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.boolOrEmptySchema = exports.topBoolOrEmptySchema = void 0;
      var errors_1 = require_errors();
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var boolError = {
        message: "boolean schema is false"
      };
      function topBoolOrEmptySchema(it) {
        const { gen, schema, validateName } = it;
        if (schema === false) {
          falseSchemaError(it, false);
        } else if (typeof schema == "object" && schema.$async === true) {
          gen.return(names_1.default.data);
        } else {
          gen.assign((0, codegen_1._)`${validateName}.errors`, null);
          gen.return(true);
        }
      }
      exports.topBoolOrEmptySchema = topBoolOrEmptySchema;
      function boolOrEmptySchema(it, valid) {
        const { gen, schema } = it;
        if (schema === false) {
          gen.var(valid, false);
          falseSchemaError(it);
        } else {
          gen.var(valid, true);
        }
      }
      exports.boolOrEmptySchema = boolOrEmptySchema;
      function falseSchemaError(it, overrideAllErrors) {
        const { gen, data } = it;
        const cxt = {
          gen,
          keyword: "false schema",
          data,
          schema: false,
          schemaCode: false,
          schemaValue: false,
          params: {},
          it
        };
        (0, errors_1.reportError)(cxt, boolError, void 0, overrideAllErrors);
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/rules.js
  var require_rules = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/rules.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.getRules = exports.isJSONType = void 0;
      var _jsonTypes = ["string", "number", "integer", "boolean", "null", "object", "array"];
      var jsonTypes = new Set(_jsonTypes);
      function isJSONType(x) {
        return typeof x == "string" && jsonTypes.has(x);
      }
      exports.isJSONType = isJSONType;
      function getRules() {
        const groups = {
          number: { type: "number", rules: [] },
          string: { type: "string", rules: [] },
          array: { type: "array", rules: [] },
          object: { type: "object", rules: [] }
        };
        return {
          types: { ...groups, integer: true, boolean: true, null: true },
          rules: [{ rules: [] }, groups.number, groups.string, groups.array, groups.object],
          post: { rules: [] },
          all: {},
          keywords: {}
        };
      }
      exports.getRules = getRules;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/applicability.js
  var require_applicability = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/applicability.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.shouldUseRule = exports.shouldUseGroup = exports.schemaHasRulesForType = void 0;
      function schemaHasRulesForType({ schema, self }, type) {
        const group = self.RULES.types[type];
        return group && group !== true && shouldUseGroup(schema, group);
      }
      exports.schemaHasRulesForType = schemaHasRulesForType;
      function shouldUseGroup(schema, group) {
        return group.rules.some((rule) => shouldUseRule(schema, rule));
      }
      exports.shouldUseGroup = shouldUseGroup;
      function shouldUseRule(schema, rule) {
        var _a;
        return schema[rule.keyword] !== void 0 || ((_a = rule.definition.implements) === null || _a === void 0 ? void 0 : _a.some((kwd) => schema[kwd] !== void 0));
      }
      exports.shouldUseRule = shouldUseRule;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/dataType.js
  var require_dataType = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/dataType.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.reportTypeError = exports.checkDataTypes = exports.checkDataType = exports.coerceAndCheckDataType = exports.getJSONTypes = exports.getSchemaTypes = exports.DataType = void 0;
      var rules_1 = require_rules();
      var applicability_1 = require_applicability();
      var errors_1 = require_errors();
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var DataType;
      (function(DataType2) {
        DataType2[DataType2["Correct"] = 0] = "Correct";
        DataType2[DataType2["Wrong"] = 1] = "Wrong";
      })(DataType || (exports.DataType = DataType = {}));
      function getSchemaTypes(schema) {
        const types = getJSONTypes(schema.type);
        const hasNull = types.includes("null");
        if (hasNull) {
          if (schema.nullable === false)
            throw new Error("type: null contradicts nullable: false");
        } else {
          if (!types.length && schema.nullable !== void 0) {
            throw new Error('"nullable" cannot be used without "type"');
          }
          if (schema.nullable === true)
            types.push("null");
        }
        return types;
      }
      exports.getSchemaTypes = getSchemaTypes;
      function getJSONTypes(ts) {
        const types = Array.isArray(ts) ? ts : ts ? [ts] : [];
        if (types.every(rules_1.isJSONType))
          return types;
        throw new Error("type must be JSONType or JSONType[]: " + types.join(","));
      }
      exports.getJSONTypes = getJSONTypes;
      function coerceAndCheckDataType(it, types) {
        const { gen, data, opts } = it;
        const coerceTo = coerceToTypes(types, opts.coerceTypes);
        const checkTypes = types.length > 0 && !(coerceTo.length === 0 && types.length === 1 && (0, applicability_1.schemaHasRulesForType)(it, types[0]));
        if (checkTypes) {
          const wrongType = checkDataTypes(types, data, opts.strictNumbers, DataType.Wrong);
          gen.if(wrongType, () => {
            if (coerceTo.length)
              coerceData(it, types, coerceTo);
            else
              reportTypeError(it);
          });
        }
        return checkTypes;
      }
      exports.coerceAndCheckDataType = coerceAndCheckDataType;
      var COERCIBLE = /* @__PURE__ */ new Set(["string", "number", "integer", "boolean", "null"]);
      function coerceToTypes(types, coerceTypes) {
        return coerceTypes ? types.filter((t) => COERCIBLE.has(t) || coerceTypes === "array" && t === "array") : [];
      }
      function coerceData(it, types, coerceTo) {
        const { gen, data, opts } = it;
        const dataType = gen.let("dataType", (0, codegen_1._)`typeof ${data}`);
        const coerced = gen.let("coerced", (0, codegen_1._)`undefined`);
        if (opts.coerceTypes === "array") {
          gen.if((0, codegen_1._)`${dataType} == 'object' && Array.isArray(${data}) && ${data}.length == 1`, () => gen.assign(data, (0, codegen_1._)`${data}[0]`).assign(dataType, (0, codegen_1._)`typeof ${data}`).if(checkDataTypes(types, data, opts.strictNumbers), () => gen.assign(coerced, data)));
        }
        gen.if((0, codegen_1._)`${coerced} !== undefined`);
        for (const t of coerceTo) {
          if (COERCIBLE.has(t) || t === "array" && opts.coerceTypes === "array") {
            coerceSpecificType(t);
          }
        }
        gen.else();
        reportTypeError(it);
        gen.endIf();
        gen.if((0, codegen_1._)`${coerced} !== undefined`, () => {
          gen.assign(data, coerced);
          assignParentData(it, coerced);
        });
        function coerceSpecificType(t) {
          switch (t) {
            case "string":
              gen.elseIf((0, codegen_1._)`${dataType} == "number" || ${dataType} == "boolean"`).assign(coerced, (0, codegen_1._)`"" + ${data}`).elseIf((0, codegen_1._)`${data} === null`).assign(coerced, (0, codegen_1._)`""`);
              return;
            case "number":
              gen.elseIf((0, codegen_1._)`${dataType} == "boolean" || ${data} === null
              || (${dataType} == "string" && ${data} && ${data} == +${data})`).assign(coerced, (0, codegen_1._)`+${data}`);
              return;
            case "integer":
              gen.elseIf((0, codegen_1._)`${dataType} === "boolean" || ${data} === null
              || (${dataType} === "string" && ${data} && ${data} == +${data} && !(${data} % 1))`).assign(coerced, (0, codegen_1._)`+${data}`);
              return;
            case "boolean":
              gen.elseIf((0, codegen_1._)`${data} === "false" || ${data} === 0 || ${data} === null`).assign(coerced, false).elseIf((0, codegen_1._)`${data} === "true" || ${data} === 1`).assign(coerced, true);
              return;
            case "null":
              gen.elseIf((0, codegen_1._)`${data} === "" || ${data} === 0 || ${data} === false`);
              gen.assign(coerced, null);
              return;
            case "array":
              gen.elseIf((0, codegen_1._)`${dataType} === "string" || ${dataType} === "number"
              || ${dataType} === "boolean" || ${data} === null`).assign(coerced, (0, codegen_1._)`[${data}]`);
          }
        }
      }
      function assignParentData({ gen, parentData, parentDataProperty }, expr) {
        gen.if((0, codegen_1._)`${parentData} !== undefined`, () => gen.assign((0, codegen_1._)`${parentData}[${parentDataProperty}]`, expr));
      }
      function checkDataType(dataType, data, strictNums, correct = DataType.Correct) {
        const EQ = correct === DataType.Correct ? codegen_1.operators.EQ : codegen_1.operators.NEQ;
        let cond;
        switch (dataType) {
          case "null":
            return (0, codegen_1._)`${data} ${EQ} null`;
          case "array":
            cond = (0, codegen_1._)`Array.isArray(${data})`;
            break;
          case "object":
            cond = (0, codegen_1._)`${data} && typeof ${data} == "object" && !Array.isArray(${data})`;
            break;
          case "integer":
            cond = numCond((0, codegen_1._)`!(${data} % 1) && !isNaN(${data})`);
            break;
          case "number":
            cond = numCond();
            break;
          default:
            return (0, codegen_1._)`typeof ${data} ${EQ} ${dataType}`;
        }
        return correct === DataType.Correct ? cond : (0, codegen_1.not)(cond);
        function numCond(_cond = codegen_1.nil) {
          return (0, codegen_1.and)((0, codegen_1._)`typeof ${data} == "number"`, _cond, strictNums ? (0, codegen_1._)`isFinite(${data})` : codegen_1.nil);
        }
      }
      exports.checkDataType = checkDataType;
      function checkDataTypes(dataTypes, data, strictNums, correct) {
        if (dataTypes.length === 1) {
          return checkDataType(dataTypes[0], data, strictNums, correct);
        }
        let cond;
        const types = (0, util_1.toHash)(dataTypes);
        if (types.array && types.object) {
          const notObj = (0, codegen_1._)`typeof ${data} != "object"`;
          cond = types.null ? notObj : (0, codegen_1._)`!${data} || ${notObj}`;
          delete types.null;
          delete types.array;
          delete types.object;
        } else {
          cond = codegen_1.nil;
        }
        if (types.number)
          delete types.integer;
        for (const t in types)
          cond = (0, codegen_1.and)(cond, checkDataType(t, data, strictNums, correct));
        return cond;
      }
      exports.checkDataTypes = checkDataTypes;
      var typeError = {
        message: ({ schema }) => `must be ${schema}`,
        params: ({ schema, schemaValue }) => typeof schema == "string" ? (0, codegen_1._)`{type: ${schema}}` : (0, codegen_1._)`{type: ${schemaValue}}`
      };
      function reportTypeError(it) {
        const cxt = getTypeErrorContext(it);
        (0, errors_1.reportError)(cxt, typeError);
      }
      exports.reportTypeError = reportTypeError;
      function getTypeErrorContext(it) {
        const { gen, data, schema } = it;
        const schemaCode = (0, util_1.schemaRefOrVal)(it, schema, "type");
        return {
          gen,
          keyword: "type",
          data,
          schema: schema.type,
          schemaCode,
          schemaValue: schemaCode,
          parentSchema: schema,
          params: {},
          it
        };
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/defaults.js
  var require_defaults = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/defaults.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.assignDefaults = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      function assignDefaults(it, ty) {
        const { properties, items } = it.schema;
        if (ty === "object" && properties) {
          for (const key in properties) {
            assignDefault(it, key, properties[key].default);
          }
        } else if (ty === "array" && Array.isArray(items)) {
          items.forEach((sch, i) => assignDefault(it, i, sch.default));
        }
      }
      exports.assignDefaults = assignDefaults;
      function assignDefault(it, prop, defaultValue) {
        const { gen, compositeRule, data, opts } = it;
        if (defaultValue === void 0)
          return;
        const childData = (0, codegen_1._)`${data}${(0, codegen_1.getProperty)(prop)}`;
        if (compositeRule) {
          (0, util_1.checkStrictMode)(it, `default is ignored for: ${childData}`);
          return;
        }
        let condition = (0, codegen_1._)`${childData} === undefined`;
        if (opts.useDefaults === "empty") {
          condition = (0, codegen_1._)`${condition} || ${childData} === null || ${childData} === ""`;
        }
        gen.if(condition, (0, codegen_1._)`${childData} = ${(0, codegen_1.stringify)(defaultValue)}`);
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/code.js
  var require_code2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/code.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.validateUnion = exports.validateArray = exports.usePattern = exports.callValidateCode = exports.schemaProperties = exports.allSchemaProperties = exports.noPropertyInData = exports.propertyInData = exports.isOwnProperty = exports.hasPropFunc = exports.reportMissingProp = exports.checkMissingProp = exports.checkReportMissingProp = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var names_1 = require_names();
      var util_2 = require_util();
      function checkReportMissingProp(cxt, prop) {
        const { gen, data, it } = cxt;
        gen.if(noPropertyInData(gen, data, prop, it.opts.ownProperties), () => {
          cxt.setParams({ missingProperty: (0, codegen_1._)`${prop}` }, true);
          cxt.error();
        });
      }
      exports.checkReportMissingProp = checkReportMissingProp;
      function checkMissingProp({ gen, data, it: { opts } }, properties, missing) {
        return (0, codegen_1.or)(...properties.map((prop) => (0, codegen_1.and)(noPropertyInData(gen, data, prop, opts.ownProperties), (0, codegen_1._)`${missing} = ${prop}`)));
      }
      exports.checkMissingProp = checkMissingProp;
      function reportMissingProp(cxt, missing) {
        cxt.setParams({ missingProperty: missing }, true);
        cxt.error();
      }
      exports.reportMissingProp = reportMissingProp;
      function hasPropFunc(gen) {
        return gen.scopeValue("func", {
          // eslint-disable-next-line @typescript-eslint/unbound-method
          ref: Object.prototype.hasOwnProperty,
          code: (0, codegen_1._)`Object.prototype.hasOwnProperty`
        });
      }
      exports.hasPropFunc = hasPropFunc;
      function isOwnProperty(gen, data, property) {
        return (0, codegen_1._)`${hasPropFunc(gen)}.call(${data}, ${property})`;
      }
      exports.isOwnProperty = isOwnProperty;
      function propertyInData(gen, data, property, ownProperties) {
        const cond = (0, codegen_1._)`${data}${(0, codegen_1.getProperty)(property)} !== undefined`;
        return ownProperties ? (0, codegen_1._)`${cond} && ${isOwnProperty(gen, data, property)}` : cond;
      }
      exports.propertyInData = propertyInData;
      function noPropertyInData(gen, data, property, ownProperties) {
        const cond = (0, codegen_1._)`${data}${(0, codegen_1.getProperty)(property)} === undefined`;
        return ownProperties ? (0, codegen_1.or)(cond, (0, codegen_1.not)(isOwnProperty(gen, data, property))) : cond;
      }
      exports.noPropertyInData = noPropertyInData;
      function allSchemaProperties(schemaMap) {
        return schemaMap ? Object.keys(schemaMap).filter((p) => p !== "__proto__") : [];
      }
      exports.allSchemaProperties = allSchemaProperties;
      function schemaProperties(it, schemaMap) {
        return allSchemaProperties(schemaMap).filter((p) => !(0, util_1.alwaysValidSchema)(it, schemaMap[p]));
      }
      exports.schemaProperties = schemaProperties;
      function callValidateCode({ schemaCode, data, it: { gen, topSchemaRef, schemaPath, errorPath }, it }, func, context, passSchema) {
        const dataAndSchema = passSchema ? (0, codegen_1._)`${schemaCode}, ${data}, ${topSchemaRef}${schemaPath}` : data;
        const valCxt = [
          [names_1.default.instancePath, (0, codegen_1.strConcat)(names_1.default.instancePath, errorPath)],
          [names_1.default.parentData, it.parentData],
          [names_1.default.parentDataProperty, it.parentDataProperty],
          [names_1.default.rootData, names_1.default.rootData]
        ];
        if (it.opts.dynamicRef)
          valCxt.push([names_1.default.dynamicAnchors, names_1.default.dynamicAnchors]);
        const args = (0, codegen_1._)`${dataAndSchema}, ${gen.object(...valCxt)}`;
        return context !== codegen_1.nil ? (0, codegen_1._)`${func}.call(${context}, ${args})` : (0, codegen_1._)`${func}(${args})`;
      }
      exports.callValidateCode = callValidateCode;
      var newRegExp = (0, codegen_1._)`new RegExp`;
      function usePattern({ gen, it: { opts } }, pattern) {
        const u = opts.unicodeRegExp ? "u" : "";
        const { regExp } = opts.code;
        const rx = regExp(pattern, u);
        return gen.scopeValue("pattern", {
          key: rx.toString(),
          ref: rx,
          code: (0, codegen_1._)`${regExp.code === "new RegExp" ? newRegExp : (0, util_2.useFunc)(gen, regExp)}(${pattern}, ${u})`
        });
      }
      exports.usePattern = usePattern;
      function validateArray(cxt) {
        const { gen, data, keyword, it } = cxt;
        const valid = gen.name("valid");
        if (it.allErrors) {
          const validArr = gen.let("valid", true);
          validateItems(() => gen.assign(validArr, false));
          return validArr;
        }
        gen.var(valid, true);
        validateItems(() => gen.break());
        return valid;
        function validateItems(notValid) {
          const len = gen.const("len", (0, codegen_1._)`${data}.length`);
          gen.forRange("i", 0, len, (i) => {
            cxt.subschema({
              keyword,
              dataProp: i,
              dataPropType: util_1.Type.Num
            }, valid);
            gen.if((0, codegen_1.not)(valid), notValid);
          });
        }
      }
      exports.validateArray = validateArray;
      function validateUnion(cxt) {
        const { gen, schema, keyword, it } = cxt;
        if (!Array.isArray(schema))
          throw new Error("ajv implementation error");
        const alwaysValid = schema.some((sch) => (0, util_1.alwaysValidSchema)(it, sch));
        if (alwaysValid && !it.opts.unevaluated)
          return;
        const valid = gen.let("valid", false);
        const schValid = gen.name("_valid");
        gen.block(() => schema.forEach((_sch, i) => {
          const schCxt = cxt.subschema({
            keyword,
            schemaProp: i,
            compositeRule: true
          }, schValid);
          gen.assign(valid, (0, codegen_1._)`${valid} || ${schValid}`);
          const merged = cxt.mergeValidEvaluated(schCxt, schValid);
          if (!merged)
            gen.if((0, codegen_1.not)(valid));
        }));
        cxt.result(valid, () => cxt.reset(), () => cxt.error(true));
      }
      exports.validateUnion = validateUnion;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/keyword.js
  var require_keyword = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/keyword.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.validateKeywordUsage = exports.validSchemaType = exports.funcKeywordCode = exports.macroKeywordCode = void 0;
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var code_1 = require_code2();
      var errors_1 = require_errors();
      function macroKeywordCode(cxt, def) {
        const { gen, keyword, schema, parentSchema, it } = cxt;
        const macroSchema = def.macro.call(it.self, schema, parentSchema, it);
        const schemaRef = useKeyword(gen, keyword, macroSchema);
        if (it.opts.validateSchema !== false)
          it.self.validateSchema(macroSchema, true);
        const valid = gen.name("valid");
        cxt.subschema({
          schema: macroSchema,
          schemaPath: codegen_1.nil,
          errSchemaPath: `${it.errSchemaPath}/${keyword}`,
          topSchemaRef: schemaRef,
          compositeRule: true
        }, valid);
        cxt.pass(valid, () => cxt.error(true));
      }
      exports.macroKeywordCode = macroKeywordCode;
      function funcKeywordCode(cxt, def) {
        var _a;
        const { gen, keyword, schema, parentSchema, $data, it } = cxt;
        checkAsyncKeyword(it, def);
        const validate = !$data && def.compile ? def.compile.call(it.self, schema, parentSchema, it) : def.validate;
        const validateRef = useKeyword(gen, keyword, validate);
        const valid = gen.let("valid");
        cxt.block$data(valid, validateKeyword);
        cxt.ok((_a = def.valid) !== null && _a !== void 0 ? _a : valid);
        function validateKeyword() {
          if (def.errors === false) {
            assignValid();
            if (def.modifying)
              modifyData(cxt);
            reportErrs(() => cxt.error());
          } else {
            const ruleErrs = def.async ? validateAsync() : validateSync();
            if (def.modifying)
              modifyData(cxt);
            reportErrs(() => addErrs(cxt, ruleErrs));
          }
        }
        function validateAsync() {
          const ruleErrs = gen.let("ruleErrs", null);
          gen.try(() => assignValid((0, codegen_1._)`await `), (e) => gen.assign(valid, false).if((0, codegen_1._)`${e} instanceof ${it.ValidationError}`, () => gen.assign(ruleErrs, (0, codegen_1._)`${e}.errors`), () => gen.throw(e)));
          return ruleErrs;
        }
        function validateSync() {
          const validateErrs = (0, codegen_1._)`${validateRef}.errors`;
          gen.assign(validateErrs, null);
          assignValid(codegen_1.nil);
          return validateErrs;
        }
        function assignValid(_await = def.async ? (0, codegen_1._)`await ` : codegen_1.nil) {
          const passCxt = it.opts.passContext ? names_1.default.this : names_1.default.self;
          const passSchema = !("compile" in def && !$data || def.schema === false);
          gen.assign(valid, (0, codegen_1._)`${_await}${(0, code_1.callValidateCode)(cxt, validateRef, passCxt, passSchema)}`, def.modifying);
        }
        function reportErrs(errors) {
          var _a2;
          gen.if((0, codegen_1.not)((_a2 = def.valid) !== null && _a2 !== void 0 ? _a2 : valid), errors);
        }
      }
      exports.funcKeywordCode = funcKeywordCode;
      function modifyData(cxt) {
        const { gen, data, it } = cxt;
        gen.if(it.parentData, () => gen.assign(data, (0, codegen_1._)`${it.parentData}[${it.parentDataProperty}]`));
      }
      function addErrs(cxt, errs) {
        const { gen } = cxt;
        gen.if((0, codegen_1._)`Array.isArray(${errs})`, () => {
          gen.assign(names_1.default.vErrors, (0, codegen_1._)`${names_1.default.vErrors} === null ? ${errs} : ${names_1.default.vErrors}.concat(${errs})`).assign(names_1.default.errors, (0, codegen_1._)`${names_1.default.vErrors}.length`);
          (0, errors_1.extendErrors)(cxt);
        }, () => cxt.error());
      }
      function checkAsyncKeyword({ schemaEnv }, def) {
        if (def.async && !schemaEnv.$async)
          throw new Error("async keyword in sync schema");
      }
      function useKeyword(gen, keyword, result) {
        if (result === void 0)
          throw new Error(`keyword "${keyword}" failed to compile`);
        return gen.scopeValue("keyword", typeof result == "function" ? { ref: result } : { ref: result, code: (0, codegen_1.stringify)(result) });
      }
      function validSchemaType(schema, schemaType, allowUndefined = false) {
        return !schemaType.length || schemaType.some((st) => st === "array" ? Array.isArray(schema) : st === "object" ? schema && typeof schema == "object" && !Array.isArray(schema) : typeof schema == st || allowUndefined && typeof schema == "undefined");
      }
      exports.validSchemaType = validSchemaType;
      function validateKeywordUsage({ schema, opts, self, errSchemaPath }, def, keyword) {
        if (Array.isArray(def.keyword) ? !def.keyword.includes(keyword) : def.keyword !== keyword) {
          throw new Error("ajv implementation error");
        }
        const deps = def.dependencies;
        if (deps === null || deps === void 0 ? void 0 : deps.some((kwd) => !Object.prototype.hasOwnProperty.call(schema, kwd))) {
          throw new Error(`parent schema must have dependencies of ${keyword}: ${deps.join(",")}`);
        }
        if (def.validateSchema) {
          const valid = def.validateSchema(schema[keyword]);
          if (!valid) {
            const msg = `keyword "${keyword}" value is invalid at path "${errSchemaPath}": ` + self.errorsText(def.validateSchema.errors);
            if (opts.validateSchema === "log")
              self.logger.error(msg);
            else
              throw new Error(msg);
          }
        }
      }
      exports.validateKeywordUsage = validateKeywordUsage;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/subschema.js
  var require_subschema = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/subschema.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.extendSubschemaMode = exports.extendSubschemaData = exports.getSubschema = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      function getSubschema(it, { keyword, schemaProp, schema, schemaPath, errSchemaPath, topSchemaRef }) {
        if (keyword !== void 0 && schema !== void 0) {
          throw new Error('both "keyword" and "schema" passed, only one allowed');
        }
        if (keyword !== void 0) {
          const sch = it.schema[keyword];
          return schemaProp === void 0 ? {
            schema: sch,
            schemaPath: (0, codegen_1._)`${it.schemaPath}${(0, codegen_1.getProperty)(keyword)}`,
            errSchemaPath: `${it.errSchemaPath}/${keyword}`
          } : {
            schema: sch[schemaProp],
            schemaPath: (0, codegen_1._)`${it.schemaPath}${(0, codegen_1.getProperty)(keyword)}${(0, codegen_1.getProperty)(schemaProp)}`,
            errSchemaPath: `${it.errSchemaPath}/${keyword}/${(0, util_1.escapeFragment)(schemaProp)}`
          };
        }
        if (schema !== void 0) {
          if (schemaPath === void 0 || errSchemaPath === void 0 || topSchemaRef === void 0) {
            throw new Error('"schemaPath", "errSchemaPath" and "topSchemaRef" are required with "schema"');
          }
          return {
            schema,
            schemaPath,
            topSchemaRef,
            errSchemaPath
          };
        }
        throw new Error('either "keyword" or "schema" must be passed');
      }
      exports.getSubschema = getSubschema;
      function extendSubschemaData(subschema, it, { dataProp, dataPropType: dpType, data, dataTypes, propertyName }) {
        if (data !== void 0 && dataProp !== void 0) {
          throw new Error('both "data" and "dataProp" passed, only one allowed');
        }
        const { gen } = it;
        if (dataProp !== void 0) {
          const { errorPath, dataPathArr, opts } = it;
          const nextData = gen.let("data", (0, codegen_1._)`${it.data}${(0, codegen_1.getProperty)(dataProp)}`, true);
          dataContextProps(nextData);
          subschema.errorPath = (0, codegen_1.str)`${errorPath}${(0, util_1.getErrorPath)(dataProp, dpType, opts.jsPropertySyntax)}`;
          subschema.parentDataProperty = (0, codegen_1._)`${dataProp}`;
          subschema.dataPathArr = [...dataPathArr, subschema.parentDataProperty];
        }
        if (data !== void 0) {
          const nextData = data instanceof codegen_1.Name ? data : gen.let("data", data, true);
          dataContextProps(nextData);
          if (propertyName !== void 0)
            subschema.propertyName = propertyName;
        }
        if (dataTypes)
          subschema.dataTypes = dataTypes;
        function dataContextProps(_nextData) {
          subschema.data = _nextData;
          subschema.dataLevel = it.dataLevel + 1;
          subschema.dataTypes = [];
          it.definedProperties = /* @__PURE__ */ new Set();
          subschema.parentData = it.data;
          subschema.dataNames = [...it.dataNames, _nextData];
        }
      }
      exports.extendSubschemaData = extendSubschemaData;
      function extendSubschemaMode(subschema, { jtdDiscriminator, jtdMetadata, compositeRule, createErrors, allErrors }) {
        if (compositeRule !== void 0)
          subschema.compositeRule = compositeRule;
        if (createErrors !== void 0)
          subschema.createErrors = createErrors;
        if (allErrors !== void 0)
          subschema.allErrors = allErrors;
        subschema.jtdDiscriminator = jtdDiscriminator;
        subschema.jtdMetadata = jtdMetadata;
      }
      exports.extendSubschemaMode = extendSubschemaMode;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-deep-equal@3.1.3/node_modules/fast-deep-equal/index.js
  var require_fast_deep_equal = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-deep-equal@3.1.3/node_modules/fast-deep-equal/index.js"(exports, module) {
      "use strict";
      module.exports = function equal(a, b) {
        if (a === b) return true;
        if (a && b && typeof a == "object" && typeof b == "object") {
          if (a.constructor !== b.constructor) return false;
          var length, i, keys;
          if (Array.isArray(a)) {
            length = a.length;
            if (length != b.length) return false;
            for (i = length; i-- !== 0; )
              if (!equal(a[i], b[i])) return false;
            return true;
          }
          if (a.constructor === RegExp) return a.source === b.source && a.flags === b.flags;
          if (a.valueOf !== Object.prototype.valueOf) return a.valueOf() === b.valueOf();
          if (a.toString !== Object.prototype.toString) return a.toString() === b.toString();
          keys = Object.keys(a);
          length = keys.length;
          if (length !== Object.keys(b).length) return false;
          for (i = length; i-- !== 0; )
            if (!Object.prototype.hasOwnProperty.call(b, keys[i])) return false;
          for (i = length; i-- !== 0; ) {
            var key = keys[i];
            if (!equal(a[key], b[key])) return false;
          }
          return true;
        }
        return a !== a && b !== b;
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/json-schema-traverse@1.0.0/node_modules/json-schema-traverse/index.js
  var require_json_schema_traverse = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/json-schema-traverse@1.0.0/node_modules/json-schema-traverse/index.js"(exports, module) {
      "use strict";
      var traverse = module.exports = function(schema, opts, cb) {
        if (typeof opts == "function") {
          cb = opts;
          opts = {};
        }
        cb = opts.cb || cb;
        var pre = typeof cb == "function" ? cb : cb.pre || function() {
        };
        var post = cb.post || function() {
        };
        _traverse(opts, pre, post, schema, "", schema);
      };
      traverse.keywords = {
        additionalItems: true,
        items: true,
        contains: true,
        additionalProperties: true,
        propertyNames: true,
        not: true,
        if: true,
        then: true,
        else: true
      };
      traverse.arrayKeywords = {
        items: true,
        allOf: true,
        anyOf: true,
        oneOf: true
      };
      traverse.propsKeywords = {
        $defs: true,
        definitions: true,
        properties: true,
        patternProperties: true,
        dependencies: true
      };
      traverse.skipKeywords = {
        default: true,
        enum: true,
        const: true,
        required: true,
        maximum: true,
        minimum: true,
        exclusiveMaximum: true,
        exclusiveMinimum: true,
        multipleOf: true,
        maxLength: true,
        minLength: true,
        pattern: true,
        format: true,
        maxItems: true,
        minItems: true,
        uniqueItems: true,
        maxProperties: true,
        minProperties: true
      };
      function _traverse(opts, pre, post, schema, jsonPtr, rootSchema, parentJsonPtr, parentKeyword, parentSchema, keyIndex) {
        if (schema && typeof schema == "object" && !Array.isArray(schema)) {
          pre(schema, jsonPtr, rootSchema, parentJsonPtr, parentKeyword, parentSchema, keyIndex);
          for (var key in schema) {
            var sch = schema[key];
            if (Array.isArray(sch)) {
              if (key in traverse.arrayKeywords) {
                for (var i = 0; i < sch.length; i++)
                  _traverse(opts, pre, post, sch[i], jsonPtr + "/" + key + "/" + i, rootSchema, jsonPtr, key, schema, i);
              }
            } else if (key in traverse.propsKeywords) {
              if (sch && typeof sch == "object") {
                for (var prop in sch)
                  _traverse(opts, pre, post, sch[prop], jsonPtr + "/" + key + "/" + escapeJsonPtr(prop), rootSchema, jsonPtr, key, schema, prop);
              }
            } else if (key in traverse.keywords || opts.allKeys && !(key in traverse.skipKeywords)) {
              _traverse(opts, pre, post, sch, jsonPtr + "/" + key, rootSchema, jsonPtr, key, schema);
            }
          }
          post(schema, jsonPtr, rootSchema, parentJsonPtr, parentKeyword, parentSchema, keyIndex);
        }
      }
      function escapeJsonPtr(str) {
        return str.replace(/~/g, "~0").replace(/\//g, "~1");
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/resolve.js
  var require_resolve = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/resolve.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.getSchemaRefs = exports.resolveUrl = exports.normalizeId = exports._getFullPath = exports.getFullPath = exports.inlineRef = void 0;
      var util_1 = require_util();
      var equal = require_fast_deep_equal();
      var traverse = require_json_schema_traverse();
      var SIMPLE_INLINED = /* @__PURE__ */ new Set([
        "type",
        "format",
        "pattern",
        "maxLength",
        "minLength",
        "maxProperties",
        "minProperties",
        "maxItems",
        "minItems",
        "maximum",
        "minimum",
        "uniqueItems",
        "multipleOf",
        "required",
        "enum",
        "const"
      ]);
      function inlineRef(schema, limit = true) {
        if (typeof schema == "boolean")
          return true;
        if (limit === true)
          return !hasRef(schema);
        if (!limit)
          return false;
        return countKeys(schema) <= limit;
      }
      exports.inlineRef = inlineRef;
      var REF_KEYWORDS = /* @__PURE__ */ new Set([
        "$ref",
        "$recursiveRef",
        "$recursiveAnchor",
        "$dynamicRef",
        "$dynamicAnchor"
      ]);
      function hasRef(schema) {
        for (const key in schema) {
          if (REF_KEYWORDS.has(key))
            return true;
          const sch = schema[key];
          if (Array.isArray(sch) && sch.some(hasRef))
            return true;
          if (typeof sch == "object" && hasRef(sch))
            return true;
        }
        return false;
      }
      function countKeys(schema) {
        let count = 0;
        for (const key in schema) {
          if (key === "$ref")
            return Infinity;
          count++;
          if (SIMPLE_INLINED.has(key))
            continue;
          if (typeof schema[key] == "object") {
            (0, util_1.eachItem)(schema[key], (sch) => count += countKeys(sch));
          }
          if (count === Infinity)
            return Infinity;
        }
        return count;
      }
      function getFullPath(resolver, id = "", normalize) {
        if (normalize !== false)
          id = normalizeId(id);
        const p = resolver.parse(id);
        return _getFullPath(resolver, p);
      }
      exports.getFullPath = getFullPath;
      function _getFullPath(resolver, p) {
        const serialized = resolver.serialize(p);
        return serialized.split("#")[0] + "#";
      }
      exports._getFullPath = _getFullPath;
      var TRAILING_SLASH_HASH = /#\/?$/;
      function normalizeId(id) {
        return id ? id.replace(TRAILING_SLASH_HASH, "") : "";
      }
      exports.normalizeId = normalizeId;
      function resolveUrl(resolver, baseId, id) {
        id = normalizeId(id);
        return resolver.resolve(baseId, id);
      }
      exports.resolveUrl = resolveUrl;
      var ANCHOR = /^[a-z_][-a-z0-9._]*$/i;
      function getSchemaRefs(schema, baseId) {
        if (typeof schema == "boolean")
          return {};
        const { schemaId, uriResolver } = this.opts;
        const schId = normalizeId(schema[schemaId] || baseId);
        const baseIds = { "": schId };
        const pathPrefix = getFullPath(uriResolver, schId, false);
        const localRefs = {};
        const schemaRefs = /* @__PURE__ */ new Set();
        traverse(schema, { allKeys: true }, (sch, jsonPtr, _, parentJsonPtr) => {
          if (parentJsonPtr === void 0)
            return;
          const fullPath = pathPrefix + jsonPtr;
          let innerBaseId = baseIds[parentJsonPtr];
          if (typeof sch[schemaId] == "string")
            innerBaseId = addRef.call(this, sch[schemaId]);
          addAnchor.call(this, sch.$anchor);
          addAnchor.call(this, sch.$dynamicAnchor);
          baseIds[jsonPtr] = innerBaseId;
          function addRef(ref) {
            const _resolve = this.opts.uriResolver.resolve;
            ref = normalizeId(innerBaseId ? _resolve(innerBaseId, ref) : ref);
            if (schemaRefs.has(ref))
              throw ambiguos(ref);
            schemaRefs.add(ref);
            let schOrRef = this.refs[ref];
            if (typeof schOrRef == "string")
              schOrRef = this.refs[schOrRef];
            if (typeof schOrRef == "object") {
              checkAmbiguosRef(sch, schOrRef.schema, ref);
            } else if (ref !== normalizeId(fullPath)) {
              if (ref[0] === "#") {
                checkAmbiguosRef(sch, localRefs[ref], ref);
                localRefs[ref] = sch;
              } else {
                this.refs[ref] = fullPath;
              }
            }
            return ref;
          }
          function addAnchor(anchor) {
            if (typeof anchor == "string") {
              if (!ANCHOR.test(anchor))
                throw new Error(`invalid anchor "${anchor}"`);
              addRef.call(this, `#${anchor}`);
            }
          }
        });
        return localRefs;
        function checkAmbiguosRef(sch1, sch2, ref) {
          if (sch2 !== void 0 && !equal(sch1, sch2))
            throw ambiguos(ref);
        }
        function ambiguos(ref) {
          return new Error(`reference "${ref}" resolves to more than one schema`);
        }
      }
      exports.getSchemaRefs = getSchemaRefs;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/index.js
  var require_validate = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/validate/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.getData = exports.KeywordCxt = exports.validateFunctionCode = void 0;
      var boolSchema_1 = require_boolSchema();
      var dataType_1 = require_dataType();
      var applicability_1 = require_applicability();
      var dataType_2 = require_dataType();
      var defaults_1 = require_defaults();
      var keyword_1 = require_keyword();
      var subschema_1 = require_subschema();
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var resolve_1 = require_resolve();
      var util_1 = require_util();
      var errors_1 = require_errors();
      function validateFunctionCode(it) {
        if (isSchemaObj(it)) {
          checkKeywords(it);
          if (schemaCxtHasRules(it)) {
            topSchemaObjCode(it);
            return;
          }
        }
        validateFunction(it, () => (0, boolSchema_1.topBoolOrEmptySchema)(it));
      }
      exports.validateFunctionCode = validateFunctionCode;
      function validateFunction({ gen, validateName, schema, schemaEnv, opts }, body) {
        if (opts.code.es5) {
          gen.func(validateName, (0, codegen_1._)`${names_1.default.data}, ${names_1.default.valCxt}`, schemaEnv.$async, () => {
            gen.code((0, codegen_1._)`"use strict"; ${funcSourceUrl(schema, opts)}`);
            destructureValCxtES5(gen, opts);
            gen.code(body);
          });
        } else {
          gen.func(validateName, (0, codegen_1._)`${names_1.default.data}, ${destructureValCxt(opts)}`, schemaEnv.$async, () => gen.code(funcSourceUrl(schema, opts)).code(body));
        }
      }
      function destructureValCxt(opts) {
        return (0, codegen_1._)`{${names_1.default.instancePath}="", ${names_1.default.parentData}, ${names_1.default.parentDataProperty}, ${names_1.default.rootData}=${names_1.default.data}${opts.dynamicRef ? (0, codegen_1._)`, ${names_1.default.dynamicAnchors}={}` : codegen_1.nil}}={}`;
      }
      function destructureValCxtES5(gen, opts) {
        gen.if(names_1.default.valCxt, () => {
          gen.var(names_1.default.instancePath, (0, codegen_1._)`${names_1.default.valCxt}.${names_1.default.instancePath}`);
          gen.var(names_1.default.parentData, (0, codegen_1._)`${names_1.default.valCxt}.${names_1.default.parentData}`);
          gen.var(names_1.default.parentDataProperty, (0, codegen_1._)`${names_1.default.valCxt}.${names_1.default.parentDataProperty}`);
          gen.var(names_1.default.rootData, (0, codegen_1._)`${names_1.default.valCxt}.${names_1.default.rootData}`);
          if (opts.dynamicRef)
            gen.var(names_1.default.dynamicAnchors, (0, codegen_1._)`${names_1.default.valCxt}.${names_1.default.dynamicAnchors}`);
        }, () => {
          gen.var(names_1.default.instancePath, (0, codegen_1._)`""`);
          gen.var(names_1.default.parentData, (0, codegen_1._)`undefined`);
          gen.var(names_1.default.parentDataProperty, (0, codegen_1._)`undefined`);
          gen.var(names_1.default.rootData, names_1.default.data);
          if (opts.dynamicRef)
            gen.var(names_1.default.dynamicAnchors, (0, codegen_1._)`{}`);
        });
      }
      function topSchemaObjCode(it) {
        const { schema, opts, gen } = it;
        validateFunction(it, () => {
          if (opts.$comment && schema.$comment)
            commentKeyword(it);
          checkNoDefault(it);
          gen.let(names_1.default.vErrors, null);
          gen.let(names_1.default.errors, 0);
          if (opts.unevaluated)
            resetEvaluated(it);
          typeAndKeywords(it);
          returnResults(it);
        });
        return;
      }
      function resetEvaluated(it) {
        const { gen, validateName } = it;
        it.evaluated = gen.const("evaluated", (0, codegen_1._)`${validateName}.evaluated`);
        gen.if((0, codegen_1._)`${it.evaluated}.dynamicProps`, () => gen.assign((0, codegen_1._)`${it.evaluated}.props`, (0, codegen_1._)`undefined`));
        gen.if((0, codegen_1._)`${it.evaluated}.dynamicItems`, () => gen.assign((0, codegen_1._)`${it.evaluated}.items`, (0, codegen_1._)`undefined`));
      }
      function funcSourceUrl(schema, opts) {
        const schId = typeof schema == "object" && schema[opts.schemaId];
        return schId && (opts.code.source || opts.code.process) ? (0, codegen_1._)`/*# sourceURL=${schId} */` : codegen_1.nil;
      }
      function subschemaCode(it, valid) {
        if (isSchemaObj(it)) {
          checkKeywords(it);
          if (schemaCxtHasRules(it)) {
            subSchemaObjCode(it, valid);
            return;
          }
        }
        (0, boolSchema_1.boolOrEmptySchema)(it, valid);
      }
      function schemaCxtHasRules({ schema, self }) {
        if (typeof schema == "boolean")
          return !schema;
        for (const key in schema)
          if (self.RULES.all[key])
            return true;
        return false;
      }
      function isSchemaObj(it) {
        return typeof it.schema != "boolean";
      }
      function subSchemaObjCode(it, valid) {
        const { schema, gen, opts } = it;
        if (opts.$comment && schema.$comment)
          commentKeyword(it);
        updateContext(it);
        checkAsyncSchema(it);
        const errsCount = gen.const("_errs", names_1.default.errors);
        typeAndKeywords(it, errsCount);
        gen.var(valid, (0, codegen_1._)`${errsCount} === ${names_1.default.errors}`);
      }
      function checkKeywords(it) {
        (0, util_1.checkUnknownRules)(it);
        checkRefsAndKeywords(it);
      }
      function typeAndKeywords(it, errsCount) {
        if (it.opts.jtd)
          return schemaKeywords(it, [], false, errsCount);
        const types = (0, dataType_1.getSchemaTypes)(it.schema);
        const checkedTypes = (0, dataType_1.coerceAndCheckDataType)(it, types);
        schemaKeywords(it, types, !checkedTypes, errsCount);
      }
      function checkRefsAndKeywords(it) {
        const { schema, errSchemaPath, opts, self } = it;
        if (schema.$ref && opts.ignoreKeywordsWithRef && (0, util_1.schemaHasRulesButRef)(schema, self.RULES)) {
          self.logger.warn(`$ref: keywords ignored in schema at path "${errSchemaPath}"`);
        }
      }
      function checkNoDefault(it) {
        const { schema, opts } = it;
        if (schema.default !== void 0 && opts.useDefaults && opts.strictSchema) {
          (0, util_1.checkStrictMode)(it, "default is ignored in the schema root");
        }
      }
      function updateContext(it) {
        const schId = it.schema[it.opts.schemaId];
        if (schId)
          it.baseId = (0, resolve_1.resolveUrl)(it.opts.uriResolver, it.baseId, schId);
      }
      function checkAsyncSchema(it) {
        if (it.schema.$async && !it.schemaEnv.$async)
          throw new Error("async schema in sync schema");
      }
      function commentKeyword({ gen, schemaEnv, schema, errSchemaPath, opts }) {
        const msg = schema.$comment;
        if (opts.$comment === true) {
          gen.code((0, codegen_1._)`${names_1.default.self}.logger.log(${msg})`);
        } else if (typeof opts.$comment == "function") {
          const schemaPath = (0, codegen_1.str)`${errSchemaPath}/$comment`;
          const rootName = gen.scopeValue("root", { ref: schemaEnv.root });
          gen.code((0, codegen_1._)`${names_1.default.self}.opts.$comment(${msg}, ${schemaPath}, ${rootName}.schema)`);
        }
      }
      function returnResults(it) {
        const { gen, schemaEnv, validateName, ValidationError, opts } = it;
        if (schemaEnv.$async) {
          gen.if((0, codegen_1._)`${names_1.default.errors} === 0`, () => gen.return(names_1.default.data), () => gen.throw((0, codegen_1._)`new ${ValidationError}(${names_1.default.vErrors})`));
        } else {
          gen.assign((0, codegen_1._)`${validateName}.errors`, names_1.default.vErrors);
          if (opts.unevaluated)
            assignEvaluated(it);
          gen.return((0, codegen_1._)`${names_1.default.errors} === 0`);
        }
      }
      function assignEvaluated({ gen, evaluated, props, items }) {
        if (props instanceof codegen_1.Name)
          gen.assign((0, codegen_1._)`${evaluated}.props`, props);
        if (items instanceof codegen_1.Name)
          gen.assign((0, codegen_1._)`${evaluated}.items`, items);
      }
      function schemaKeywords(it, types, typeErrors, errsCount) {
        const { gen, schema, data, allErrors, opts, self } = it;
        const { RULES } = self;
        if (schema.$ref && (opts.ignoreKeywordsWithRef || !(0, util_1.schemaHasRulesButRef)(schema, RULES))) {
          gen.block(() => keywordCode(it, "$ref", RULES.all.$ref.definition));
          return;
        }
        if (!opts.jtd)
          checkStrictTypes(it, types);
        gen.block(() => {
          for (const group of RULES.rules)
            groupKeywords(group);
          groupKeywords(RULES.post);
        });
        function groupKeywords(group) {
          if (!(0, applicability_1.shouldUseGroup)(schema, group))
            return;
          if (group.type) {
            gen.if((0, dataType_2.checkDataType)(group.type, data, opts.strictNumbers));
            iterateKeywords(it, group);
            if (types.length === 1 && types[0] === group.type && typeErrors) {
              gen.else();
              (0, dataType_2.reportTypeError)(it);
            }
            gen.endIf();
          } else {
            iterateKeywords(it, group);
          }
          if (!allErrors)
            gen.if((0, codegen_1._)`${names_1.default.errors} === ${errsCount || 0}`);
        }
      }
      function iterateKeywords(it, group) {
        const { gen, schema, opts: { useDefaults } } = it;
        if (useDefaults)
          (0, defaults_1.assignDefaults)(it, group.type);
        gen.block(() => {
          for (const rule of group.rules) {
            if ((0, applicability_1.shouldUseRule)(schema, rule)) {
              keywordCode(it, rule.keyword, rule.definition, group.type);
            }
          }
        });
      }
      function checkStrictTypes(it, types) {
        if (it.schemaEnv.meta || !it.opts.strictTypes)
          return;
        checkContextTypes(it, types);
        if (!it.opts.allowUnionTypes)
          checkMultipleTypes(it, types);
        checkKeywordTypes(it, it.dataTypes);
      }
      function checkContextTypes(it, types) {
        if (!types.length)
          return;
        if (!it.dataTypes.length) {
          it.dataTypes = types;
          return;
        }
        types.forEach((t) => {
          if (!includesType(it.dataTypes, t)) {
            strictTypesError(it, `type "${t}" not allowed by context "${it.dataTypes.join(",")}"`);
          }
        });
        narrowSchemaTypes(it, types);
      }
      function checkMultipleTypes(it, ts) {
        if (ts.length > 1 && !(ts.length === 2 && ts.includes("null"))) {
          strictTypesError(it, "use allowUnionTypes to allow union type keyword");
        }
      }
      function checkKeywordTypes(it, ts) {
        const rules = it.self.RULES.all;
        for (const keyword in rules) {
          const rule = rules[keyword];
          if (typeof rule == "object" && (0, applicability_1.shouldUseRule)(it.schema, rule)) {
            const { type } = rule.definition;
            if (type.length && !type.some((t) => hasApplicableType(ts, t))) {
              strictTypesError(it, `missing type "${type.join(",")}" for keyword "${keyword}"`);
            }
          }
        }
      }
      function hasApplicableType(schTs, kwdT) {
        return schTs.includes(kwdT) || kwdT === "number" && schTs.includes("integer");
      }
      function includesType(ts, t) {
        return ts.includes(t) || t === "integer" && ts.includes("number");
      }
      function narrowSchemaTypes(it, withTypes) {
        const ts = [];
        for (const t of it.dataTypes) {
          if (includesType(withTypes, t))
            ts.push(t);
          else if (withTypes.includes("integer") && t === "number")
            ts.push("integer");
        }
        it.dataTypes = ts;
      }
      function strictTypesError(it, msg) {
        const schemaPath = it.schemaEnv.baseId + it.errSchemaPath;
        msg += ` at "${schemaPath}" (strictTypes)`;
        (0, util_1.checkStrictMode)(it, msg, it.opts.strictTypes);
      }
      var KeywordCxt = class {
        constructor(it, def, keyword) {
          (0, keyword_1.validateKeywordUsage)(it, def, keyword);
          this.gen = it.gen;
          this.allErrors = it.allErrors;
          this.keyword = keyword;
          this.data = it.data;
          this.schema = it.schema[keyword];
          this.$data = def.$data && it.opts.$data && this.schema && this.schema.$data;
          this.schemaValue = (0, util_1.schemaRefOrVal)(it, this.schema, keyword, this.$data);
          this.schemaType = def.schemaType;
          this.parentSchema = it.schema;
          this.params = {};
          this.it = it;
          this.def = def;
          if (this.$data) {
            this.schemaCode = it.gen.const("vSchema", getData(this.$data, it));
          } else {
            this.schemaCode = this.schemaValue;
            if (!(0, keyword_1.validSchemaType)(this.schema, def.schemaType, def.allowUndefined)) {
              throw new Error(`${keyword} value must be ${JSON.stringify(def.schemaType)}`);
            }
          }
          if ("code" in def ? def.trackErrors : def.errors !== false) {
            this.errsCount = it.gen.const("_errs", names_1.default.errors);
          }
        }
        result(condition, successAction, failAction) {
          this.failResult((0, codegen_1.not)(condition), successAction, failAction);
        }
        failResult(condition, successAction, failAction) {
          this.gen.if(condition);
          if (failAction)
            failAction();
          else
            this.error();
          if (successAction) {
            this.gen.else();
            successAction();
            if (this.allErrors)
              this.gen.endIf();
          } else {
            if (this.allErrors)
              this.gen.endIf();
            else
              this.gen.else();
          }
        }
        pass(condition, failAction) {
          this.failResult((0, codegen_1.not)(condition), void 0, failAction);
        }
        fail(condition) {
          if (condition === void 0) {
            this.error();
            if (!this.allErrors)
              this.gen.if(false);
            return;
          }
          this.gen.if(condition);
          this.error();
          if (this.allErrors)
            this.gen.endIf();
          else
            this.gen.else();
        }
        fail$data(condition) {
          if (!this.$data)
            return this.fail(condition);
          const { schemaCode } = this;
          this.fail((0, codegen_1._)`${schemaCode} !== undefined && (${(0, codegen_1.or)(this.invalid$data(), condition)})`);
        }
        error(append, errorParams, errorPaths) {
          if (errorParams) {
            this.setParams(errorParams);
            this._error(append, errorPaths);
            this.setParams({});
            return;
          }
          this._error(append, errorPaths);
        }
        _error(append, errorPaths) {
          ;
          (append ? errors_1.reportExtraError : errors_1.reportError)(this, this.def.error, errorPaths);
        }
        $dataError() {
          (0, errors_1.reportError)(this, this.def.$dataError || errors_1.keyword$DataError);
        }
        reset() {
          if (this.errsCount === void 0)
            throw new Error('add "trackErrors" to keyword definition');
          (0, errors_1.resetErrorsCount)(this.gen, this.errsCount);
        }
        ok(cond) {
          if (!this.allErrors)
            this.gen.if(cond);
        }
        setParams(obj, assign) {
          if (assign)
            Object.assign(this.params, obj);
          else
            this.params = obj;
        }
        block$data(valid, codeBlock, $dataValid = codegen_1.nil) {
          this.gen.block(() => {
            this.check$data(valid, $dataValid);
            codeBlock();
          });
        }
        check$data(valid = codegen_1.nil, $dataValid = codegen_1.nil) {
          if (!this.$data)
            return;
          const { gen, schemaCode, schemaType, def } = this;
          gen.if((0, codegen_1.or)((0, codegen_1._)`${schemaCode} === undefined`, $dataValid));
          if (valid !== codegen_1.nil)
            gen.assign(valid, true);
          if (schemaType.length || def.validateSchema) {
            gen.elseIf(this.invalid$data());
            this.$dataError();
            if (valid !== codegen_1.nil)
              gen.assign(valid, false);
          }
          gen.else();
        }
        invalid$data() {
          const { gen, schemaCode, schemaType, def, it } = this;
          return (0, codegen_1.or)(wrong$DataType(), invalid$DataSchema());
          function wrong$DataType() {
            if (schemaType.length) {
              if (!(schemaCode instanceof codegen_1.Name))
                throw new Error("ajv implementation error");
              const st = Array.isArray(schemaType) ? schemaType : [schemaType];
              return (0, codegen_1._)`${(0, dataType_2.checkDataTypes)(st, schemaCode, it.opts.strictNumbers, dataType_2.DataType.Wrong)}`;
            }
            return codegen_1.nil;
          }
          function invalid$DataSchema() {
            if (def.validateSchema) {
              const validateSchemaRef = gen.scopeValue("validate$data", { ref: def.validateSchema });
              return (0, codegen_1._)`!${validateSchemaRef}(${schemaCode})`;
            }
            return codegen_1.nil;
          }
        }
        subschema(appl, valid) {
          const subschema = (0, subschema_1.getSubschema)(this.it, appl);
          (0, subschema_1.extendSubschemaData)(subschema, this.it, appl);
          (0, subschema_1.extendSubschemaMode)(subschema, appl);
          const nextContext = { ...this.it, ...subschema, items: void 0, props: void 0 };
          subschemaCode(nextContext, valid);
          return nextContext;
        }
        mergeEvaluated(schemaCxt, toName) {
          const { it, gen } = this;
          if (!it.opts.unevaluated)
            return;
          if (it.props !== true && schemaCxt.props !== void 0) {
            it.props = util_1.mergeEvaluated.props(gen, schemaCxt.props, it.props, toName);
          }
          if (it.items !== true && schemaCxt.items !== void 0) {
            it.items = util_1.mergeEvaluated.items(gen, schemaCxt.items, it.items, toName);
          }
        }
        mergeValidEvaluated(schemaCxt, valid) {
          const { it, gen } = this;
          if (it.opts.unevaluated && (it.props !== true || it.items !== true)) {
            gen.if(valid, () => this.mergeEvaluated(schemaCxt, codegen_1.Name));
            return true;
          }
        }
      };
      exports.KeywordCxt = KeywordCxt;
      function keywordCode(it, keyword, def, ruleType) {
        const cxt = new KeywordCxt(it, def, keyword);
        if ("code" in def) {
          def.code(cxt, ruleType);
        } else if (cxt.$data && def.validate) {
          (0, keyword_1.funcKeywordCode)(cxt, def);
        } else if ("macro" in def) {
          (0, keyword_1.macroKeywordCode)(cxt, def);
        } else if (def.compile || def.validate) {
          (0, keyword_1.funcKeywordCode)(cxt, def);
        }
      }
      var JSON_POINTER = /^\/(?:[^~]|~0|~1)*$/;
      var RELATIVE_JSON_POINTER = /^([0-9]+)(#|\/(?:[^~]|~0|~1)*)?$/;
      function getData($data, { dataLevel, dataNames, dataPathArr }) {
        let jsonPointer;
        let data;
        if ($data === "")
          return names_1.default.rootData;
        if ($data[0] === "/") {
          if (!JSON_POINTER.test($data))
            throw new Error(`Invalid JSON-pointer: ${$data}`);
          jsonPointer = $data;
          data = names_1.default.rootData;
        } else {
          const matches = RELATIVE_JSON_POINTER.exec($data);
          if (!matches)
            throw new Error(`Invalid JSON-pointer: ${$data}`);
          const up = +matches[1];
          jsonPointer = matches[2];
          if (jsonPointer === "#") {
            if (up >= dataLevel)
              throw new Error(errorMsg("property/index", up));
            return dataPathArr[dataLevel - up];
          }
          if (up > dataLevel)
            throw new Error(errorMsg("data", up));
          data = dataNames[dataLevel - up];
          if (!jsonPointer)
            return data;
        }
        let expr = data;
        const segments = jsonPointer.split("/");
        for (const segment of segments) {
          if (segment) {
            data = (0, codegen_1._)`${data}${(0, codegen_1.getProperty)((0, util_1.unescapeJsonPointer)(segment))}`;
            expr = (0, codegen_1._)`${expr} && ${data}`;
          }
        }
        return expr;
        function errorMsg(pointerType, up) {
          return `Cannot access ${pointerType} ${up} levels up, current level is ${dataLevel}`;
        }
      }
      exports.getData = getData;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/validation_error.js
  var require_validation_error = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/validation_error.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var ValidationError = class extends Error {
        constructor(errors) {
          super("validation failed");
          this.errors = errors;
          this.ajv = this.validation = true;
        }
      };
      exports.default = ValidationError;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/ref_error.js
  var require_ref_error = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/ref_error.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var resolve_1 = require_resolve();
      var MissingRefError = class extends Error {
        constructor(resolver, baseId, ref, msg) {
          super(msg || `can't resolve reference ${ref} from id ${baseId}`);
          this.missingRef = (0, resolve_1.resolveUrl)(resolver, baseId, ref);
          this.missingSchema = (0, resolve_1.normalizeId)((0, resolve_1.getFullPath)(resolver, this.missingRef));
        }
      };
      exports.default = MissingRefError;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/index.js
  var require_compile = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/compile/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.resolveSchema = exports.getCompilingSchema = exports.resolveRef = exports.compileSchema = exports.SchemaEnv = void 0;
      var codegen_1 = require_codegen();
      var validation_error_1 = require_validation_error();
      var names_1 = require_names();
      var resolve_1 = require_resolve();
      var util_1 = require_util();
      var validate_1 = require_validate();
      var SchemaEnv = class {
        constructor(env) {
          var _a;
          this.refs = {};
          this.dynamicAnchors = {};
          let schema;
          if (typeof env.schema == "object")
            schema = env.schema;
          this.schema = env.schema;
          this.schemaId = env.schemaId;
          this.root = env.root || this;
          this.baseId = (_a = env.baseId) !== null && _a !== void 0 ? _a : (0, resolve_1.normalizeId)(schema === null || schema === void 0 ? void 0 : schema[env.schemaId || "$id"]);
          this.schemaPath = env.schemaPath;
          this.localRefs = env.localRefs;
          this.meta = env.meta;
          this.$async = schema === null || schema === void 0 ? void 0 : schema.$async;
          this.refs = {};
        }
      };
      exports.SchemaEnv = SchemaEnv;
      function compileSchema(sch) {
        const _sch = getCompilingSchema.call(this, sch);
        if (_sch)
          return _sch;
        const rootId = (0, resolve_1.getFullPath)(this.opts.uriResolver, sch.root.baseId);
        const { es5, lines } = this.opts.code;
        const { ownProperties } = this.opts;
        const gen = new codegen_1.CodeGen(this.scope, { es5, lines, ownProperties });
        let _ValidationError;
        if (sch.$async) {
          _ValidationError = gen.scopeValue("Error", {
            ref: validation_error_1.default,
            code: (0, codegen_1._)`require("ajv/dist/runtime/validation_error").default`
          });
        }
        const validateName = gen.scopeName("validate");
        sch.validateName = validateName;
        const schemaCxt = {
          gen,
          allErrors: this.opts.allErrors,
          data: names_1.default.data,
          parentData: names_1.default.parentData,
          parentDataProperty: names_1.default.parentDataProperty,
          dataNames: [names_1.default.data],
          dataPathArr: [codegen_1.nil],
          // TODO can its length be used as dataLevel if nil is removed?
          dataLevel: 0,
          dataTypes: [],
          definedProperties: /* @__PURE__ */ new Set(),
          topSchemaRef: gen.scopeValue("schema", this.opts.code.source === true ? { ref: sch.schema, code: (0, codegen_1.stringify)(sch.schema) } : { ref: sch.schema }),
          validateName,
          ValidationError: _ValidationError,
          schema: sch.schema,
          schemaEnv: sch,
          rootId,
          baseId: sch.baseId || rootId,
          schemaPath: codegen_1.nil,
          errSchemaPath: sch.schemaPath || (this.opts.jtd ? "" : "#"),
          errorPath: (0, codegen_1._)`""`,
          opts: this.opts,
          self: this
        };
        let sourceCode;
        try {
          this._compilations.add(sch);
          (0, validate_1.validateFunctionCode)(schemaCxt);
          gen.optimize(this.opts.code.optimize);
          const validateCode = gen.toString();
          sourceCode = `${gen.scopeRefs(names_1.default.scope)}return ${validateCode}`;
          if (this.opts.code.process)
            sourceCode = this.opts.code.process(sourceCode, sch);
          const makeValidate = new Function(`${names_1.default.self}`, `${names_1.default.scope}`, sourceCode);
          const validate = makeValidate(this, this.scope.get());
          this.scope.value(validateName, { ref: validate });
          validate.errors = null;
          validate.schema = sch.schema;
          validate.schemaEnv = sch;
          if (sch.$async)
            validate.$async = true;
          if (this.opts.code.source === true) {
            validate.source = { validateName, validateCode, scopeValues: gen._values };
          }
          if (this.opts.unevaluated) {
            const { props, items } = schemaCxt;
            validate.evaluated = {
              props: props instanceof codegen_1.Name ? void 0 : props,
              items: items instanceof codegen_1.Name ? void 0 : items,
              dynamicProps: props instanceof codegen_1.Name,
              dynamicItems: items instanceof codegen_1.Name
            };
            if (validate.source)
              validate.source.evaluated = (0, codegen_1.stringify)(validate.evaluated);
          }
          sch.validate = validate;
          return sch;
        } catch (e) {
          delete sch.validate;
          delete sch.validateName;
          if (sourceCode)
            this.logger.error("Error compiling schema, function code:", sourceCode);
          throw e;
        } finally {
          this._compilations.delete(sch);
        }
      }
      exports.compileSchema = compileSchema;
      function resolveRef(root, baseId, ref) {
        var _a;
        ref = (0, resolve_1.resolveUrl)(this.opts.uriResolver, baseId, ref);
        const schOrFunc = root.refs[ref];
        if (schOrFunc)
          return schOrFunc;
        let _sch = resolve.call(this, root, ref);
        if (_sch === void 0) {
          const schema = (_a = root.localRefs) === null || _a === void 0 ? void 0 : _a[ref];
          const { schemaId } = this.opts;
          if (schema)
            _sch = new SchemaEnv({ schema, schemaId, root, baseId });
        }
        if (_sch === void 0)
          return;
        return root.refs[ref] = inlineOrCompile.call(this, _sch);
      }
      exports.resolveRef = resolveRef;
      function inlineOrCompile(sch) {
        if ((0, resolve_1.inlineRef)(sch.schema, this.opts.inlineRefs))
          return sch.schema;
        return sch.validate ? sch : compileSchema.call(this, sch);
      }
      function getCompilingSchema(schEnv) {
        for (const sch of this._compilations) {
          if (sameSchemaEnv(sch, schEnv))
            return sch;
        }
      }
      exports.getCompilingSchema = getCompilingSchema;
      function sameSchemaEnv(s1, s2) {
        return s1.schema === s2.schema && s1.root === s2.root && s1.baseId === s2.baseId;
      }
      function resolve(root, ref) {
        let sch;
        while (typeof (sch = this.refs[ref]) == "string")
          ref = sch;
        return sch || this.schemas[ref] || resolveSchema.call(this, root, ref);
      }
      function resolveSchema(root, ref) {
        const p = this.opts.uriResolver.parse(ref);
        const refPath = (0, resolve_1._getFullPath)(this.opts.uriResolver, p);
        let baseId = (0, resolve_1.getFullPath)(this.opts.uriResolver, root.baseId, void 0);
        if (Object.keys(root.schema).length > 0 && refPath === baseId) {
          return getJsonPointer.call(this, p, root);
        }
        const id = (0, resolve_1.normalizeId)(refPath);
        const schOrRef = this.refs[id] || this.schemas[id];
        if (typeof schOrRef == "string") {
          const sch = resolveSchema.call(this, root, schOrRef);
          if (typeof (sch === null || sch === void 0 ? void 0 : sch.schema) !== "object")
            return;
          return getJsonPointer.call(this, p, sch);
        }
        if (typeof (schOrRef === null || schOrRef === void 0 ? void 0 : schOrRef.schema) !== "object")
          return;
        if (!schOrRef.validate)
          compileSchema.call(this, schOrRef);
        if (id === (0, resolve_1.normalizeId)(ref)) {
          const { schema } = schOrRef;
          const { schemaId } = this.opts;
          const schId = schema[schemaId];
          if (schId)
            baseId = (0, resolve_1.resolveUrl)(this.opts.uriResolver, baseId, schId);
          return new SchemaEnv({ schema, schemaId, root, baseId });
        }
        return getJsonPointer.call(this, p, schOrRef);
      }
      exports.resolveSchema = resolveSchema;
      var PREVENT_SCOPE_CHANGE = /* @__PURE__ */ new Set([
        "properties",
        "patternProperties",
        "enum",
        "dependencies",
        "definitions"
      ]);
      function getJsonPointer(parsedRef, { baseId, schema, root }) {
        var _a;
        if (((_a = parsedRef.fragment) === null || _a === void 0 ? void 0 : _a[0]) !== "/")
          return;
        for (const part of parsedRef.fragment.slice(1).split("/")) {
          if (typeof schema === "boolean")
            return;
          const partSchema = schema[(0, util_1.unescapeFragment)(part)];
          if (partSchema === void 0)
            return;
          schema = partSchema;
          const schId = typeof schema === "object" && schema[this.opts.schemaId];
          if (!PREVENT_SCOPE_CHANGE.has(part) && schId) {
            baseId = (0, resolve_1.resolveUrl)(this.opts.uriResolver, baseId, schId);
          }
        }
        let env;
        if (typeof schema != "boolean" && schema.$ref && !(0, util_1.schemaHasRulesButRef)(schema, this.RULES)) {
          const $ref = (0, resolve_1.resolveUrl)(this.opts.uriResolver, baseId, schema.$ref);
          env = resolveSchema.call(this, root, $ref);
        }
        const { schemaId } = this.opts;
        env = env || new SchemaEnv({ schema, schemaId, root, baseId });
        if (env.schema !== env.root.schema)
          return env;
        return void 0;
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/data.json
  var require_data = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/data.json"(exports, module) {
      module.exports = {
        $id: "https://raw.githubusercontent.com/ajv-validator/ajv/master/lib/refs/data.json#",
        description: "Meta-schema for $data reference (JSON AnySchema extension proposal)",
        type: "object",
        required: ["$data"],
        properties: {
          $data: {
            type: "string",
            anyOf: [{ format: "relative-json-pointer" }, { format: "json-pointer" }]
          }
        },
        additionalProperties: false
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/lib/utils.js
  var require_utils = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/lib/utils.js"(exports, module) {
      "use strict";
      var isUUID = RegExp.prototype.test.bind(/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/iu);
      var isIPv4 = RegExp.prototype.test.bind(/^(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]\d|\d)$/u);
      var isPort = RegExp.prototype.test.bind(/^\d*$/u);
      var isHexPair = RegExp.prototype.test.bind(/^[\da-f]{2}$/iu);
      var isUnreserved = RegExp.prototype.test.bind(/^[\da-z\-._~]$/iu);
      var isPathCharacter = RegExp.prototype.test.bind(/^[A-Za-z0-9\-._~!$&'()*+,;=:@/]$/u);
      var isQueryFragmentCharacter = RegExp.prototype.test.bind(/^[A-Za-z0-9\-._~!$&'()*+,;=:@/?]$/u);
      var isUserinfoCharacter = RegExp.prototype.test.bind(/^[A-Za-z0-9\-._~!$&'()*+,;=:]$/u);
      var BYTE_HEX = new Array(256);
      {
        const HEX_DIGITS = "0123456789ABCDEF";
        for (let i = 0; i < 256; i++) {
          BYTE_HEX[i] = "%" + HEX_DIGITS[i >> 4] + HEX_DIGITS[i & 15];
        }
      }
      function percentEncodeNonAscii(cp) {
        if (cp < 2048) {
          return BYTE_HEX[192 | cp >> 6] + BYTE_HEX[128 | cp & 63];
        }
        if (cp < 65536) {
          return BYTE_HEX[224 | cp >> 12] + BYTE_HEX[128 | cp >> 6 & 63] + BYTE_HEX[128 | cp & 63];
        }
        return BYTE_HEX[240 | cp >> 18] + BYTE_HEX[128 | cp >> 12 & 63] + BYTE_HEX[128 | cp >> 6 & 63] + BYTE_HEX[128 | cp & 63];
      }
      function stringArrayToHexStripped(input) {
        let acc = "";
        let code = 0;
        let i = 0;
        for (i = 0; i < input.length; i++) {
          code = input[i].charCodeAt(0);
          if (code === 48) {
            continue;
          }
          if (!(code >= 48 && code <= 57 || code >= 65 && code <= 70 || code >= 97 && code <= 102)) {
            return "";
          }
          acc += input[i];
          break;
        }
        for (i += 1; i < input.length; i++) {
          code = input[i].charCodeAt(0);
          if (!(code >= 48 && code <= 57 || code >= 65 && code <= 70 || code >= 97 && code <= 102)) {
            return "";
          }
          acc += input[i];
        }
        return acc;
      }
      var isHextet = RegExp.prototype.test.bind(/^[\dA-Fa-f]{1,4}$/);
      var isIPvFuture = RegExp.prototype.test.bind(/^[vV][\dA-Fa-f]+\.[A-Za-z\d\-._~!$&'()*+,;=:]+$/);
      var isZoneCharacter = RegExp.prototype.test.bind(/^[A-Za-z\d\-._~]$/);
      var nonSimpleDomain = RegExp.prototype.test.bind(/[^!"$&'()*+,\-.;=_`a-z{}~]/u);
      function isZoneIdentifier(zone) {
        if (zone.length === 0) return false;
        for (let i = 0; i < zone.length; i++) {
          if (isZoneCharacter(zone[i])) continue;
          if (zone[i] === "%" && i + 2 < zone.length && isHexPair(zone.slice(i + 1, i + 3))) {
            i += 2;
            continue;
          }
          return false;
        }
        return true;
      }
      function compressIPv6ZeroRun(hextets) {
        let bestStart = -1;
        let bestLength = 0;
        let runStart = -1;
        let runLength = 0;
        for (let i = 0; i < hextets.length; i++) {
          if (hextets[i] === "0") {
            if (runStart === -1) runStart = i;
            runLength++;
            if (runLength > bestLength) {
              bestLength = runLength;
              bestStart = runStart;
            }
          } else {
            runStart = -1;
            runLength = 0;
          }
        }
        if (bestLength < 2) return hextets.join(":");
        const head = hextets.slice(0, bestStart).join(":");
        const tail = hextets.slice(bestStart + bestLength).join(":");
        return head + "::" + tail;
      }
      function normalizeIPv6Address(input) {
        const compression = input.indexOf("::");
        if (compression !== -1 && input.indexOf("::", compression + 1) !== -1) return void 0;
        const left = compression === -1 ? input.split(":") : input.slice(0, compression).split(":");
        const right = compression === -1 ? [] : input.slice(compression + 2).split(":");
        if (compression !== -1) {
          if (left.length === 1 && left[0] === "") left.length = 0;
          if (right.length === 1 && right[0] === "") right.length = 0;
        }
        const parts = left.concat(right);
        let hextetCount = 0;
        for (let i = 0; i < parts.length; i++) {
          const part = parts[i];
          if (part === "") return void 0;
          if (part.indexOf(".") !== -1) {
            if (i !== parts.length - 1 || compression !== -1 && right.length === 0 || !isIPv4(part)) return void 0;
            hextetCount += 2;
            continue;
          }
          if (!isHextet(part)) return void 0;
          parts[i] = parseInt(part, 16).toString(16);
          hextetCount++;
        }
        if (compression === -1) {
          if (hextetCount !== 8) return void 0;
          return compressIPv6ZeroRun(parts);
        }
        if (hextetCount >= 8) return void 0;
        const expanded = parts.slice(0, left.length);
        for (let i = hextetCount; i < 8; i++) expanded.push("0");
        for (let i = left.length; i < parts.length; i++) expanded.push(parts[i]);
        return compressIPv6ZeroRun(expanded);
      }
      function normalizeIPv6(host) {
        const bracketed = host[0] === "[" && host[host.length - 1] === "]";
        const hasBracket = host[0] === "[" || host[host.length - 1] === "]";
        if (hasBracket && !bracketed) return { host, isIPV6: false, error: true };
        let input = bracketed ? host.slice(1, -1) : host;
        if (bracketed && isIPvFuture(input)) {
          input = input.toLowerCase();
          return { host: `[${input}]`, escapedHost: input, isIPV6: false, isIPVFuture: true };
        }
        if (findToken(input, ":") < 2) {
          return { host, isIPV6: false, error: bracketed };
        }
        let zoneIdentifier = "";
        const zoneSeparator = input.indexOf("%");
        if (zoneSeparator !== -1) {
          const separatorLength = input.slice(zoneSeparator, zoneSeparator + 3).toLowerCase() === "%25" ? 3 : 1;
          zoneIdentifier = input.slice(zoneSeparator + separatorLength);
          if (!isZoneIdentifier(zoneIdentifier)) return { host, isIPV6: false, error: true };
          input = input.slice(0, zoneSeparator);
        }
        const address = normalizeIPv6Address(input);
        if (address === void 0) return { host, isIPV6: false, error: true };
        return {
          host: address + (zoneIdentifier ? "%" + zoneIdentifier : ""),
          escapedHost: address + (zoneIdentifier ? "%25" + zoneIdentifier : ""),
          isIPV6: true
        };
      }
      function findToken(str, token) {
        let ind = 0;
        for (let i = 0; i < str.length; i++) {
          if (str[i] === token) ind++;
        }
        return ind;
      }
      function removeDotSegments(path) {
        let input = path;
        const output = [];
        let nextSlash = -1;
        let len = 0;
        while (len = input.length) {
          if (len === 1) {
            if (input === ".") {
              break;
            } else if (input === "/") {
              output.push("/");
              break;
            } else {
              output.push(input);
              break;
            }
          } else if (len === 2) {
            if (input[0] === ".") {
              if (input[1] === ".") {
                break;
              } else if (input[1] === "/") {
                input = input.slice(2);
                continue;
              }
            } else if (input[0] === "/") {
              if (input[1] === "." || input[1] === "/") {
                output.push("/");
                break;
              }
            }
          } else if (len === 3) {
            if (input === "/..") {
              if (output.length !== 0) {
                output.pop();
              }
              output.push("/");
              break;
            }
          }
          if (input[0] === ".") {
            if (input[1] === ".") {
              if (input[2] === "/") {
                input = input.slice(3);
                continue;
              }
            } else if (input[1] === "/") {
              input = input.slice(2);
              continue;
            }
          } else if (input[0] === "/") {
            if (input[1] === ".") {
              if (input[2] === "/") {
                input = input.slice(2);
                continue;
              } else if (input[2] === ".") {
                if (input[3] === "/") {
                  input = input.slice(3);
                  if (output.length !== 0) {
                    output.pop();
                  }
                  continue;
                }
              }
            }
          }
          if ((nextSlash = input.indexOf("/", 1)) === -1) {
            output.push(input);
            break;
          } else {
            output.push(input.slice(0, nextSlash));
            input = input.slice(nextSlash);
          }
        }
        return output.join("");
      }
      var HOST_DELIMS = { "@": "%40", "/": "%2F", "?": "%3F", "#": "%23", ":": "%3A" };
      var HOST_DELIM_RE = /[@/?#:]/g;
      var HOST_DELIM_NO_COLON_RE = /[@/?#]/g;
      function reescapeHostDelimiters(host, isIP) {
        const re = isIP ? HOST_DELIM_NO_COLON_RE : HOST_DELIM_RE;
        re.lastIndex = 0;
        return host.replace(re, (ch) => HOST_DELIMS[ch]);
      }
      function normalizePercentEncoding(input, decodeUnreserved = false) {
        if (input.indexOf("%") === -1) {
          return input;
        }
        let output = "";
        for (let i = 0; i < input.length; i++) {
          if (input[i] === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              const normalizedHex = hex.toUpperCase();
              const decoded = String.fromCharCode(parseInt(normalizedHex, 16));
              if (decodeUnreserved && isUnreserved(decoded)) {
                output += decoded;
              } else {
                output += "%" + normalizedHex;
              }
              i += 2;
              continue;
            }
          }
          output += input[i];
        }
        return output;
      }
      function normalizePathEncoding(input) {
        let output = "";
        for (let i = 0; i < input.length; i++) {
          const ch = input[i];
          if (ch === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              const normalizedHex = hex.toUpperCase();
              const decoded = String.fromCharCode(parseInt(normalizedHex, 16));
              if (decoded !== "." && isUnreserved(decoded)) {
                output += decoded;
              } else {
                output += "%" + normalizedHex;
              }
              i += 2;
              continue;
            }
          }
          if (isPathCharacter(ch)) {
            output += ch;
          } else {
            const code = input.charCodeAt(i);
            if (code < 128) {
              output += isEscapeSafe(code) ? ch : BYTE_HEX[code];
            } else if (code < 55296 || code > 57343) {
              output += percentEncodeNonAscii(code);
            } else if (code <= 56319 && i + 1 < input.length) {
              const low = input.charCodeAt(i + 1);
              if (low >= 56320 && low <= 57343) {
                output += percentEncodeNonAscii(65536 + (code - 55296 << 10) + (low - 56320));
                i++;
              } else {
                output += percentEncodeNonAscii(65533);
              }
            } else {
              output += percentEncodeNonAscii(65533);
            }
          }
        }
        return output;
      }
      function serializePathEncoding(input, pathNoScheme = false) {
        let output = "";
        let firstSegment = pathNoScheme && input[0] !== "/";
        for (let i = 0; i < input.length; i++) {
          const ch = input[i];
          if (ch === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              output += "%" + hex.toUpperCase();
              i += 2;
              continue;
            }
          }
          if (ch === "/") {
            firstSegment = false;
          }
          if (isPathCharacter(ch) && (ch !== ":" || !firstSegment)) {
            output += ch;
          } else {
            const code = input.charCodeAt(i);
            if (code < 128) {
              output += BYTE_HEX[code];
            } else if (code < 55296 || code > 57343) {
              output += percentEncodeNonAscii(code);
            } else if (code <= 56319 && i + 1 < input.length) {
              const low = input.charCodeAt(i + 1);
              if (low >= 56320 && low <= 57343) {
                output += percentEncodeNonAscii(65536 + (code - 55296 << 10) + (low - 56320));
                i++;
              } else {
                output += percentEncodeNonAscii(65533);
              }
            } else {
              output += percentEncodeNonAscii(65533);
            }
          }
        }
        return output;
      }
      function encodeComponent(input, isAllowed) {
        let output = "";
        for (let i = 0; i < input.length; i++) {
          const ch = input[i];
          if (ch === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              output += "%" + hex.toUpperCase();
              i += 2;
              continue;
            }
          }
          if (isAllowed(ch)) {
            output += ch;
          } else {
            const code = input.charCodeAt(i);
            if (code < 128) {
              output += BYTE_HEX[code];
            } else if (code < 55296 || code > 57343) {
              output += percentEncodeNonAscii(code);
            } else if (code <= 56319 && i + 1 < input.length) {
              const low = input.charCodeAt(i + 1);
              if (low >= 56320 && low <= 57343) {
                output += percentEncodeNonAscii(65536 + (code - 55296 << 10) + (low - 56320));
                i++;
              } else {
                output += percentEncodeNonAscii(65533);
              }
            } else {
              output += percentEncodeNonAscii(65533);
            }
          }
        }
        return output;
      }
      function encodeUserinfo(input) {
        return encodeComponent(input, isUserinfoCharacter);
      }
      function encodeQuery(input) {
        return encodeComponent(input, isQueryFragmentCharacter);
      }
      function encodeFragment(input) {
        return encodeComponent(input, isQueryFragmentCharacter);
      }
      function isEscapeSafe(cp) {
        return cp >= 48 && cp <= 57 || cp >= 65 && cp <= 90 || cp >= 97 && cp <= 122 || cp === 42 || cp === 43 || cp === 45 || cp === 46 || cp === 47 || cp === 64 || cp === 95;
      }
      function normalizeQueryFragmentEncoding(input) {
        let output = "";
        for (let i = 0; i < input.length; i++) {
          const ch = input[i];
          if (ch === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              const normalizedHex = hex.toUpperCase();
              const decoded = String.fromCharCode(parseInt(normalizedHex, 16));
              if (isUnreserved(decoded)) {
                output += decoded;
              } else {
                output += "%" + normalizedHex;
              }
              i += 2;
              continue;
            }
          }
          if (isQueryFragmentCharacter(ch)) {
            output += ch;
          } else {
            const code = input.charCodeAt(i);
            if (code < 128) {
              output += isEscapeSafe(code) ? ch : BYTE_HEX[code];
            } else if (code < 55296 || code > 57343) {
              output += percentEncodeNonAscii(code);
            } else if (code <= 56319 && i + 1 < input.length) {
              const low = input.charCodeAt(i + 1);
              if (low >= 56320 && low <= 57343) {
                output += percentEncodeNonAscii(65536 + (code - 55296 << 10) + (low - 56320));
                i++;
              } else {
                output += percentEncodeNonAscii(65533);
              }
            } else {
              output += percentEncodeNonAscii(65533);
            }
          }
        }
        return output;
      }
      function escapePreservingEscapes(input) {
        let output = "";
        for (let i = 0; i < input.length; i++) {
          if (input[i] === "%" && i + 2 < input.length) {
            const hex = input.slice(i + 1, i + 3);
            if (isHexPair(hex)) {
              output += "%" + hex.toUpperCase();
              i += 2;
              continue;
            }
          }
          output += escape(input[i]);
        }
        return output;
      }
      function recomposeAuthority(component) {
        const uriTokens = [];
        if (component.userinfo !== void 0) {
          uriTokens.push(encodeUserinfo(component.userinfo));
          uriTokens.push("@");
        }
        if (component.host !== void 0) {
          let host = component.host;
          if (!isIPv4(host)) {
            let ipV6res = normalizeIPv6(host);
            if (ipV6res.isIPV6 !== true && ipV6res.isIPVFuture !== true) {
              host = normalizePercentEncoding(host, true);
              ipV6res = normalizeIPv6(host);
            }
            if (ipV6res.isIPV6 === true || ipV6res.isIPVFuture === true) {
              host = `[${ipV6res.escapedHost}]`;
            } else {
              host = reescapeHostDelimiters(host, false);
            }
          }
          uriTokens.push(host);
        }
        if (typeof component.port === "number" || typeof component.port === "string") {
          const port = String(component.port);
          if (!isPort(port)) {
            throw new TypeError("URI port is malformed.");
          }
          uriTokens.push(":");
          uriTokens.push(port);
        }
        return uriTokens.length ? uriTokens.join("") : void 0;
      }
      module.exports = {
        nonSimpleDomain,
        recomposeAuthority,
        reescapeHostDelimiters,
        normalizePercentEncoding,
        normalizePathEncoding,
        serializePathEncoding,
        normalizeQueryFragmentEncoding,
        encodeUserinfo,
        encodeQuery,
        encodeFragment,
        escapePreservingEscapes,
        removeDotSegments,
        isIPv4,
        isUUID,
        normalizeIPv6,
        stringArrayToHexStripped
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/lib/schemes.js
  var require_schemes = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/lib/schemes.js"(exports, module) {
      "use strict";
      var { isUUID } = require_utils();
      var URN_REG = /^([\da-z][\d\-a-z]{0,31}):((?:[\w!$'()*+,\-./:;=@]|%[\da-f]{2})+)$/iu;
      var supportedSchemeNames = (
        /** @type {const} */
        [
          "http",
          "https",
          "ws",
          "wss",
          "urn",
          "urn:uuid"
        ]
      );
      function isValidSchemeName(name) {
        return supportedSchemeNames.indexOf(
          /** @type {*} */
          name
        ) !== -1;
      }
      function wsIsSecure(wsComponent) {
        if (wsComponent.secure === true) {
          return true;
        } else if (wsComponent.secure === false) {
          return false;
        } else if (wsComponent.scheme) {
          return wsComponent.scheme.length === 3 && (wsComponent.scheme[0] === "w" || wsComponent.scheme[0] === "W") && (wsComponent.scheme[1] === "s" || wsComponent.scheme[1] === "S") && (wsComponent.scheme[2] === "s" || wsComponent.scheme[2] === "S");
        } else {
          return false;
        }
      }
      function httpParse(component) {
        if (!component.host) {
          component.error = component.error || "HTTP URIs must have a host.";
        }
        return component;
      }
      function httpSerialize(component) {
        const secure = String(component.scheme).toLowerCase() === "https";
        if (component.port === (secure ? 443 : 80) || component.port === "") {
          component.port = void 0;
        }
        if (!component.path) {
          component.path = "/";
        }
        return component;
      }
      function wsParse(wsComponent) {
        wsComponent.secure = wsIsSecure(wsComponent);
        wsComponent.resourceName = (wsComponent.path || "/") + (wsComponent.query ? "?" + wsComponent.query : "");
        wsComponent.path = void 0;
        wsComponent.query = void 0;
        return wsComponent;
      }
      function wsSerialize(wsComponent) {
        if (wsComponent.port === (wsIsSecure(wsComponent) ? 443 : 80) || wsComponent.port === "") {
          wsComponent.port = void 0;
        }
        if (typeof wsComponent.secure === "boolean") {
          wsComponent.scheme = wsComponent.secure ? "wss" : "ws";
          wsComponent.secure = void 0;
        }
        if (wsComponent.resourceName) {
          const queryIndex = wsComponent.resourceName.indexOf("?");
          const path = queryIndex === -1 ? wsComponent.resourceName : wsComponent.resourceName.slice(0, queryIndex);
          wsComponent.path = path && path !== "/" ? path : void 0;
          wsComponent.query = queryIndex === -1 ? void 0 : wsComponent.resourceName.slice(queryIndex + 1);
          wsComponent.resourceName = void 0;
        }
        wsComponent.fragment = void 0;
        return wsComponent;
      }
      function urnParse(urnComponent, options) {
        if (!urnComponent.path) {
          urnComponent.error = "URN can not be parsed";
          return urnComponent;
        }
        const matches = urnComponent.path.match(URN_REG);
        if (matches && matches[0] === urnComponent.path) {
          const scheme = options.scheme || urnComponent.scheme || "urn";
          urnComponent.nid = matches[1].toLowerCase();
          urnComponent.nss = matches[2];
          const urnScheme = `${scheme}:${options.nid || urnComponent.nid}`;
          const schemeHandler = getSchemeHandler(urnScheme);
          urnComponent.path = void 0;
          if (schemeHandler) {
            urnComponent = schemeHandler.parse(urnComponent, options);
          }
        } else {
          urnComponent.error = urnComponent.error || "URN can not be parsed.";
        }
        return urnComponent;
      }
      function urnSerialize(urnComponent, options) {
        if (urnComponent.nid === void 0) {
          throw new Error("URN without nid cannot be serialized");
        }
        const scheme = options.scheme || urnComponent.scheme || "urn";
        const nid = urnComponent.nid.toLowerCase();
        const urnScheme = `${scheme}:${options.nid || nid}`;
        const schemeHandler = getSchemeHandler(urnScheme);
        if (schemeHandler) {
          urnComponent = schemeHandler.serialize(urnComponent, options);
        }
        const uriComponent = urnComponent;
        const nss = urnComponent.nss;
        uriComponent.path = `${nid || options.nid}:${nss}`;
        options.skipEscape = true;
        return uriComponent;
      }
      function urnuuidParse(urnComponent, options) {
        const uuidComponent = urnComponent;
        uuidComponent.uuid = uuidComponent.nss;
        uuidComponent.nss = void 0;
        if (!options.tolerant && (!uuidComponent.uuid || !isUUID(uuidComponent.uuid))) {
          uuidComponent.error = uuidComponent.error || "UUID is not valid.";
        }
        return uuidComponent;
      }
      function urnuuidSerialize(uuidComponent) {
        const urnComponent = uuidComponent;
        urnComponent.nss = (uuidComponent.uuid || "").toLowerCase();
        return urnComponent;
      }
      var http = (
        /** @type {SchemeHandler} */
        {
          scheme: "http",
          domainHost: true,
          parse: httpParse,
          serialize: httpSerialize
        }
      );
      var https = (
        /** @type {SchemeHandler} */
        {
          scheme: "https",
          domainHost: http.domainHost,
          parse: httpParse,
          serialize: httpSerialize
        }
      );
      var ws = (
        /** @type {SchemeHandler} */
        {
          scheme: "ws",
          domainHost: true,
          parse: wsParse,
          serialize: wsSerialize
        }
      );
      var wss = (
        /** @type {SchemeHandler} */
        {
          scheme: "wss",
          domainHost: ws.domainHost,
          parse: ws.parse,
          serialize: ws.serialize
        }
      );
      var urn = (
        /** @type {SchemeHandler} */
        {
          scheme: "urn",
          parse: urnParse,
          serialize: urnSerialize,
          skipNormalize: true
        }
      );
      var urnuuid = (
        /** @type {SchemeHandler} */
        {
          scheme: "urn:uuid",
          parse: urnuuidParse,
          serialize: urnuuidSerialize,
          skipNormalize: true
        }
      );
      var SCHEMES = (
        /** @type {Record<SchemeName, SchemeHandler>} */
        {
          http,
          https,
          ws,
          wss,
          urn,
          "urn:uuid": urnuuid
        }
      );
      Object.setPrototypeOf(SCHEMES, null);
      function getSchemeHandler(scheme) {
        return scheme && (SCHEMES[
          /** @type {SchemeName} */
          scheme
        ] || SCHEMES[
          /** @type {SchemeName} */
          scheme.toLowerCase()
        ]) || void 0;
      }
      module.exports = {
        wsIsSecure,
        SCHEMES,
        isValidSchemeName,
        getSchemeHandler
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/index.js
  var require_fast_uri = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/fast-uri@3.1.8/node_modules/fast-uri/index.js"(exports, module) {
      "use strict";
      var { normalizeIPv6, removeDotSegments, recomposeAuthority, normalizePercentEncoding, normalizePathEncoding, serializePathEncoding, normalizeQueryFragmentEncoding, encodeQuery, encodeFragment, reescapeHostDelimiters, isIPv4, nonSimpleDomain } = require_utils();
      var { SCHEMES, getSchemeHandler } = require_schemes();
      var VALID_SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*$/u;
      var MALFORMED_SCHEME_ERROR = "URI scheme is malformed.";
      function decodeValidScheme(scheme) {
        const decodedScheme = unescape(String(scheme));
        if (!VALID_SCHEME.test(decodedScheme)) {
          throw new TypeError(MALFORMED_SCHEME_ERROR);
        }
        return decodedScheme;
      }
      function normalize(uri, options) {
        if (typeof uri === "string") {
          uri = /** @type {T} */
          normalizeString(uri, options);
        } else if (typeof uri === "object") {
          uri = /** @type {T} */
          parse(serialize(uri, options), options);
        }
        return uri;
      }
      function resolve(baseURI, relativeURI, options) {
        const schemelessOptions = options ? Object.assign({ scheme: "null" }, options) : { scheme: "null" };
        const {
          parsed: baseParsed,
          malformedAuthorityOrPort: baseMalformed,
          malformedPercentEncoding: baseMalformedPercentEncoding,
          malformedSchemeSpecific: baseMalformedSchemeSpecific,
          malformedHost: baseMalformedHost,
          malformedScheme: baseMalformedScheme
        } = parseWithStatus(baseURI, schemelessOptions);
        const {
          parsed: relativeParsed,
          malformedAuthorityOrPort: relativeMalformed,
          malformedPercentEncoding: relativeMalformedPercentEncoding,
          malformedSchemeSpecific: relativeMalformedSchemeSpecific,
          malformedHost: relativeMalformedHost,
          malformedScheme: relativeMalformedScheme
        } = parseWithStatus(relativeURI, schemelessOptions);
        if (baseMalformed || relativeMalformed || baseMalformedPercentEncoding || relativeMalformedPercentEncoding || baseMalformedSchemeSpecific || relativeMalformedSchemeSpecific || baseMalformedHost || relativeMalformedHost || baseMalformedScheme || relativeMalformedScheme) {
          throw new Error(baseParsed.error || relativeParsed.error || "URI is malformed.");
        }
        const resolved = resolveComponent(baseParsed, relativeParsed, schemelessOptions, true);
        const resolvedSchemeHandler = getSchemeHandler(options && options.scheme || resolved.scheme);
        const resolvedHost = resolved.host;
        const resolvedHostIsIP = resolvedHost !== void 0 && resolvedHost !== "" && (isIPv4(resolvedHost) || normalizeIPv6(resolvedHost).isIPV6);
        canonicalizeHost(resolved, options || {}, resolvedSchemeHandler, resolvedHostIsIP);
        const encodedASCIIHost = resolvedHost && resolvedHost.indexOf("%") !== -1 && !/\P{ASCII}/u.test(resolvedHost);
        if (resolved.error && !encodedASCIIHost) {
          throw new Error(resolved.error);
        }
        schemelessOptions.skipEscape = true;
        return serialize(resolved, schemelessOptions);
      }
      function resolveComponent(base, relative, options, skipNormalization) {
        const target = {};
        if (!skipNormalization) {
          base = parse(serialize(base, options), options);
          relative = parse(serialize(relative, options), options);
        }
        options = options || {};
        if (!options.tolerant && relative.scheme) {
          target.scheme = relative.scheme;
          target.userinfo = relative.userinfo;
          target.host = relative.host;
          target.port = relative.port;
          target.path = removeDotSegments(relative.path || "");
          target.query = relative.query;
        } else {
          if (relative.userinfo !== void 0 || relative.host !== void 0 || relative.port !== void 0) {
            target.userinfo = relative.userinfo;
            target.host = relative.host;
            target.port = relative.port;
            target.path = removeDotSegments(relative.path || "");
            target.query = relative.query;
          } else {
            if (!relative.path) {
              target.path = base.path;
              if (relative.query !== void 0) {
                target.query = relative.query;
              } else {
                target.query = base.query;
              }
            } else {
              if (relative.path[0] === "/") {
                target.path = removeDotSegments(relative.path);
              } else {
                if ((base.userinfo !== void 0 || base.host !== void 0 || base.port !== void 0) && !base.path) {
                  target.path = "/" + relative.path;
                } else if (!base.path) {
                  target.path = relative.path;
                } else {
                  target.path = base.path.slice(0, base.path.lastIndexOf("/") + 1) + relative.path;
                }
                target.path = removeDotSegments(target.path);
              }
              target.query = relative.query;
            }
            target.userinfo = base.userinfo;
            target.host = base.host;
            target.port = base.port;
          }
          target.scheme = base.scheme;
        }
        target.fragment = relative.fragment;
        return target;
      }
      function equal(uriA, uriB, options) {
        const normalizedA = normalizeComparableURI(uriA, options);
        const normalizedB = normalizeComparableURI(uriB, options);
        return normalizedA !== void 0 && normalizedB !== void 0 && normalizedA === normalizedB;
      }
      function serialize(cmpts, opts) {
        const component = {
          host: cmpts.host,
          scheme: cmpts.scheme,
          userinfo: cmpts.userinfo,
          port: cmpts.port,
          path: cmpts.path,
          query: cmpts.query,
          nid: cmpts.nid,
          nss: cmpts.nss,
          uuid: cmpts.uuid,
          fragment: cmpts.fragment,
          reference: cmpts.reference,
          resourceName: cmpts.resourceName,
          secure: cmpts.secure,
          error: ""
        };
        const options = Object.assign({}, opts);
        const uriTokens = [];
        if (component.scheme) {
          component.scheme = decodeValidScheme(component.scheme);
        }
        const schemeHandler = getSchemeHandler(options.scheme || component.scheme);
        if (schemeHandler && schemeHandler.serialize) schemeHandler.serialize(component, options);
        const hasAuthority = component.userinfo !== void 0 || component.host !== void 0 || component.port !== void 0;
        const pathNoScheme = !options.skipEscape && component.scheme === void 0 && !hasAuthority;
        if (component.path !== void 0) {
          if (!options.skipEscape) {
            component.path = serializePathEncoding(component.path, pathNoScheme);
          } else {
            component.path = normalizePercentEncoding(component.path);
          }
        }
        if (options.reference !== "suffix" && component.scheme) {
          component.scheme = decodeValidScheme(component.scheme);
          uriTokens.push(component.scheme, ":");
        }
        const authority = recomposeAuthority(component);
        if (authority !== void 0) {
          if (options.reference !== "suffix") {
            uriTokens.push("//");
          }
          uriTokens.push(authority);
          if (component.path && component.path[0] !== "/") {
            uriTokens.push("/");
          }
        }
        if (component.path !== void 0) {
          let s = component.path;
          if (!options.absolutePath && (!schemeHandler || !schemeHandler.absolutePath)) {
            s = removeDotSegments(s);
          }
          if (pathNoScheme) {
            s = serializePathEncoding(s, true);
          }
          if (authority === void 0 && s[0] === "/" && s[1] === "/") {
            s = "/%2F" + s.slice(2);
          }
          uriTokens.push(s);
        }
        if (component.query !== void 0) {
          uriTokens.push("?", encodeQuery(component.query));
        }
        if (component.fragment !== void 0) {
          uriTokens.push("#", encodeFragment(component.fragment));
        }
        return uriTokens.join("");
      }
      var URI_PARSE = /^(?:([^#/:?]+):)?(?:\/\/((?:([^#/?@]*)@)?(\[[^#/?\]]+\]|[^#/:?]*)(?::(\d*))?))?([^#?]*)(?:\?([^#]*))?(?:#((?:.|[\n\r])*))?/u;
      var AUTHORITY_PREFIX = /^(?:[^#/:?]+:)?\/\/([^/?#]*)/;
      var AUTHORITY_INTRODUCER_REGION = /^(?:[^#/:?]+:)?([/\\\t\n\r]*)/;
      function getParseError(parsed, matches) {
        if (matches[2] !== void 0 && parsed.path && parsed.path[0] !== "/") {
          return 'URI path must start with "/" when authority is present.';
        }
        if (typeof parsed.port === "number" && (parsed.port < 0 || parsed.port > 65535)) {
          return "URI port is malformed.";
        }
        return void 0;
      }
      function hasMalformedPercentEncoding(component) {
        if (component === void 0) return false;
        let percent = component.indexOf("%");
        while (percent !== -1) {
          if (percent + 2 >= component.length || !/^[\da-f]{2}$/iu.test(component.slice(percent + 1, percent + 3))) {
            return true;
          }
          percent = component.indexOf("%", percent + 3);
        }
        return false;
      }
      function isIPLiteral(host) {
        return host[0] === "[" && host[host.length - 1] === "]";
      }
      function hasMalformedComponentPercentEncoding(matches) {
        const host = matches[4];
        return hasMalformedPercentEncoding(matches[3]) || host !== void 0 && !isIPLiteral(host) && hasMalformedPercentEncoding(host) || hasMalformedPercentEncoding(matches[6]) || hasMalformedPercentEncoding(matches[7]) || hasMalformedPercentEncoding(matches[8]);
      }
      function canonicalizeHost(parsed, options, schemeHandler, isIP) {
        if (!options.unicodeSupport && (!schemeHandler || !schemeHandler.unicodeSupport) && parsed.host && !isIPLiteral(parsed.host) && (options.domainHost || schemeHandler && schemeHandler.domainHost) && isIP === false && nonSimpleDomain(parsed.host)) {
          try {
            parsed.host = new URL("http://" + parsed.host).hostname;
          } catch (e) {
            parsed.error = parsed.error || "Host's domain name can not be converted to ASCII: " + e;
            return true;
          }
        }
        return false;
      }
      function parseWithStatus(uri, opts) {
        const options = Object.assign({}, opts);
        const parsed = {
          scheme: void 0,
          userinfo: void 0,
          host: "",
          port: void 0,
          path: "",
          query: void 0,
          fragment: void 0
        };
        let malformedAuthorityOrPort = false;
        let malformedPercentEncoding = false;
        let malformedSchemeSpecific = false;
        let malformedHost = false;
        let malformedIPLiteral = false;
        let malformedScheme = false;
        let isIP = false;
        if (options.reference === "suffix") {
          if (options.scheme) {
            uri = options.scheme + ":" + uri;
          } else {
            uri = "//" + uri;
          }
        }
        const authorityMatch = uri.match(AUTHORITY_PREFIX);
        if (authorityMatch !== null && authorityMatch[1].indexOf("\\") !== -1) {
          parsed.error = "URI authority must not contain a literal backslash.";
          malformedAuthorityOrPort = true;
        }
        const introducerMatch = uri.match(AUTHORITY_INTRODUCER_REGION);
        if (introducerMatch !== null) {
          const region = introducerMatch[1];
          const normalizedRegion = region.replace(/[\t\n\r]/g, "");
          if (normalizedRegion.length >= 2) {
            if (normalizedRegion.slice(0, 2) !== "//") {
              parsed.error = parsed.error || "URI authority must not contain a literal backslash.";
              malformedAuthorityOrPort = true;
            } else if (region.length !== normalizedRegion.length) {
              parsed.error = parsed.error || "URI authority introducer must not contain whitespace.";
              malformedAuthorityOrPort = true;
            }
          }
        }
        const matches = uri.match(URI_PARSE);
        if (matches) {
          parsed.scheme = matches[1];
          parsed.userinfo = matches[3];
          parsed.host = matches[4];
          parsed.port = parseInt(matches[5], 10);
          parsed.path = matches[6] || "";
          parsed.query = matches[7];
          parsed.fragment = matches[8];
          if (parsed.scheme !== void 0) {
            const decodedScheme = unescape(parsed.scheme);
            if (VALID_SCHEME.test(decodedScheme)) {
              parsed.scheme = decodedScheme.toLowerCase();
            } else {
              parsed.error = parsed.error || MALFORMED_SCHEME_ERROR;
              malformedScheme = true;
            }
          }
          malformedPercentEncoding = hasMalformedComponentPercentEncoding(matches);
          if (malformedPercentEncoding) {
            parsed.error = parsed.error || "URI contains malformed percent-encoding.";
          }
          if (isNaN(parsed.port)) {
            parsed.port = matches[5];
          }
          const parseError = getParseError(parsed, matches);
          if (parseError !== void 0) {
            parsed.error = parsed.error || parseError;
            malformedAuthorityOrPort = true;
          }
          if (parsed.host) {
            const ipv4result = isIPv4(parsed.host);
            if (ipv4result === false) {
              const bracketedIPLiteral = isIPLiteral(parsed.host);
              const hasIPLiteralBracket = parsed.host.indexOf("[") !== -1 || parsed.host.indexOf("]") !== -1;
              const ipv6result = normalizeIPv6(parsed.host);
              isIP = ipv6result.isIPV6 || ipv6result.isIPVFuture === true;
              malformedIPLiteral = hasIPLiteralBracket && (!bracketedIPLiteral || ipv6result.error === true);
              parsed.host = isIP ? ipv6result.host : ipv6result.host.toLowerCase();
              if (malformedIPLiteral) {
                parsed.error = parsed.error || "URI host is malformed.";
                malformedAuthorityOrPort = true;
              }
            } else {
              isIP = true;
            }
          }
          if (parsed.scheme === void 0 && parsed.userinfo === void 0 && parsed.host === void 0 && parsed.port === void 0 && parsed.query === void 0 && !parsed.path) {
            parsed.reference = "same-document";
          } else if (parsed.scheme === void 0) {
            parsed.reference = "relative";
          } else if (parsed.fragment === void 0) {
            parsed.reference = "absolute";
          } else {
            parsed.reference = "uri";
          }
          if (options.reference && options.reference !== "suffix" && options.reference !== parsed.reference) {
            parsed.error = parsed.error || "URI is not a " + options.reference + " reference.";
          }
          const schemeHandler = getSchemeHandler(options.scheme || parsed.scheme);
          if (!malformedIPLiteral) {
            malformedHost = canonicalizeHost(parsed, options, schemeHandler, isIP);
          }
          if (uri.indexOf("%") !== -1 && parsed.host !== void 0 && !malformedIPLiteral) {
            let host = isIP ? parsed.host : normalizePercentEncoding(parsed.host, true);
            if (!isIP) {
              host = normalizePercentEncoding(host.toLowerCase());
            }
            parsed.host = reescapeHostDelimiters(host, isIP);
          }
          if (!schemeHandler || schemeHandler && !schemeHandler.skipNormalize) {
            if (parsed.path) {
              parsed.path = normalizePathEncoding(parsed.path);
            }
            if (parsed.query) {
              parsed.query = normalizeQueryFragmentEncoding(parsed.query);
            }
            if (parsed.fragment) {
              parsed.fragment = normalizeQueryFragmentEncoding(parsed.fragment);
            }
          }
          if (schemeHandler && schemeHandler.parse) {
            schemeHandler.parse(parsed, options);
            if (schemeHandler === SCHEMES.urn && parsed.nid === void 0) {
              malformedSchemeSpecific = true;
            }
          }
        } else {
          parsed.error = parsed.error || "URI can not be parsed.";
        }
        return { parsed, malformedAuthorityOrPort, malformedPercentEncoding, malformedSchemeSpecific, malformedHost, malformedScheme };
      }
      function parse(uri, opts) {
        return parseWithStatus(uri, opts).parsed;
      }
      function normalizeString(uri, opts) {
        return normalizeStringWithStatus(uri, opts).normalized;
      }
      function normalizeStringWithStatus(uri, opts) {
        const { parsed, malformedAuthorityOrPort, malformedPercentEncoding, malformedSchemeSpecific, malformedHost, malformedScheme } = parseWithStatus(uri, opts);
        return {
          normalized: malformedAuthorityOrPort || malformedPercentEncoding || malformedSchemeSpecific || malformedHost || malformedScheme ? uri : serialize(parsed, opts),
          malformedAuthorityOrPort,
          malformedPercentEncoding,
          malformedSchemeSpecific,
          malformedHost,
          malformedScheme
        };
      }
      function normalizeComparableURI(uri, opts) {
        if (typeof uri !== "string" && typeof uri !== "object") {
          return void 0;
        }
        let value;
        try {
          value = typeof uri === "string" ? uri : serialize(uri, opts);
        } catch {
          return void 0;
        }
        const { normalized, malformedAuthorityOrPort, malformedPercentEncoding, malformedSchemeSpecific, malformedHost, malformedScheme } = normalizeStringWithStatus(value, opts);
        return malformedAuthorityOrPort || malformedPercentEncoding || malformedSchemeSpecific || malformedHost || malformedScheme ? void 0 : normalized;
      }
      var fastUri = {
        SCHEMES,
        normalize,
        resolve,
        resolveComponent,
        equal,
        serialize,
        parse
      };
      module.exports = fastUri;
      module.exports.default = fastUri;
      module.exports.fastUri = fastUri;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/uri.js
  var require_uri = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/uri.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var uri = require_fast_uri();
      uri.code = 'require("ajv/dist/runtime/uri").default';
      exports.default = uri;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/core.js
  var require_core = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/core.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.CodeGen = exports.Name = exports.nil = exports.stringify = exports.str = exports._ = exports.KeywordCxt = void 0;
      var validate_1 = require_validate();
      Object.defineProperty(exports, "KeywordCxt", { enumerable: true, get: function() {
        return validate_1.KeywordCxt;
      } });
      var codegen_1 = require_codegen();
      Object.defineProperty(exports, "_", { enumerable: true, get: function() {
        return codegen_1._;
      } });
      Object.defineProperty(exports, "str", { enumerable: true, get: function() {
        return codegen_1.str;
      } });
      Object.defineProperty(exports, "stringify", { enumerable: true, get: function() {
        return codegen_1.stringify;
      } });
      Object.defineProperty(exports, "nil", { enumerable: true, get: function() {
        return codegen_1.nil;
      } });
      Object.defineProperty(exports, "Name", { enumerable: true, get: function() {
        return codegen_1.Name;
      } });
      Object.defineProperty(exports, "CodeGen", { enumerable: true, get: function() {
        return codegen_1.CodeGen;
      } });
      var validation_error_1 = require_validation_error();
      var ref_error_1 = require_ref_error();
      var rules_1 = require_rules();
      var compile_1 = require_compile();
      var codegen_2 = require_codegen();
      var resolve_1 = require_resolve();
      var dataType_1 = require_dataType();
      var util_1 = require_util();
      var $dataRefSchema = require_data();
      var uri_1 = require_uri();
      var defaultRegExp = (str, flags) => new RegExp(str, flags);
      defaultRegExp.code = "new RegExp";
      var META_IGNORE_OPTIONS = ["removeAdditional", "useDefaults", "coerceTypes"];
      var EXT_SCOPE_NAMES = /* @__PURE__ */ new Set([
        "validate",
        "serialize",
        "parse",
        "wrapper",
        "root",
        "schema",
        "keyword",
        "pattern",
        "formats",
        "validate$data",
        "func",
        "obj",
        "Error"
      ]);
      var removedOptions = {
        errorDataPath: "",
        format: "`validateFormats: false` can be used instead.",
        nullable: '"nullable" keyword is supported by default.',
        jsonPointers: "Deprecated jsPropertySyntax can be used instead.",
        extendRefs: "Deprecated ignoreKeywordsWithRef can be used instead.",
        missingRefs: "Pass empty schema with $id that should be ignored to ajv.addSchema.",
        processCode: "Use option `code: {process: (code, schemaEnv: object) => string}`",
        sourceCode: "Use option `code: {source: true}`",
        strictDefaults: "It is default now, see option `strict`.",
        strictKeywords: "It is default now, see option `strict`.",
        uniqueItems: '"uniqueItems" keyword is always validated.',
        unknownFormats: "Disable strict mode or pass `true` to `ajv.addFormat` (or `formats` option).",
        cache: "Map is used as cache, schema object as key.",
        serialize: "Map is used as cache, schema object as key.",
        ajvErrors: "It is default now."
      };
      var deprecatedOptions = {
        ignoreKeywordsWithRef: "",
        jsPropertySyntax: "",
        unicode: '"minLength"/"maxLength" account for unicode characters by default.'
      };
      var MAX_EXPRESSION = 200;
      function requiredOptions(o) {
        var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _0;
        const s = o.strict;
        const _optz = (_a = o.code) === null || _a === void 0 ? void 0 : _a.optimize;
        const optimize = _optz === true || _optz === void 0 ? 1 : _optz || 0;
        const regExp = (_c = (_b = o.code) === null || _b === void 0 ? void 0 : _b.regExp) !== null && _c !== void 0 ? _c : defaultRegExp;
        const uriResolver = (_d = o.uriResolver) !== null && _d !== void 0 ? _d : uri_1.default;
        return {
          strictSchema: (_f = (_e = o.strictSchema) !== null && _e !== void 0 ? _e : s) !== null && _f !== void 0 ? _f : true,
          strictNumbers: (_h = (_g = o.strictNumbers) !== null && _g !== void 0 ? _g : s) !== null && _h !== void 0 ? _h : true,
          strictTypes: (_k = (_j = o.strictTypes) !== null && _j !== void 0 ? _j : s) !== null && _k !== void 0 ? _k : "log",
          strictTuples: (_m = (_l = o.strictTuples) !== null && _l !== void 0 ? _l : s) !== null && _m !== void 0 ? _m : "log",
          strictRequired: (_p = (_o = o.strictRequired) !== null && _o !== void 0 ? _o : s) !== null && _p !== void 0 ? _p : false,
          code: o.code ? { ...o.code, optimize, regExp } : { optimize, regExp },
          loopRequired: (_q = o.loopRequired) !== null && _q !== void 0 ? _q : MAX_EXPRESSION,
          loopEnum: (_r = o.loopEnum) !== null && _r !== void 0 ? _r : MAX_EXPRESSION,
          meta: (_s = o.meta) !== null && _s !== void 0 ? _s : true,
          messages: (_t = o.messages) !== null && _t !== void 0 ? _t : true,
          inlineRefs: (_u = o.inlineRefs) !== null && _u !== void 0 ? _u : true,
          schemaId: (_v = o.schemaId) !== null && _v !== void 0 ? _v : "$id",
          addUsedSchema: (_w = o.addUsedSchema) !== null && _w !== void 0 ? _w : true,
          validateSchema: (_x = o.validateSchema) !== null && _x !== void 0 ? _x : true,
          validateFormats: (_y = o.validateFormats) !== null && _y !== void 0 ? _y : true,
          unicodeRegExp: (_z = o.unicodeRegExp) !== null && _z !== void 0 ? _z : true,
          int32range: (_0 = o.int32range) !== null && _0 !== void 0 ? _0 : true,
          uriResolver
        };
      }
      var Ajv = class {
        constructor(opts = {}) {
          this.schemas = {};
          this.refs = {};
          this.formats = /* @__PURE__ */ Object.create(null);
          this._compilations = /* @__PURE__ */ new Set();
          this._loading = {};
          this._cache = /* @__PURE__ */ new Map();
          opts = this.opts = { ...opts, ...requiredOptions(opts) };
          const { es5, lines } = this.opts.code;
          this.scope = new codegen_2.ValueScope({ scope: {}, prefixes: EXT_SCOPE_NAMES, es5, lines });
          this.logger = getLogger(opts.logger);
          const formatOpt = opts.validateFormats;
          opts.validateFormats = false;
          this.RULES = (0, rules_1.getRules)();
          checkOptions.call(this, removedOptions, opts, "NOT SUPPORTED");
          checkOptions.call(this, deprecatedOptions, opts, "DEPRECATED", "warn");
          this._metaOpts = getMetaSchemaOptions.call(this);
          if (opts.formats)
            addInitialFormats.call(this);
          this._addVocabularies();
          this._addDefaultMetaSchema();
          if (opts.keywords)
            addInitialKeywords.call(this, opts.keywords);
          if (typeof opts.meta == "object")
            this.addMetaSchema(opts.meta);
          addInitialSchemas.call(this);
          opts.validateFormats = formatOpt;
        }
        _addVocabularies() {
          this.addKeyword("$async");
        }
        _addDefaultMetaSchema() {
          const { $data, meta, schemaId } = this.opts;
          let _dataRefSchema = $dataRefSchema;
          if (schemaId === "id") {
            _dataRefSchema = { ...$dataRefSchema };
            _dataRefSchema.id = _dataRefSchema.$id;
            delete _dataRefSchema.$id;
          }
          if (meta && $data)
            this.addMetaSchema(_dataRefSchema, _dataRefSchema[schemaId], false);
        }
        defaultMeta() {
          const { meta, schemaId } = this.opts;
          return this.opts.defaultMeta = typeof meta == "object" ? meta[schemaId] || meta : void 0;
        }
        validate(schemaKeyRef, data) {
          let v;
          if (typeof schemaKeyRef == "string") {
            v = this.getSchema(schemaKeyRef);
            if (!v)
              throw new Error(`no schema with key or ref "${schemaKeyRef}"`);
          } else {
            v = this.compile(schemaKeyRef);
          }
          const valid = v(data);
          if (!("$async" in v))
            this.errors = v.errors;
          return valid;
        }
        compile(schema, _meta) {
          const sch = this._addSchema(schema, _meta);
          return sch.validate || this._compileSchemaEnv(sch);
        }
        compileAsync(schema, meta) {
          if (typeof this.opts.loadSchema != "function") {
            throw new Error("options.loadSchema should be a function");
          }
          const { loadSchema } = this.opts;
          return runCompileAsync.call(this, schema, meta);
          async function runCompileAsync(_schema, _meta) {
            await loadMetaSchema.call(this, _schema.$schema);
            const sch = this._addSchema(_schema, _meta);
            return sch.validate || _compileAsync.call(this, sch);
          }
          async function loadMetaSchema($ref) {
            if ($ref && !this.getSchema($ref)) {
              await runCompileAsync.call(this, { $ref }, true);
            }
          }
          async function _compileAsync(sch) {
            try {
              return this._compileSchemaEnv(sch);
            } catch (e) {
              if (!(e instanceof ref_error_1.default))
                throw e;
              checkLoaded.call(this, e);
              await loadMissingSchema.call(this, e.missingSchema);
              return _compileAsync.call(this, sch);
            }
          }
          function checkLoaded({ missingSchema: ref, missingRef }) {
            if (this.refs[ref]) {
              throw new Error(`AnySchema ${ref} is loaded but ${missingRef} cannot be resolved`);
            }
          }
          async function loadMissingSchema(ref) {
            const _schema = await _loadSchema.call(this, ref);
            if (!this.refs[ref])
              await loadMetaSchema.call(this, _schema.$schema);
            if (!this.refs[ref])
              this.addSchema(_schema, ref, meta);
          }
          async function _loadSchema(ref) {
            const p = this._loading[ref];
            if (p)
              return p;
            try {
              return await (this._loading[ref] = loadSchema(ref));
            } finally {
              delete this._loading[ref];
            }
          }
        }
        // Adds schema to the instance
        addSchema(schema, key, _meta, _validateSchema = this.opts.validateSchema) {
          if (Array.isArray(schema)) {
            for (const sch of schema)
              this.addSchema(sch, void 0, _meta, _validateSchema);
            return this;
          }
          let id;
          if (typeof schema === "object") {
            const { schemaId } = this.opts;
            id = schema[schemaId];
            if (id !== void 0 && typeof id != "string") {
              throw new Error(`schema ${schemaId} must be string`);
            }
          }
          key = (0, resolve_1.normalizeId)(key || id);
          this._checkUnique(key);
          this.schemas[key] = this._addSchema(schema, _meta, key, _validateSchema, true);
          return this;
        }
        // Add schema that will be used to validate other schemas
        // options in META_IGNORE_OPTIONS are alway set to false
        addMetaSchema(schema, key, _validateSchema = this.opts.validateSchema) {
          this.addSchema(schema, key, true, _validateSchema);
          return this;
        }
        //  Validate schema against its meta-schema
        validateSchema(schema, throwOrLogError) {
          if (typeof schema == "boolean")
            return true;
          let $schema;
          $schema = schema.$schema;
          if ($schema !== void 0 && typeof $schema != "string") {
            throw new Error("$schema must be a string");
          }
          $schema = $schema || this.opts.defaultMeta || this.defaultMeta();
          if (!$schema) {
            this.logger.warn("meta-schema not available");
            this.errors = null;
            return true;
          }
          const valid = this.validate($schema, schema);
          if (!valid && throwOrLogError) {
            const message = "schema is invalid: " + this.errorsText();
            if (this.opts.validateSchema === "log")
              this.logger.error(message);
            else
              throw new Error(message);
          }
          return valid;
        }
        // Get compiled schema by `key` or `ref`.
        // (`key` that was passed to `addSchema` or full schema reference - `schema.$id` or resolved id)
        getSchema(keyRef) {
          let sch;
          while (typeof (sch = getSchEnv.call(this, keyRef)) == "string")
            keyRef = sch;
          if (sch === void 0) {
            const { schemaId } = this.opts;
            const root = new compile_1.SchemaEnv({ schema: {}, schemaId });
            sch = compile_1.resolveSchema.call(this, root, keyRef);
            if (!sch)
              return;
            this.refs[keyRef] = sch;
          }
          return sch.validate || this._compileSchemaEnv(sch);
        }
        // Remove cached schema(s).
        // If no parameter is passed all schemas but meta-schemas are removed.
        // If RegExp is passed all schemas with key/id matching pattern but meta-schemas are removed.
        // Even if schema is referenced by other schemas it still can be removed as other schemas have local references.
        removeSchema(schemaKeyRef) {
          if (schemaKeyRef instanceof RegExp) {
            this._removeAllSchemas(this.schemas, schemaKeyRef);
            this._removeAllSchemas(this.refs, schemaKeyRef);
            return this;
          }
          switch (typeof schemaKeyRef) {
            case "undefined":
              this._removeAllSchemas(this.schemas);
              this._removeAllSchemas(this.refs);
              this._cache.clear();
              return this;
            case "string": {
              const sch = getSchEnv.call(this, schemaKeyRef);
              if (typeof sch == "object")
                this._cache.delete(sch.schema);
              delete this.schemas[schemaKeyRef];
              delete this.refs[schemaKeyRef];
              return this;
            }
            case "object": {
              const cacheKey = schemaKeyRef;
              this._cache.delete(cacheKey);
              let id = schemaKeyRef[this.opts.schemaId];
              if (id) {
                id = (0, resolve_1.normalizeId)(id);
                delete this.schemas[id];
                delete this.refs[id];
              }
              return this;
            }
            default:
              throw new Error("ajv.removeSchema: invalid parameter");
          }
        }
        // add "vocabulary" - a collection of keywords
        addVocabulary(definitions) {
          for (const def of definitions)
            this.addKeyword(def);
          return this;
        }
        addKeyword(kwdOrDef, def) {
          let keyword;
          if (typeof kwdOrDef == "string") {
            keyword = kwdOrDef;
            if (typeof def == "object") {
              this.logger.warn("these parameters are deprecated, see docs for addKeyword");
              def.keyword = keyword;
            }
          } else if (typeof kwdOrDef == "object" && def === void 0) {
            def = kwdOrDef;
            keyword = def.keyword;
            if (Array.isArray(keyword) && !keyword.length) {
              throw new Error("addKeywords: keyword must be string or non-empty array");
            }
          } else {
            throw new Error("invalid addKeywords parameters");
          }
          checkKeyword.call(this, keyword, def);
          if (!def) {
            (0, util_1.eachItem)(keyword, (kwd) => addRule.call(this, kwd));
            return this;
          }
          keywordMetaschema.call(this, def);
          const definition = {
            ...def,
            type: (0, dataType_1.getJSONTypes)(def.type),
            schemaType: (0, dataType_1.getJSONTypes)(def.schemaType)
          };
          (0, util_1.eachItem)(keyword, definition.type.length === 0 ? (k) => addRule.call(this, k, definition) : (k) => definition.type.forEach((t) => addRule.call(this, k, definition, t)));
          return this;
        }
        getKeyword(keyword) {
          const rule = this.RULES.all[keyword];
          return typeof rule == "object" ? rule.definition : !!rule;
        }
        // Remove keyword
        removeKeyword(keyword) {
          const { RULES } = this;
          delete RULES.keywords[keyword];
          delete RULES.all[keyword];
          for (const group of RULES.rules) {
            const i = group.rules.findIndex((rule) => rule.keyword === keyword);
            if (i >= 0)
              group.rules.splice(i, 1);
          }
          return this;
        }
        // Add format
        addFormat(name, format) {
          if (typeof format == "string")
            format = new RegExp(format);
          this.formats[name] = format;
          return this;
        }
        errorsText(errors = this.errors, { separator = ", ", dataVar = "data" } = {}) {
          if (!errors || errors.length === 0)
            return "No errors";
          return errors.map((e) => `${dataVar}${e.instancePath} ${e.message}`).reduce((text, msg) => text + separator + msg);
        }
        $dataMetaSchema(metaSchema, keywordsJsonPointers) {
          const rules = this.RULES.all;
          metaSchema = JSON.parse(JSON.stringify(metaSchema));
          for (const jsonPointer of keywordsJsonPointers) {
            const segments = jsonPointer.split("/").slice(1);
            let keywords = metaSchema;
            for (const seg of segments)
              keywords = keywords[seg];
            for (const key in rules) {
              const rule = rules[key];
              if (typeof rule != "object")
                continue;
              const { $data } = rule.definition;
              const schema = keywords[key];
              if ($data && schema)
                keywords[key] = schemaOrData(schema);
            }
          }
          return metaSchema;
        }
        _removeAllSchemas(schemas, regex) {
          for (const keyRef in schemas) {
            const sch = schemas[keyRef];
            if (!regex || regex.test(keyRef)) {
              if (typeof sch == "string") {
                delete schemas[keyRef];
              } else if (sch && !sch.meta) {
                this._cache.delete(sch.schema);
                delete schemas[keyRef];
              }
            }
          }
        }
        _addSchema(schema, meta, baseId, validateSchema = this.opts.validateSchema, addSchema = this.opts.addUsedSchema) {
          let id;
          const { schemaId } = this.opts;
          if (typeof schema == "object") {
            id = schema[schemaId];
          } else {
            if (this.opts.jtd)
              throw new Error("schema must be object");
            else if (typeof schema != "boolean")
              throw new Error("schema must be object or boolean");
          }
          let sch = this._cache.get(schema);
          if (sch !== void 0)
            return sch;
          baseId = (0, resolve_1.normalizeId)(id || baseId);
          const localRefs = resolve_1.getSchemaRefs.call(this, schema, baseId);
          sch = new compile_1.SchemaEnv({ schema, schemaId, meta, baseId, localRefs });
          this._cache.set(sch.schema, sch);
          if (addSchema && !baseId.startsWith("#")) {
            if (baseId)
              this._checkUnique(baseId);
            this.refs[baseId] = sch;
          }
          if (validateSchema)
            this.validateSchema(schema, true);
          return sch;
        }
        _checkUnique(id) {
          if (this.schemas[id] || this.refs[id]) {
            throw new Error(`schema with key or id "${id}" already exists`);
          }
        }
        _compileSchemaEnv(sch) {
          if (sch.meta)
            this._compileMetaSchema(sch);
          else
            compile_1.compileSchema.call(this, sch);
          if (!sch.validate)
            throw new Error("ajv implementation error");
          return sch.validate;
        }
        _compileMetaSchema(sch) {
          const currentOpts = this.opts;
          this.opts = this._metaOpts;
          try {
            compile_1.compileSchema.call(this, sch);
          } finally {
            this.opts = currentOpts;
          }
        }
      };
      Ajv.ValidationError = validation_error_1.default;
      Ajv.MissingRefError = ref_error_1.default;
      exports.default = Ajv;
      function checkOptions(checkOpts, options, msg, log = "error") {
        for (const key in checkOpts) {
          const opt = key;
          if (opt in options)
            this.logger[log](`${msg}: option ${key}. ${checkOpts[opt]}`);
        }
      }
      function getSchEnv(keyRef) {
        keyRef = (0, resolve_1.normalizeId)(keyRef);
        return this.schemas[keyRef] || this.refs[keyRef];
      }
      function addInitialSchemas() {
        const optsSchemas = this.opts.schemas;
        if (!optsSchemas)
          return;
        if (Array.isArray(optsSchemas))
          this.addSchema(optsSchemas);
        else
          for (const key in optsSchemas)
            this.addSchema(optsSchemas[key], key);
      }
      function addInitialFormats() {
        for (const name in this.opts.formats) {
          const format = this.opts.formats[name];
          if (format)
            this.addFormat(name, format);
        }
      }
      function addInitialKeywords(defs) {
        if (Array.isArray(defs)) {
          this.addVocabulary(defs);
          return;
        }
        this.logger.warn("keywords option as map is deprecated, pass array");
        for (const keyword in defs) {
          const def = defs[keyword];
          if (!def.keyword)
            def.keyword = keyword;
          this.addKeyword(def);
        }
      }
      function getMetaSchemaOptions() {
        const metaOpts = { ...this.opts };
        for (const opt of META_IGNORE_OPTIONS)
          delete metaOpts[opt];
        return metaOpts;
      }
      var noLogs = { log() {
      }, warn() {
      }, error() {
      } };
      function getLogger(logger) {
        if (logger === false)
          return noLogs;
        if (logger === void 0)
          return console;
        if (logger.log && logger.warn && logger.error)
          return logger;
        throw new Error("logger must implement log, warn and error methods");
      }
      var KEYWORD_NAME = /^[a-z_$][a-z0-9_$:-]*$/i;
      function checkKeyword(keyword, def) {
        const { RULES } = this;
        (0, util_1.eachItem)(keyword, (kwd) => {
          if (RULES.keywords[kwd])
            throw new Error(`Keyword ${kwd} is already defined`);
          if (!KEYWORD_NAME.test(kwd))
            throw new Error(`Keyword ${kwd} has invalid name`);
        });
        if (!def)
          return;
        if (def.$data && !("code" in def || "validate" in def)) {
          throw new Error('$data keyword must have "code" or "validate" function');
        }
      }
      function addRule(keyword, definition, dataType) {
        var _a;
        const post = definition === null || definition === void 0 ? void 0 : definition.post;
        if (dataType && post)
          throw new Error('keyword with "post" flag cannot have "type"');
        const { RULES } = this;
        let ruleGroup = post ? RULES.post : RULES.rules.find(({ type: t }) => t === dataType);
        if (!ruleGroup) {
          ruleGroup = { type: dataType, rules: [] };
          RULES.rules.push(ruleGroup);
        }
        RULES.keywords[keyword] = true;
        if (!definition)
          return;
        const rule = {
          keyword,
          definition: {
            ...definition,
            type: (0, dataType_1.getJSONTypes)(definition.type),
            schemaType: (0, dataType_1.getJSONTypes)(definition.schemaType)
          }
        };
        if (definition.before)
          addBeforeRule.call(this, ruleGroup, rule, definition.before);
        else
          ruleGroup.rules.push(rule);
        RULES.all[keyword] = rule;
        (_a = definition.implements) === null || _a === void 0 ? void 0 : _a.forEach((kwd) => this.addKeyword(kwd));
      }
      function addBeforeRule(ruleGroup, rule, before) {
        const i = ruleGroup.rules.findIndex((_rule) => _rule.keyword === before);
        if (i >= 0) {
          ruleGroup.rules.splice(i, 0, rule);
        } else {
          ruleGroup.rules.push(rule);
          this.logger.warn(`rule ${before} is not defined`);
        }
      }
      function keywordMetaschema(def) {
        let { metaSchema } = def;
        if (metaSchema === void 0)
          return;
        if (def.$data && this.opts.$data)
          metaSchema = schemaOrData(metaSchema);
        def.validateSchema = this.compile(metaSchema, true);
      }
      var $dataRef = {
        $ref: "https://raw.githubusercontent.com/ajv-validator/ajv/master/lib/refs/data.json#"
      };
      function schemaOrData(schema) {
        return { anyOf: [schema, $dataRef] };
      }
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/id.js
  var require_id = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/id.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var def = {
        keyword: "id",
        code() {
          throw new Error('NOT SUPPORTED: keyword "id", use "$id" for schema ID');
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/ref.js
  var require_ref = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/ref.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.callRef = exports.getValidate = void 0;
      var ref_error_1 = require_ref_error();
      var code_1 = require_code2();
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var compile_1 = require_compile();
      var util_1 = require_util();
      var def = {
        keyword: "$ref",
        schemaType: "string",
        code(cxt) {
          const { gen, schema: $ref, it } = cxt;
          const { baseId, schemaEnv: env, validateName, opts, self } = it;
          const { root } = env;
          if (($ref === "#" || $ref === "#/") && baseId === root.baseId)
            return callRootRef();
          const schOrEnv = compile_1.resolveRef.call(self, root, baseId, $ref);
          if (schOrEnv === void 0)
            throw new ref_error_1.default(it.opts.uriResolver, baseId, $ref);
          if (schOrEnv instanceof compile_1.SchemaEnv)
            return callValidate(schOrEnv);
          return inlineRefSchema(schOrEnv);
          function callRootRef() {
            if (env === root)
              return callRef(cxt, validateName, env, env.$async);
            const rootName = gen.scopeValue("root", { ref: root });
            return callRef(cxt, (0, codegen_1._)`${rootName}.validate`, root, root.$async);
          }
          function callValidate(sch) {
            const v = getValidate(cxt, sch);
            callRef(cxt, v, sch, sch.$async);
          }
          function inlineRefSchema(sch) {
            const schName = gen.scopeValue("schema", opts.code.source === true ? { ref: sch, code: (0, codegen_1.stringify)(sch) } : { ref: sch });
            const valid = gen.name("valid");
            const schCxt = cxt.subschema({
              schema: sch,
              dataTypes: [],
              schemaPath: codegen_1.nil,
              topSchemaRef: schName,
              errSchemaPath: $ref
            }, valid);
            cxt.mergeEvaluated(schCxt);
            cxt.ok(valid);
          }
        }
      };
      function getValidate(cxt, sch) {
        const { gen } = cxt;
        return sch.validate ? gen.scopeValue("validate", { ref: sch.validate }) : (0, codegen_1._)`${gen.scopeValue("wrapper", { ref: sch })}.validate`;
      }
      exports.getValidate = getValidate;
      function callRef(cxt, v, sch, $async) {
        const { gen, it } = cxt;
        const { allErrors, schemaEnv: env, opts } = it;
        const passCxt = opts.passContext ? names_1.default.this : codegen_1.nil;
        if ($async)
          callAsyncRef();
        else
          callSyncRef();
        function callAsyncRef() {
          if (!env.$async)
            throw new Error("async schema referenced by sync schema");
          const valid = gen.let("valid");
          gen.try(() => {
            gen.code((0, codegen_1._)`await ${(0, code_1.callValidateCode)(cxt, v, passCxt)}`);
            addEvaluatedFrom(v);
            if (!allErrors)
              gen.assign(valid, true);
          }, (e) => {
            gen.if((0, codegen_1._)`!(${e} instanceof ${it.ValidationError})`, () => gen.throw(e));
            addErrorsFrom(e);
            if (!allErrors)
              gen.assign(valid, false);
          });
          cxt.ok(valid);
        }
        function callSyncRef() {
          cxt.result((0, code_1.callValidateCode)(cxt, v, passCxt), () => addEvaluatedFrom(v), () => addErrorsFrom(v));
        }
        function addErrorsFrom(source) {
          const errs = (0, codegen_1._)`${source}.errors`;
          gen.assign(names_1.default.vErrors, (0, codegen_1._)`${names_1.default.vErrors} === null ? ${errs} : ${names_1.default.vErrors}.concat(${errs})`);
          gen.assign(names_1.default.errors, (0, codegen_1._)`${names_1.default.vErrors}.length`);
        }
        function addEvaluatedFrom(source) {
          var _a;
          if (!it.opts.unevaluated)
            return;
          const schEvaluated = (_a = sch === null || sch === void 0 ? void 0 : sch.validate) === null || _a === void 0 ? void 0 : _a.evaluated;
          if (it.props !== true) {
            if (schEvaluated && !schEvaluated.dynamicProps) {
              if (schEvaluated.props !== void 0) {
                it.props = util_1.mergeEvaluated.props(gen, schEvaluated.props, it.props);
              }
            } else {
              const props = gen.var("props", (0, codegen_1._)`${source}.evaluated.props`);
              it.props = util_1.mergeEvaluated.props(gen, props, it.props, codegen_1.Name);
            }
          }
          if (it.items !== true) {
            if (schEvaluated && !schEvaluated.dynamicItems) {
              if (schEvaluated.items !== void 0) {
                it.items = util_1.mergeEvaluated.items(gen, schEvaluated.items, it.items);
              }
            } else {
              const items = gen.var("items", (0, codegen_1._)`${source}.evaluated.items`);
              it.items = util_1.mergeEvaluated.items(gen, items, it.items, codegen_1.Name);
            }
          }
        }
      }
      exports.callRef = callRef;
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/index.js
  var require_core2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/core/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var id_1 = require_id();
      var ref_1 = require_ref();
      var core = [
        "$schema",
        "$id",
        "$defs",
        "$vocabulary",
        { keyword: "$comment" },
        "definitions",
        id_1.default,
        ref_1.default
      ];
      exports.default = core;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitNumber.js
  var require_limitNumber = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitNumber.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var ops = codegen_1.operators;
      var KWDs = {
        maximum: { okStr: "<=", ok: ops.LTE, fail: ops.GT },
        minimum: { okStr: ">=", ok: ops.GTE, fail: ops.LT },
        exclusiveMaximum: { okStr: "<", ok: ops.LT, fail: ops.GTE },
        exclusiveMinimum: { okStr: ">", ok: ops.GT, fail: ops.LTE }
      };
      var error = {
        message: ({ keyword, schemaCode }) => (0, codegen_1.str)`must be ${KWDs[keyword].okStr} ${schemaCode}`,
        params: ({ keyword, schemaCode }) => (0, codegen_1._)`{comparison: ${KWDs[keyword].okStr}, limit: ${schemaCode}}`
      };
      var def = {
        keyword: Object.keys(KWDs),
        type: "number",
        schemaType: "number",
        $data: true,
        error,
        code(cxt) {
          const { keyword, data, schemaCode } = cxt;
          cxt.fail$data((0, codegen_1._)`${data} ${KWDs[keyword].fail} ${schemaCode} || isNaN(${data})`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/multipleOf.js
  var require_multipleOf = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/multipleOf.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var error = {
        message: ({ schemaCode }) => (0, codegen_1.str)`must be multiple of ${schemaCode}`,
        params: ({ schemaCode }) => (0, codegen_1._)`{multipleOf: ${schemaCode}}`
      };
      var def = {
        keyword: "multipleOf",
        type: "number",
        schemaType: "number",
        $data: true,
        error,
        code(cxt) {
          const { gen, data, schemaCode, it } = cxt;
          const prec = it.opts.multipleOfPrecision;
          const res = gen.let("res");
          const invalid = prec ? (0, codegen_1._)`Math.abs(Math.round(${res}) - ${res}) > 1e-${prec}` : (0, codegen_1._)`${res} !== parseInt(${res})`;
          cxt.fail$data((0, codegen_1._)`(${schemaCode} === 0 || (${res} = ${data}/${schemaCode}, ${invalid}))`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/ucs2length.js
  var require_ucs2length = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/ucs2length.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      function ucs2length(str) {
        const len = str.length;
        let length = 0;
        let pos = 0;
        let value;
        while (pos < len) {
          length++;
          value = str.charCodeAt(pos++);
          if (value >= 55296 && value <= 56319 && pos < len) {
            value = str.charCodeAt(pos);
            if ((value & 64512) === 56320)
              pos++;
          }
        }
        return length;
      }
      exports.default = ucs2length;
      ucs2length.code = 'require("ajv/dist/runtime/ucs2length").default';
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitLength.js
  var require_limitLength = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitLength.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var ucs2length_1 = require_ucs2length();
      var error = {
        message({ keyword, schemaCode }) {
          const comp = keyword === "maxLength" ? "more" : "fewer";
          return (0, codegen_1.str)`must NOT have ${comp} than ${schemaCode} characters`;
        },
        params: ({ schemaCode }) => (0, codegen_1._)`{limit: ${schemaCode}}`
      };
      var def = {
        keyword: ["maxLength", "minLength"],
        type: "string",
        schemaType: "number",
        $data: true,
        error,
        code(cxt) {
          const { keyword, data, schemaCode, it } = cxt;
          const op = keyword === "maxLength" ? codegen_1.operators.GT : codegen_1.operators.LT;
          const len = it.opts.unicode === false ? (0, codegen_1._)`${data}.length` : (0, codegen_1._)`${(0, util_1.useFunc)(cxt.gen, ucs2length_1.default)}(${data})`;
          cxt.fail$data((0, codegen_1._)`${len} ${op} ${schemaCode}`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/pattern.js
  var require_pattern = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/pattern.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var code_1 = require_code2();
      var util_1 = require_util();
      var codegen_1 = require_codegen();
      var error = {
        message: ({ schemaCode }) => (0, codegen_1.str)`must match pattern "${schemaCode}"`,
        params: ({ schemaCode }) => (0, codegen_1._)`{pattern: ${schemaCode}}`
      };
      var def = {
        keyword: "pattern",
        type: "string",
        schemaType: "string",
        $data: true,
        error,
        code(cxt) {
          const { gen, data, $data, schema, schemaCode, it } = cxt;
          const u = it.opts.unicodeRegExp ? "u" : "";
          if ($data) {
            const { regExp } = it.opts.code;
            const regExpCode = regExp.code === "new RegExp" ? (0, codegen_1._)`new RegExp` : (0, util_1.useFunc)(gen, regExp);
            const valid = gen.let("valid");
            gen.try(() => gen.assign(valid, (0, codegen_1._)`${regExpCode}(${schemaCode}, ${u}).test(${data})`), () => gen.assign(valid, false));
            cxt.fail$data((0, codegen_1._)`!${valid}`);
          } else {
            const regExp = (0, code_1.usePattern)(cxt, schema);
            cxt.fail$data((0, codegen_1._)`!${regExp}.test(${data})`);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitProperties.js
  var require_limitProperties = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitProperties.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var error = {
        message({ keyword, schemaCode }) {
          const comp = keyword === "maxProperties" ? "more" : "fewer";
          return (0, codegen_1.str)`must NOT have ${comp} than ${schemaCode} properties`;
        },
        params: ({ schemaCode }) => (0, codegen_1._)`{limit: ${schemaCode}}`
      };
      var def = {
        keyword: ["maxProperties", "minProperties"],
        type: "object",
        schemaType: "number",
        $data: true,
        error,
        code(cxt) {
          const { keyword, data, schemaCode } = cxt;
          const op = keyword === "maxProperties" ? codegen_1.operators.GT : codegen_1.operators.LT;
          cxt.fail$data((0, codegen_1._)`Object.keys(${data}).length ${op} ${schemaCode}`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/required.js
  var require_required = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/required.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var code_1 = require_code2();
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: ({ params: { missingProperty } }) => (0, codegen_1.str)`must have required property '${missingProperty}'`,
        params: ({ params: { missingProperty } }) => (0, codegen_1._)`{missingProperty: ${missingProperty}}`
      };
      var def = {
        keyword: "required",
        type: "object",
        schemaType: "array",
        $data: true,
        error,
        code(cxt) {
          const { gen, schema, schemaCode, data, $data, it } = cxt;
          const { opts } = it;
          if (!$data && schema.length === 0)
            return;
          const useLoop = schema.length >= opts.loopRequired;
          if (it.allErrors)
            allErrorsMode();
          else
            exitOnErrorMode();
          if (opts.strictRequired) {
            const props = cxt.parentSchema.properties;
            const { definedProperties } = cxt.it;
            for (const requiredKey of schema) {
              if ((props === null || props === void 0 ? void 0 : props[requiredKey]) === void 0 && !definedProperties.has(requiredKey)) {
                const schemaPath = it.schemaEnv.baseId + it.errSchemaPath;
                const msg = `required property "${requiredKey}" is not defined at "${schemaPath}" (strictRequired)`;
                (0, util_1.checkStrictMode)(it, msg, it.opts.strictRequired);
              }
            }
          }
          function allErrorsMode() {
            if (useLoop || $data) {
              cxt.block$data(codegen_1.nil, loopAllRequired);
            } else {
              for (const prop of schema) {
                (0, code_1.checkReportMissingProp)(cxt, prop);
              }
            }
          }
          function exitOnErrorMode() {
            const missing = gen.let("missing");
            if (useLoop || $data) {
              const valid = gen.let("valid", true);
              cxt.block$data(valid, () => loopUntilMissing(missing, valid));
              cxt.ok(valid);
            } else {
              gen.if((0, code_1.checkMissingProp)(cxt, schema, missing));
              (0, code_1.reportMissingProp)(cxt, missing);
              gen.else();
            }
          }
          function loopAllRequired() {
            gen.forOf("prop", schemaCode, (prop) => {
              cxt.setParams({ missingProperty: prop });
              gen.if((0, code_1.noPropertyInData)(gen, data, prop, opts.ownProperties), () => cxt.error());
            });
          }
          function loopUntilMissing(missing, valid) {
            cxt.setParams({ missingProperty: missing });
            gen.forOf(missing, schemaCode, () => {
              gen.assign(valid, (0, code_1.propertyInData)(gen, data, missing, opts.ownProperties));
              gen.if((0, codegen_1.not)(valid), () => {
                cxt.error();
                gen.break();
              });
            }, codegen_1.nil);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitItems.js
  var require_limitItems = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitItems.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var error = {
        message({ keyword, schemaCode }) {
          const comp = keyword === "maxItems" ? "more" : "fewer";
          return (0, codegen_1.str)`must NOT have ${comp} than ${schemaCode} items`;
        },
        params: ({ schemaCode }) => (0, codegen_1._)`{limit: ${schemaCode}}`
      };
      var def = {
        keyword: ["maxItems", "minItems"],
        type: "array",
        schemaType: "number",
        $data: true,
        error,
        code(cxt) {
          const { keyword, data, schemaCode } = cxt;
          const op = keyword === "maxItems" ? codegen_1.operators.GT : codegen_1.operators.LT;
          cxt.fail$data((0, codegen_1._)`${data}.length ${op} ${schemaCode}`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/equal.js
  var require_equal = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/runtime/equal.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var equal = require_fast_deep_equal();
      equal.code = 'require("ajv/dist/runtime/equal").default';
      exports.default = equal;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/uniqueItems.js
  var require_uniqueItems = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/uniqueItems.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dataType_1 = require_dataType();
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var equal_1 = require_equal();
      var error = {
        message: ({ params: { i, j } }) => (0, codegen_1.str)`must NOT have duplicate items (items ## ${j} and ${i} are identical)`,
        params: ({ params: { i, j } }) => (0, codegen_1._)`{i: ${i}, j: ${j}}`
      };
      var def = {
        keyword: "uniqueItems",
        type: "array",
        schemaType: "boolean",
        $data: true,
        error,
        code(cxt) {
          const { gen, data, $data, schema, parentSchema, schemaCode, it } = cxt;
          if (!$data && !schema)
            return;
          const valid = gen.let("valid");
          const itemTypes = parentSchema.items ? (0, dataType_1.getSchemaTypes)(parentSchema.items) : [];
          cxt.block$data(valid, validateUniqueItems, (0, codegen_1._)`${schemaCode} === false`);
          cxt.ok(valid);
          function validateUniqueItems() {
            const i = gen.let("i", (0, codegen_1._)`${data}.length`);
            const j = gen.let("j");
            cxt.setParams({ i, j });
            gen.assign(valid, true);
            gen.if((0, codegen_1._)`${i} > 1`, () => (canOptimize() ? loopN : loopN2)(i, j));
          }
          function canOptimize() {
            return itemTypes.length > 0 && !itemTypes.some((t) => t === "object" || t === "array");
          }
          function loopN(i, j) {
            const item = gen.name("item");
            const wrongType = (0, dataType_1.checkDataTypes)(itemTypes, item, it.opts.strictNumbers, dataType_1.DataType.Wrong);
            const indices = gen.const("indices", (0, codegen_1._)`{}`);
            gen.for((0, codegen_1._)`;${i}--;`, () => {
              gen.let(item, (0, codegen_1._)`${data}[${i}]`);
              gen.if(wrongType, (0, codegen_1._)`continue`);
              if (itemTypes.length > 1)
                gen.if((0, codegen_1._)`typeof ${item} == "string"`, (0, codegen_1._)`${item} += "_"`);
              gen.if((0, codegen_1._)`typeof ${indices}[${item}] == "number"`, () => {
                gen.assign(j, (0, codegen_1._)`${indices}[${item}]`);
                cxt.error();
                gen.assign(valid, false).break();
              }).code((0, codegen_1._)`${indices}[${item}] = ${i}`);
            });
          }
          function loopN2(i, j) {
            const eql = (0, util_1.useFunc)(gen, equal_1.default);
            const outer = gen.name("outer");
            gen.label(outer).for((0, codegen_1._)`;${i}--;`, () => gen.for((0, codegen_1._)`${j} = ${i}; ${j}--;`, () => gen.if((0, codegen_1._)`${eql}(${data}[${i}], ${data}[${j}])`, () => {
              cxt.error();
              gen.assign(valid, false).break(outer);
            })));
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/const.js
  var require_const = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/const.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var equal_1 = require_equal();
      var error = {
        message: "must be equal to constant",
        params: ({ schemaCode }) => (0, codegen_1._)`{allowedValue: ${schemaCode}}`
      };
      var def = {
        keyword: "const",
        $data: true,
        error,
        code(cxt) {
          const { gen, data, $data, schemaCode, schema } = cxt;
          if ($data || schema && typeof schema == "object") {
            cxt.fail$data((0, codegen_1._)`!${(0, util_1.useFunc)(gen, equal_1.default)}(${data}, ${schemaCode})`);
          } else {
            cxt.fail((0, codegen_1._)`${schema} !== ${data}`);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/enum.js
  var require_enum = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/enum.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var equal_1 = require_equal();
      var error = {
        message: "must be equal to one of the allowed values",
        params: ({ schemaCode }) => (0, codegen_1._)`{allowedValues: ${schemaCode}}`
      };
      var def = {
        keyword: "enum",
        schemaType: "array",
        $data: true,
        error,
        code(cxt) {
          const { gen, data, $data, schema, schemaCode, it } = cxt;
          if (!$data && schema.length === 0)
            throw new Error("enum must have non-empty array");
          const useLoop = schema.length >= it.opts.loopEnum;
          let eql;
          const getEql = () => eql !== null && eql !== void 0 ? eql : eql = (0, util_1.useFunc)(gen, equal_1.default);
          let valid;
          if (useLoop || $data) {
            valid = gen.let("valid");
            cxt.block$data(valid, loopEnum);
          } else {
            if (!Array.isArray(schema))
              throw new Error("ajv implementation error");
            const vSchema = gen.const("vSchema", schemaCode);
            valid = (0, codegen_1.or)(...schema.map((_x, i) => equalCode(vSchema, i)));
          }
          cxt.pass(valid);
          function loopEnum() {
            gen.assign(valid, false);
            gen.forOf("v", schemaCode, (v) => gen.if((0, codegen_1._)`${getEql()}(${data}, ${v})`, () => gen.assign(valid, true).break()));
          }
          function equalCode(vSchema, i) {
            const sch = schema[i];
            return typeof sch === "object" && sch !== null ? (0, codegen_1._)`${getEql()}(${data}, ${vSchema}[${i}])` : (0, codegen_1._)`${data} === ${sch}`;
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/index.js
  var require_validation = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var limitNumber_1 = require_limitNumber();
      var multipleOf_1 = require_multipleOf();
      var limitLength_1 = require_limitLength();
      var pattern_1 = require_pattern();
      var limitProperties_1 = require_limitProperties();
      var required_1 = require_required();
      var limitItems_1 = require_limitItems();
      var uniqueItems_1 = require_uniqueItems();
      var const_1 = require_const();
      var enum_1 = require_enum();
      var validation = [
        // number
        limitNumber_1.default,
        multipleOf_1.default,
        // string
        limitLength_1.default,
        pattern_1.default,
        // object
        limitProperties_1.default,
        required_1.default,
        // array
        limitItems_1.default,
        uniqueItems_1.default,
        // any
        { keyword: "type", schemaType: ["string", "array"] },
        { keyword: "nullable", schemaType: "boolean" },
        const_1.default,
        enum_1.default
      ];
      exports.default = validation;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/additionalItems.js
  var require_additionalItems = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/additionalItems.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.validateAdditionalItems = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: ({ params: { len } }) => (0, codegen_1.str)`must NOT have more than ${len} items`,
        params: ({ params: { len } }) => (0, codegen_1._)`{limit: ${len}}`
      };
      var def = {
        keyword: "additionalItems",
        type: "array",
        schemaType: ["boolean", "object"],
        before: "uniqueItems",
        error,
        code(cxt) {
          const { parentSchema, it } = cxt;
          const { items } = parentSchema;
          if (!Array.isArray(items)) {
            (0, util_1.checkStrictMode)(it, '"additionalItems" is ignored when "items" is not an array of schemas');
            return;
          }
          validateAdditionalItems(cxt, items);
        }
      };
      function validateAdditionalItems(cxt, items) {
        const { gen, schema, data, keyword, it } = cxt;
        it.items = true;
        const len = gen.const("len", (0, codegen_1._)`${data}.length`);
        if (schema === false) {
          cxt.setParams({ len: items.length });
          cxt.pass((0, codegen_1._)`${len} <= ${items.length}`);
        } else if (typeof schema == "object" && !(0, util_1.alwaysValidSchema)(it, schema)) {
          const valid = gen.var("valid", (0, codegen_1._)`${len} <= ${items.length}`);
          gen.if((0, codegen_1.not)(valid), () => validateItems(valid));
          cxt.ok(valid);
        }
        function validateItems(valid) {
          gen.forRange("i", items.length, len, (i) => {
            cxt.subschema({ keyword, dataProp: i, dataPropType: util_1.Type.Num }, valid);
            if (!it.allErrors)
              gen.if((0, codegen_1.not)(valid), () => gen.break());
          });
        }
      }
      exports.validateAdditionalItems = validateAdditionalItems;
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/items.js
  var require_items = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/items.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.validateTuple = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var code_1 = require_code2();
      var def = {
        keyword: "items",
        type: "array",
        schemaType: ["object", "array", "boolean"],
        before: "uniqueItems",
        code(cxt) {
          const { schema, it } = cxt;
          if (Array.isArray(schema))
            return validateTuple(cxt, "additionalItems", schema);
          it.items = true;
          if ((0, util_1.alwaysValidSchema)(it, schema))
            return;
          cxt.ok((0, code_1.validateArray)(cxt));
        }
      };
      function validateTuple(cxt, extraItems, schArr = cxt.schema) {
        const { gen, parentSchema, data, keyword, it } = cxt;
        checkStrictTuple(parentSchema);
        if (it.opts.unevaluated && schArr.length && it.items !== true) {
          it.items = util_1.mergeEvaluated.items(gen, schArr.length, it.items);
        }
        const valid = gen.name("valid");
        const len = gen.const("len", (0, codegen_1._)`${data}.length`);
        schArr.forEach((sch, i) => {
          if ((0, util_1.alwaysValidSchema)(it, sch))
            return;
          gen.if((0, codegen_1._)`${len} > ${i}`, () => cxt.subschema({
            keyword,
            schemaProp: i,
            dataProp: i
          }, valid));
          cxt.ok(valid);
        });
        function checkStrictTuple(sch) {
          const { opts, errSchemaPath } = it;
          const l = schArr.length;
          const fullTuple = l === sch.minItems && (l === sch.maxItems || sch[extraItems] === false);
          if (opts.strictTuples && !fullTuple) {
            const msg = `"${keyword}" is ${l}-tuple, but minItems or maxItems/${extraItems} are not specified or different at path "${errSchemaPath}"`;
            (0, util_1.checkStrictMode)(it, msg, opts.strictTuples);
          }
        }
      }
      exports.validateTuple = validateTuple;
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/prefixItems.js
  var require_prefixItems = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/prefixItems.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var items_1 = require_items();
      var def = {
        keyword: "prefixItems",
        type: "array",
        schemaType: ["array"],
        before: "uniqueItems",
        code: (cxt) => (0, items_1.validateTuple)(cxt, "items")
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/items2020.js
  var require_items2020 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/items2020.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var code_1 = require_code2();
      var additionalItems_1 = require_additionalItems();
      var error = {
        message: ({ params: { len } }) => (0, codegen_1.str)`must NOT have more than ${len} items`,
        params: ({ params: { len } }) => (0, codegen_1._)`{limit: ${len}}`
      };
      var def = {
        keyword: "items",
        type: "array",
        schemaType: ["object", "boolean"],
        before: "uniqueItems",
        error,
        code(cxt) {
          const { schema, parentSchema, it } = cxt;
          const { prefixItems } = parentSchema;
          it.items = true;
          if ((0, util_1.alwaysValidSchema)(it, schema))
            return;
          if (prefixItems)
            (0, additionalItems_1.validateAdditionalItems)(cxt, prefixItems);
          else
            cxt.ok((0, code_1.validateArray)(cxt));
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/contains.js
  var require_contains = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/contains.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: ({ params: { min, max } }) => max === void 0 ? (0, codegen_1.str)`must contain at least ${min} valid item(s)` : (0, codegen_1.str)`must contain at least ${min} and no more than ${max} valid item(s)`,
        params: ({ params: { min, max } }) => max === void 0 ? (0, codegen_1._)`{minContains: ${min}}` : (0, codegen_1._)`{minContains: ${min}, maxContains: ${max}}`
      };
      var def = {
        keyword: "contains",
        type: "array",
        schemaType: ["object", "boolean"],
        before: "uniqueItems",
        trackErrors: true,
        error,
        code(cxt) {
          const { gen, schema, parentSchema, data, it } = cxt;
          let min;
          let max;
          const { minContains, maxContains } = parentSchema;
          if (it.opts.next) {
            min = minContains === void 0 ? 1 : minContains;
            max = maxContains;
          } else {
            min = 1;
          }
          const len = gen.const("len", (0, codegen_1._)`${data}.length`);
          cxt.setParams({ min, max });
          if (max === void 0 && min === 0) {
            (0, util_1.checkStrictMode)(it, `"minContains" == 0 without "maxContains": "contains" keyword ignored`);
            return;
          }
          if (max !== void 0 && min > max) {
            (0, util_1.checkStrictMode)(it, `"minContains" > "maxContains" is always invalid`);
            cxt.fail();
            return;
          }
          if ((0, util_1.alwaysValidSchema)(it, schema)) {
            let cond = (0, codegen_1._)`${len} >= ${min}`;
            if (max !== void 0)
              cond = (0, codegen_1._)`${cond} && ${len} <= ${max}`;
            cxt.pass(cond);
            return;
          }
          it.items = true;
          const valid = gen.name("valid");
          if (max === void 0 && min === 1) {
            validateItems(valid, () => gen.if(valid, () => gen.break()));
          } else if (min === 0) {
            gen.let(valid, true);
            if (max !== void 0)
              gen.if((0, codegen_1._)`${data}.length > 0`, validateItemsWithCount);
          } else {
            gen.let(valid, false);
            validateItemsWithCount();
          }
          cxt.result(valid, () => cxt.reset());
          function validateItemsWithCount() {
            const schValid = gen.name("_valid");
            const count = gen.let("count", 0);
            validateItems(schValid, () => gen.if(schValid, () => checkLimits(count)));
          }
          function validateItems(_valid, block) {
            gen.forRange("i", 0, len, (i) => {
              cxt.subschema({
                keyword: "contains",
                dataProp: i,
                dataPropType: util_1.Type.Num,
                compositeRule: true
              }, _valid);
              block();
            });
          }
          function checkLimits(count) {
            gen.code((0, codegen_1._)`${count}++`);
            if (max === void 0) {
              gen.if((0, codegen_1._)`${count} >= ${min}`, () => gen.assign(valid, true).break());
            } else {
              gen.if((0, codegen_1._)`${count} > ${max}`, () => gen.assign(valid, false).break());
              if (min === 1)
                gen.assign(valid, true);
              else
                gen.if((0, codegen_1._)`${count} >= ${min}`, () => gen.assign(valid, true));
            }
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/dependencies.js
  var require_dependencies = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/dependencies.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.validateSchemaDeps = exports.validatePropertyDeps = exports.error = void 0;
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var code_1 = require_code2();
      exports.error = {
        message: ({ params: { property, depsCount, deps } }) => {
          const property_ies = depsCount === 1 ? "property" : "properties";
          return (0, codegen_1.str)`must have ${property_ies} ${deps} when property ${property} is present`;
        },
        params: ({ params: { property, depsCount, deps, missingProperty } }) => (0, codegen_1._)`{property: ${property},
    missingProperty: ${missingProperty},
    depsCount: ${depsCount},
    deps: ${deps}}`
        // TODO change to reference
      };
      var def = {
        keyword: "dependencies",
        type: "object",
        schemaType: "object",
        error: exports.error,
        code(cxt) {
          const [propDeps, schDeps] = splitDependencies(cxt);
          validatePropertyDeps(cxt, propDeps);
          validateSchemaDeps(cxt, schDeps);
        }
      };
      function splitDependencies({ schema }) {
        const propertyDeps = {};
        const schemaDeps = {};
        for (const key in schema) {
          if (key === "__proto__")
            continue;
          const deps = Array.isArray(schema[key]) ? propertyDeps : schemaDeps;
          deps[key] = schema[key];
        }
        return [propertyDeps, schemaDeps];
      }
      function validatePropertyDeps(cxt, propertyDeps = cxt.schema) {
        const { gen, data, it } = cxt;
        if (Object.keys(propertyDeps).length === 0)
          return;
        const missing = gen.let("missing");
        for (const prop in propertyDeps) {
          const deps = propertyDeps[prop];
          if (deps.length === 0)
            continue;
          const hasProperty = (0, code_1.propertyInData)(gen, data, prop, it.opts.ownProperties);
          cxt.setParams({
            property: prop,
            depsCount: deps.length,
            deps: deps.join(", ")
          });
          if (it.allErrors) {
            gen.if(hasProperty, () => {
              for (const depProp of deps) {
                (0, code_1.checkReportMissingProp)(cxt, depProp);
              }
            });
          } else {
            gen.if((0, codegen_1._)`${hasProperty} && (${(0, code_1.checkMissingProp)(cxt, deps, missing)})`);
            (0, code_1.reportMissingProp)(cxt, missing);
            gen.else();
          }
        }
      }
      exports.validatePropertyDeps = validatePropertyDeps;
      function validateSchemaDeps(cxt, schemaDeps = cxt.schema) {
        const { gen, data, keyword, it } = cxt;
        const valid = gen.name("valid");
        for (const prop in schemaDeps) {
          if ((0, util_1.alwaysValidSchema)(it, schemaDeps[prop]))
            continue;
          gen.if(
            (0, code_1.propertyInData)(gen, data, prop, it.opts.ownProperties),
            () => {
              const schCxt = cxt.subschema({ keyword, schemaProp: prop }, valid);
              cxt.mergeValidEvaluated(schCxt, valid);
            },
            () => gen.var(valid, true)
            // TODO var
          );
          cxt.ok(valid);
        }
      }
      exports.validateSchemaDeps = validateSchemaDeps;
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/propertyNames.js
  var require_propertyNames = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/propertyNames.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: "property name must be valid",
        params: ({ params }) => (0, codegen_1._)`{propertyName: ${params.propertyName}}`
      };
      var def = {
        keyword: "propertyNames",
        type: "object",
        schemaType: ["object", "boolean"],
        error,
        code(cxt) {
          const { gen, schema, data, it } = cxt;
          if ((0, util_1.alwaysValidSchema)(it, schema))
            return;
          const valid = gen.name("valid");
          gen.forIn("key", data, (key) => {
            cxt.setParams({ propertyName: key });
            cxt.subschema({
              keyword: "propertyNames",
              data: key,
              dataTypes: ["string"],
              propertyName: key,
              compositeRule: true
            }, valid);
            gen.if((0, codegen_1.not)(valid), () => {
              cxt.error(true);
              if (!it.allErrors)
                gen.break();
            });
          });
          cxt.ok(valid);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/additionalProperties.js
  var require_additionalProperties = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/additionalProperties.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var code_1 = require_code2();
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var util_1 = require_util();
      var error = {
        message: "must NOT have additional properties",
        params: ({ params }) => (0, codegen_1._)`{additionalProperty: ${params.additionalProperty}}`
      };
      var def = {
        keyword: "additionalProperties",
        type: ["object"],
        schemaType: ["boolean", "object"],
        allowUndefined: true,
        trackErrors: true,
        error,
        code(cxt) {
          const { gen, schema, parentSchema, data, errsCount, it } = cxt;
          if (!errsCount)
            throw new Error("ajv implementation error");
          const { allErrors, opts } = it;
          it.props = true;
          if (opts.removeAdditional !== "all" && (0, util_1.alwaysValidSchema)(it, schema))
            return;
          const props = (0, code_1.allSchemaProperties)(parentSchema.properties);
          const patProps = (0, code_1.allSchemaProperties)(parentSchema.patternProperties);
          checkAdditionalProperties();
          cxt.ok((0, codegen_1._)`${errsCount} === ${names_1.default.errors}`);
          function checkAdditionalProperties() {
            gen.forIn("key", data, (key) => {
              if (!props.length && !patProps.length)
                additionalPropertyCode(key);
              else
                gen.if(isAdditional(key), () => additionalPropertyCode(key));
            });
          }
          function isAdditional(key) {
            let definedProp;
            if (props.length > 8) {
              const propsSchema = (0, util_1.schemaRefOrVal)(it, parentSchema.properties, "properties");
              definedProp = (0, code_1.isOwnProperty)(gen, propsSchema, key);
            } else if (props.length) {
              definedProp = (0, codegen_1.or)(...props.map((p) => (0, codegen_1._)`${key} === ${p}`));
            } else {
              definedProp = codegen_1.nil;
            }
            if (patProps.length) {
              definedProp = (0, codegen_1.or)(definedProp, ...patProps.map((p) => (0, codegen_1._)`${(0, code_1.usePattern)(cxt, p)}.test(${key})`));
            }
            return (0, codegen_1.not)(definedProp);
          }
          function deleteAdditional(key) {
            gen.code((0, codegen_1._)`delete ${data}[${key}]`);
          }
          function additionalPropertyCode(key) {
            if (opts.removeAdditional === "all" || opts.removeAdditional && schema === false) {
              deleteAdditional(key);
              return;
            }
            if (schema === false) {
              cxt.setParams({ additionalProperty: key });
              cxt.error();
              if (!allErrors)
                gen.break();
              return;
            }
            if (typeof schema == "object" && !(0, util_1.alwaysValidSchema)(it, schema)) {
              const valid = gen.name("valid");
              if (opts.removeAdditional === "failing") {
                applyAdditionalSchema(key, valid, false);
                gen.if((0, codegen_1.not)(valid), () => {
                  cxt.reset();
                  deleteAdditional(key);
                });
              } else {
                applyAdditionalSchema(key, valid);
                if (!allErrors)
                  gen.if((0, codegen_1.not)(valid), () => gen.break());
              }
            }
          }
          function applyAdditionalSchema(key, valid, errors) {
            const subschema = {
              keyword: "additionalProperties",
              dataProp: key,
              dataPropType: util_1.Type.Str
            };
            if (errors === false) {
              Object.assign(subschema, {
                compositeRule: true,
                createErrors: false,
                allErrors: false
              });
            }
            cxt.subschema(subschema, valid);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/properties.js
  var require_properties = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/properties.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var validate_1 = require_validate();
      var code_1 = require_code2();
      var util_1 = require_util();
      var additionalProperties_1 = require_additionalProperties();
      var def = {
        keyword: "properties",
        type: "object",
        schemaType: "object",
        code(cxt) {
          const { gen, schema, parentSchema, data, it } = cxt;
          if (it.opts.removeAdditional === "all" && parentSchema.additionalProperties === void 0) {
            additionalProperties_1.default.code(new validate_1.KeywordCxt(it, additionalProperties_1.default, "additionalProperties"));
          }
          const allProps = (0, code_1.allSchemaProperties)(schema);
          for (const prop of allProps) {
            it.definedProperties.add(prop);
          }
          if (it.opts.unevaluated && allProps.length && it.props !== true) {
            it.props = util_1.mergeEvaluated.props(gen, (0, util_1.toHash)(allProps), it.props);
          }
          const properties = allProps.filter((p) => !(0, util_1.alwaysValidSchema)(it, schema[p]));
          if (properties.length === 0)
            return;
          const valid = gen.name("valid");
          for (const prop of properties) {
            if (hasDefault(prop)) {
              applyPropertySchema(prop);
            } else {
              gen.if((0, code_1.propertyInData)(gen, data, prop, it.opts.ownProperties));
              applyPropertySchema(prop);
              if (!it.allErrors)
                gen.else().var(valid, true);
              gen.endIf();
            }
            cxt.it.definedProperties.add(prop);
            cxt.ok(valid);
          }
          function hasDefault(prop) {
            return it.opts.useDefaults && !it.compositeRule && schema[prop].default !== void 0;
          }
          function applyPropertySchema(prop) {
            cxt.subschema({
              keyword: "properties",
              schemaProp: prop,
              dataProp: prop
            }, valid);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/patternProperties.js
  var require_patternProperties = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/patternProperties.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var code_1 = require_code2();
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var util_2 = require_util();
      var def = {
        keyword: "patternProperties",
        type: "object",
        schemaType: "object",
        code(cxt) {
          const { gen, schema, data, parentSchema, it } = cxt;
          const { opts } = it;
          const patterns = (0, code_1.allSchemaProperties)(schema);
          const alwaysValidPatterns = patterns.filter((p) => (0, util_1.alwaysValidSchema)(it, schema[p]));
          if (patterns.length === 0 || alwaysValidPatterns.length === patterns.length && (!it.opts.unevaluated || it.props === true)) {
            return;
          }
          const checkProperties = opts.strictSchema && !opts.allowMatchingProperties && parentSchema.properties;
          const valid = gen.name("valid");
          if (it.props !== true && !(it.props instanceof codegen_1.Name)) {
            it.props = (0, util_2.evaluatedPropsToName)(gen, it.props);
          }
          const { props } = it;
          validatePatternProperties();
          function validatePatternProperties() {
            for (const pat of patterns) {
              if (checkProperties)
                checkMatchingProperties(pat);
              if (it.allErrors) {
                validateProperties(pat);
              } else {
                gen.var(valid, true);
                validateProperties(pat);
                gen.if(valid);
              }
            }
          }
          function checkMatchingProperties(pat) {
            for (const prop in checkProperties) {
              if (new RegExp(pat).test(prop)) {
                (0, util_1.checkStrictMode)(it, `property ${prop} matches pattern ${pat} (use allowMatchingProperties)`);
              }
            }
          }
          function validateProperties(pat) {
            gen.forIn("key", data, (key) => {
              gen.if((0, codegen_1._)`${(0, code_1.usePattern)(cxt, pat)}.test(${key})`, () => {
                const alwaysValid = alwaysValidPatterns.includes(pat);
                if (!alwaysValid) {
                  cxt.subschema({
                    keyword: "patternProperties",
                    schemaProp: pat,
                    dataProp: key,
                    dataPropType: util_2.Type.Str
                  }, valid);
                }
                if (it.opts.unevaluated && props !== true) {
                  gen.assign((0, codegen_1._)`${props}[${key}]`, true);
                } else if (!alwaysValid && !it.allErrors) {
                  gen.if((0, codegen_1.not)(valid), () => gen.break());
                }
              });
            });
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/not.js
  var require_not = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/not.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var util_1 = require_util();
      var def = {
        keyword: "not",
        schemaType: ["object", "boolean"],
        trackErrors: true,
        code(cxt) {
          const { gen, schema, it } = cxt;
          if ((0, util_1.alwaysValidSchema)(it, schema)) {
            cxt.fail();
            return;
          }
          const valid = gen.name("valid");
          cxt.subschema({
            keyword: "not",
            compositeRule: true,
            createErrors: false,
            allErrors: false
          }, valid);
          cxt.failResult(valid, () => cxt.reset(), () => cxt.error());
        },
        error: { message: "must NOT be valid" }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/anyOf.js
  var require_anyOf = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/anyOf.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var code_1 = require_code2();
      var def = {
        keyword: "anyOf",
        schemaType: "array",
        trackErrors: true,
        code: code_1.validateUnion,
        error: { message: "must match a schema in anyOf" }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/oneOf.js
  var require_oneOf = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/oneOf.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: "must match exactly one schema in oneOf",
        params: ({ params }) => (0, codegen_1._)`{passingSchemas: ${params.passing}}`
      };
      var def = {
        keyword: "oneOf",
        schemaType: "array",
        trackErrors: true,
        error,
        code(cxt) {
          const { gen, schema, parentSchema, it } = cxt;
          if (!Array.isArray(schema))
            throw new Error("ajv implementation error");
          if (it.opts.discriminator && parentSchema.discriminator)
            return;
          const schArr = schema;
          const valid = gen.let("valid", false);
          const passing = gen.let("passing", null);
          const schValid = gen.name("_valid");
          cxt.setParams({ passing });
          gen.block(validateOneOf);
          cxt.result(valid, () => cxt.reset(), () => cxt.error(true));
          function validateOneOf() {
            schArr.forEach((sch, i) => {
              let schCxt;
              if ((0, util_1.alwaysValidSchema)(it, sch)) {
                gen.var(schValid, true);
              } else {
                schCxt = cxt.subschema({
                  keyword: "oneOf",
                  schemaProp: i,
                  compositeRule: true
                }, schValid);
              }
              if (i > 0) {
                gen.if((0, codegen_1._)`${schValid} && ${valid}`).assign(valid, false).assign(passing, (0, codegen_1._)`[${passing}, ${i}]`).else();
              }
              gen.if(schValid, () => {
                gen.assign(valid, true);
                gen.assign(passing, i);
                if (schCxt)
                  cxt.mergeEvaluated(schCxt, codegen_1.Name);
              });
            });
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/allOf.js
  var require_allOf = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/allOf.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var util_1 = require_util();
      var def = {
        keyword: "allOf",
        schemaType: "array",
        code(cxt) {
          const { gen, schema, it } = cxt;
          if (!Array.isArray(schema))
            throw new Error("ajv implementation error");
          const valid = gen.name("valid");
          schema.forEach((sch, i) => {
            if ((0, util_1.alwaysValidSchema)(it, sch))
              return;
            const schCxt = cxt.subschema({ keyword: "allOf", schemaProp: i }, valid);
            cxt.ok(valid);
            cxt.mergeEvaluated(schCxt);
          });
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/if.js
  var require_if = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/if.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: ({ params }) => (0, codegen_1.str)`must match "${params.ifClause}" schema`,
        params: ({ params }) => (0, codegen_1._)`{failingKeyword: ${params.ifClause}}`
      };
      var def = {
        keyword: "if",
        schemaType: ["object", "boolean"],
        trackErrors: true,
        error,
        code(cxt) {
          const { gen, parentSchema, it } = cxt;
          if (parentSchema.then === void 0 && parentSchema.else === void 0) {
            (0, util_1.checkStrictMode)(it, '"if" without "then" and "else" is ignored');
          }
          const hasThen = hasSchema(it, "then");
          const hasElse = hasSchema(it, "else");
          if (!hasThen && !hasElse)
            return;
          const valid = gen.let("valid", true);
          const schValid = gen.name("_valid");
          validateIf();
          cxt.reset();
          if (hasThen && hasElse) {
            const ifClause = gen.let("ifClause");
            cxt.setParams({ ifClause });
            gen.if(schValid, validateClause("then", ifClause), validateClause("else", ifClause));
          } else if (hasThen) {
            gen.if(schValid, validateClause("then"));
          } else {
            gen.if((0, codegen_1.not)(schValid), validateClause("else"));
          }
          cxt.pass(valid, () => cxt.error(true));
          function validateIf() {
            const schCxt = cxt.subschema({
              keyword: "if",
              compositeRule: true,
              createErrors: false,
              allErrors: false
            }, schValid);
            cxt.mergeEvaluated(schCxt);
          }
          function validateClause(keyword, ifClause) {
            return () => {
              const schCxt = cxt.subschema({ keyword }, schValid);
              gen.assign(valid, schValid);
              cxt.mergeValidEvaluated(schCxt, valid);
              if (ifClause)
                gen.assign(ifClause, (0, codegen_1._)`${keyword}`);
              else
                cxt.setParams({ ifClause: keyword });
            };
          }
        }
      };
      function hasSchema(it, keyword) {
        const schema = it.schema[keyword];
        return schema !== void 0 && !(0, util_1.alwaysValidSchema)(it, schema);
      }
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/thenElse.js
  var require_thenElse = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/thenElse.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var util_1 = require_util();
      var def = {
        keyword: ["then", "else"],
        schemaType: ["object", "boolean"],
        code({ keyword, parentSchema, it }) {
          if (parentSchema.if === void 0)
            (0, util_1.checkStrictMode)(it, `"${keyword}" without "if" is ignored`);
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/index.js
  var require_applicator = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var additionalItems_1 = require_additionalItems();
      var prefixItems_1 = require_prefixItems();
      var items_1 = require_items();
      var items2020_1 = require_items2020();
      var contains_1 = require_contains();
      var dependencies_1 = require_dependencies();
      var propertyNames_1 = require_propertyNames();
      var additionalProperties_1 = require_additionalProperties();
      var properties_1 = require_properties();
      var patternProperties_1 = require_patternProperties();
      var not_1 = require_not();
      var anyOf_1 = require_anyOf();
      var oneOf_1 = require_oneOf();
      var allOf_1 = require_allOf();
      var if_1 = require_if();
      var thenElse_1 = require_thenElse();
      function getApplicator(draft2020 = false) {
        const applicator = [
          // any
          not_1.default,
          anyOf_1.default,
          oneOf_1.default,
          allOf_1.default,
          if_1.default,
          thenElse_1.default,
          // object
          propertyNames_1.default,
          additionalProperties_1.default,
          dependencies_1.default,
          properties_1.default,
          patternProperties_1.default
        ];
        if (draft2020)
          applicator.push(prefixItems_1.default, items2020_1.default);
        else
          applicator.push(additionalItems_1.default, items_1.default);
        applicator.push(contains_1.default);
        return applicator;
      }
      exports.default = getApplicator;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/dynamicAnchor.js
  var require_dynamicAnchor = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/dynamicAnchor.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.dynamicAnchor = void 0;
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var compile_1 = require_compile();
      var ref_1 = require_ref();
      var def = {
        keyword: "$dynamicAnchor",
        schemaType: "string",
        code: (cxt) => dynamicAnchor(cxt, cxt.schema)
      };
      function dynamicAnchor(cxt, anchor) {
        const { gen, it } = cxt;
        it.schemaEnv.root.dynamicAnchors[anchor] = true;
        const v = (0, codegen_1._)`${names_1.default.dynamicAnchors}${(0, codegen_1.getProperty)(anchor)}`;
        const validate = it.errSchemaPath === "#" ? it.validateName : _getValidate(cxt);
        gen.if((0, codegen_1._)`!${v}`, () => gen.assign(v, validate));
      }
      exports.dynamicAnchor = dynamicAnchor;
      function _getValidate(cxt) {
        const { schemaEnv, schema, self } = cxt.it;
        const { root, baseId, localRefs, meta } = schemaEnv.root;
        const { schemaId } = self.opts;
        const sch = new compile_1.SchemaEnv({ schema, schemaId, root, baseId, localRefs, meta });
        compile_1.compileSchema.call(self, sch);
        return (0, ref_1.getValidate)(cxt, sch);
      }
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/dynamicRef.js
  var require_dynamicRef = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/dynamicRef.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.dynamicRef = void 0;
      var codegen_1 = require_codegen();
      var names_1 = require_names();
      var ref_1 = require_ref();
      var def = {
        keyword: "$dynamicRef",
        schemaType: "string",
        code: (cxt) => dynamicRef(cxt, cxt.schema)
      };
      function dynamicRef(cxt, ref) {
        const { gen, keyword, it } = cxt;
        if (ref[0] !== "#")
          throw new Error(`"${keyword}" only supports hash fragment reference`);
        const anchor = ref.slice(1);
        if (it.allErrors) {
          _dynamicRef();
        } else {
          const valid = gen.let("valid", false);
          _dynamicRef(valid);
          cxt.ok(valid);
        }
        function _dynamicRef(valid) {
          if (it.schemaEnv.root.dynamicAnchors[anchor]) {
            const v = gen.let("_v", (0, codegen_1._)`${names_1.default.dynamicAnchors}${(0, codegen_1.getProperty)(anchor)}`);
            gen.if(v, _callRef(v, valid), _callRef(it.validateName, valid));
          } else {
            _callRef(it.validateName, valid)();
          }
        }
        function _callRef(validate, valid) {
          return valid ? () => gen.block(() => {
            (0, ref_1.callRef)(cxt, validate);
            gen.let(valid, true);
          }) : () => (0, ref_1.callRef)(cxt, validate);
        }
      }
      exports.dynamicRef = dynamicRef;
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/recursiveAnchor.js
  var require_recursiveAnchor = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/recursiveAnchor.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dynamicAnchor_1 = require_dynamicAnchor();
      var util_1 = require_util();
      var def = {
        keyword: "$recursiveAnchor",
        schemaType: "boolean",
        code(cxt) {
          if (cxt.schema)
            (0, dynamicAnchor_1.dynamicAnchor)(cxt, "");
          else
            (0, util_1.checkStrictMode)(cxt.it, "$recursiveAnchor: false is ignored");
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/recursiveRef.js
  var require_recursiveRef = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/recursiveRef.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dynamicRef_1 = require_dynamicRef();
      var def = {
        keyword: "$recursiveRef",
        schemaType: "string",
        code: (cxt) => (0, dynamicRef_1.dynamicRef)(cxt, cxt.schema)
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/index.js
  var require_dynamic = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/dynamic/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dynamicAnchor_1 = require_dynamicAnchor();
      var dynamicRef_1 = require_dynamicRef();
      var recursiveAnchor_1 = require_recursiveAnchor();
      var recursiveRef_1 = require_recursiveRef();
      var dynamic = [dynamicAnchor_1.default, dynamicRef_1.default, recursiveAnchor_1.default, recursiveRef_1.default];
      exports.default = dynamic;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/dependentRequired.js
  var require_dependentRequired = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/dependentRequired.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dependencies_1 = require_dependencies();
      var def = {
        keyword: "dependentRequired",
        type: "object",
        schemaType: "object",
        error: dependencies_1.error,
        code: (cxt) => (0, dependencies_1.validatePropertyDeps)(cxt)
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/dependentSchemas.js
  var require_dependentSchemas = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/applicator/dependentSchemas.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dependencies_1 = require_dependencies();
      var def = {
        keyword: "dependentSchemas",
        type: "object",
        schemaType: "object",
        code: (cxt) => (0, dependencies_1.validateSchemaDeps)(cxt)
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitContains.js
  var require_limitContains = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/validation/limitContains.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var util_1 = require_util();
      var def = {
        keyword: ["maxContains", "minContains"],
        type: "array",
        schemaType: "number",
        code({ keyword, parentSchema, it }) {
          if (parentSchema.contains === void 0) {
            (0, util_1.checkStrictMode)(it, `"${keyword}" without "contains" is ignored`);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/next.js
  var require_next = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/next.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var dependentRequired_1 = require_dependentRequired();
      var dependentSchemas_1 = require_dependentSchemas();
      var limitContains_1 = require_limitContains();
      var next = [dependentRequired_1.default, dependentSchemas_1.default, limitContains_1.default];
      exports.default = next;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/unevaluatedProperties.js
  var require_unevaluatedProperties = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/unevaluatedProperties.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var names_1 = require_names();
      var error = {
        message: "must NOT have unevaluated properties",
        params: ({ params }) => (0, codegen_1._)`{unevaluatedProperty: ${params.unevaluatedProperty}}`
      };
      var def = {
        keyword: "unevaluatedProperties",
        type: "object",
        schemaType: ["boolean", "object"],
        trackErrors: true,
        error,
        code(cxt) {
          const { gen, schema, data, errsCount, it } = cxt;
          if (!errsCount)
            throw new Error("ajv implementation error");
          const { allErrors, props } = it;
          if (props instanceof codegen_1.Name) {
            gen.if((0, codegen_1._)`${props} !== true`, () => gen.forIn("key", data, (key) => gen.if(unevaluatedDynamic(props, key), () => unevaluatedPropCode(key))));
          } else if (props !== true) {
            gen.forIn("key", data, (key) => props === void 0 ? unevaluatedPropCode(key) : gen.if(unevaluatedStatic(props, key), () => unevaluatedPropCode(key)));
          }
          it.props = true;
          cxt.ok((0, codegen_1._)`${errsCount} === ${names_1.default.errors}`);
          function unevaluatedPropCode(key) {
            if (schema === false) {
              cxt.setParams({ unevaluatedProperty: key });
              cxt.error();
              if (!allErrors)
                gen.break();
              return;
            }
            if (!(0, util_1.alwaysValidSchema)(it, schema)) {
              const valid = gen.name("valid");
              cxt.subschema({
                keyword: "unevaluatedProperties",
                dataProp: key,
                dataPropType: util_1.Type.Str
              }, valid);
              if (!allErrors)
                gen.if((0, codegen_1.not)(valid), () => gen.break());
            }
          }
          function unevaluatedDynamic(evaluatedProps, key) {
            return (0, codegen_1._)`!${evaluatedProps} || !${evaluatedProps}[${key}]`;
          }
          function unevaluatedStatic(evaluatedProps, key) {
            const ps = [];
            for (const p in evaluatedProps) {
              if (evaluatedProps[p] === true)
                ps.push((0, codegen_1._)`${key} !== ${p}`);
            }
            return (0, codegen_1.and)(...ps);
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/unevaluatedItems.js
  var require_unevaluatedItems = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/unevaluatedItems.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var util_1 = require_util();
      var error = {
        message: ({ params: { len } }) => (0, codegen_1.str)`must NOT have more than ${len} items`,
        params: ({ params: { len } }) => (0, codegen_1._)`{limit: ${len}}`
      };
      var def = {
        keyword: "unevaluatedItems",
        type: "array",
        schemaType: ["boolean", "object"],
        error,
        code(cxt) {
          const { gen, schema, data, it } = cxt;
          const items = it.items || 0;
          if (items === true)
            return;
          const len = gen.const("len", (0, codegen_1._)`${data}.length`);
          if (schema === false) {
            cxt.setParams({ len: items });
            cxt.fail((0, codegen_1._)`${len} > ${items}`);
          } else if (typeof schema == "object" && !(0, util_1.alwaysValidSchema)(it, schema)) {
            const valid = gen.var("valid", (0, codegen_1._)`${len} <= ${items}`);
            gen.if((0, codegen_1.not)(valid), () => validateItems(valid, items));
            cxt.ok(valid);
          }
          it.items = true;
          function validateItems(valid, from) {
            gen.forRange("i", from, len, (i) => {
              cxt.subschema({ keyword: "unevaluatedItems", dataProp: i, dataPropType: util_1.Type.Num }, valid);
              if (!it.allErrors)
                gen.if((0, codegen_1.not)(valid), () => gen.break());
            });
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/index.js
  var require_unevaluated = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/unevaluated/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var unevaluatedProperties_1 = require_unevaluatedProperties();
      var unevaluatedItems_1 = require_unevaluatedItems();
      var unevaluated = [unevaluatedProperties_1.default, unevaluatedItems_1.default];
      exports.default = unevaluated;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/format/format.js
  var require_format = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/format/format.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var error = {
        message: ({ schemaCode }) => (0, codegen_1.str)`must match format "${schemaCode}"`,
        params: ({ schemaCode }) => (0, codegen_1._)`{format: ${schemaCode}}`
      };
      var def = {
        keyword: "format",
        type: ["number", "string"],
        schemaType: "string",
        $data: true,
        error,
        code(cxt, ruleType) {
          const { gen, data, $data, schema, schemaCode, it } = cxt;
          const { opts, errSchemaPath, schemaEnv, self } = it;
          if (!opts.validateFormats)
            return;
          if ($data)
            validate$DataFormat();
          else
            validateFormat();
          function validate$DataFormat() {
            const fmts = gen.scopeValue("formats", {
              ref: self.formats,
              code: opts.code.formats
            });
            const fDef = gen.const("fDef", (0, codegen_1._)`${fmts}[${schemaCode}]`);
            const fType = gen.let("fType");
            const format = gen.let("format");
            gen.if((0, codegen_1._)`typeof ${fDef} == "object" && !(${fDef} instanceof RegExp)`, () => gen.assign(fType, (0, codegen_1._)`${fDef}.type || "string"`).assign(format, (0, codegen_1._)`${fDef}.validate`), () => gen.assign(fType, (0, codegen_1._)`"string"`).assign(format, fDef));
            cxt.fail$data((0, codegen_1.or)(unknownFmt(), invalidFmt()));
            function unknownFmt() {
              if (opts.strictSchema === false)
                return codegen_1.nil;
              return (0, codegen_1._)`${schemaCode} && !${format}`;
            }
            function invalidFmt() {
              const callFormat = schemaEnv.$async ? (0, codegen_1._)`(${fDef}.async ? await ${format}(${data}) : ${format}(${data}))` : (0, codegen_1._)`${format}(${data})`;
              const validData = (0, codegen_1._)`(typeof ${format} == "function" ? ${callFormat} : ${format}.test(${data}))`;
              return (0, codegen_1._)`${format} && ${format} !== true && ${fType} === ${ruleType} && !${validData}`;
            }
          }
          function validateFormat() {
            const formatDef = self.formats[schema];
            if (!formatDef) {
              unknownFormat();
              return;
            }
            if (formatDef === true)
              return;
            const [fmtType, format, fmtRef] = getFormat(formatDef);
            if (fmtType === ruleType)
              cxt.pass(validCondition());
            function unknownFormat() {
              if (opts.strictSchema === false) {
                self.logger.warn(unknownMsg());
                return;
              }
              throw new Error(unknownMsg());
              function unknownMsg() {
                return `unknown format "${schema}" ignored in schema at path "${errSchemaPath}"`;
              }
            }
            function getFormat(fmtDef) {
              const code = fmtDef instanceof RegExp ? (0, codegen_1.regexpCode)(fmtDef) : opts.code.formats ? (0, codegen_1._)`${opts.code.formats}${(0, codegen_1.getProperty)(schema)}` : void 0;
              const fmt = gen.scopeValue("formats", { key: schema, ref: fmtDef, code });
              if (typeof fmtDef == "object" && !(fmtDef instanceof RegExp)) {
                return [fmtDef.type || "string", fmtDef.validate, (0, codegen_1._)`${fmt}.validate`];
              }
              return ["string", fmtDef, fmt];
            }
            function validCondition() {
              if (typeof formatDef == "object" && !(formatDef instanceof RegExp) && formatDef.async) {
                if (!schemaEnv.$async)
                  throw new Error("async format in sync schema");
                return (0, codegen_1._)`await ${fmtRef}(${data})`;
              }
              return typeof format == "function" ? (0, codegen_1._)`${fmtRef}(${data})` : (0, codegen_1._)`${fmtRef}.test(${data})`;
            }
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/format/index.js
  var require_format2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/format/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var format_1 = require_format();
      var format = [format_1.default];
      exports.default = format;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/metadata.js
  var require_metadata = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/metadata.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.contentVocabulary = exports.metadataVocabulary = void 0;
      exports.metadataVocabulary = [
        "title",
        "description",
        "default",
        "deprecated",
        "readOnly",
        "writeOnly",
        "examples"
      ];
      exports.contentVocabulary = [
        "contentMediaType",
        "contentEncoding",
        "contentSchema"
      ];
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/draft2020.js
  var require_draft2020 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/draft2020.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var core_1 = require_core2();
      var validation_1 = require_validation();
      var applicator_1 = require_applicator();
      var dynamic_1 = require_dynamic();
      var next_1 = require_next();
      var unevaluated_1 = require_unevaluated();
      var format_1 = require_format2();
      var metadata_1 = require_metadata();
      var draft2020Vocabularies = [
        dynamic_1.default,
        core_1.default,
        validation_1.default,
        (0, applicator_1.default)(true),
        format_1.default,
        metadata_1.metadataVocabulary,
        metadata_1.contentVocabulary,
        next_1.default,
        unevaluated_1.default
      ];
      exports.default = draft2020Vocabularies;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/discriminator/types.js
  var require_types = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/discriminator/types.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.DiscrError = void 0;
      var DiscrError;
      (function(DiscrError2) {
        DiscrError2["Tag"] = "tag";
        DiscrError2["Mapping"] = "mapping";
      })(DiscrError || (exports.DiscrError = DiscrError = {}));
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/discriminator/index.js
  var require_discriminator = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/vocabularies/discriminator/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var codegen_1 = require_codegen();
      var types_1 = require_types();
      var compile_1 = require_compile();
      var ref_error_1 = require_ref_error();
      var util_1 = require_util();
      var error = {
        message: ({ params: { discrError, tagName } }) => discrError === types_1.DiscrError.Tag ? `tag "${tagName}" must be string` : `value of tag "${tagName}" must be in oneOf`,
        params: ({ params: { discrError, tag, tagName } }) => (0, codegen_1._)`{error: ${discrError}, tag: ${tagName}, tagValue: ${tag}}`
      };
      var def = {
        keyword: "discriminator",
        type: "object",
        schemaType: "object",
        error,
        code(cxt) {
          const { gen, data, schema, parentSchema, it } = cxt;
          const { oneOf } = parentSchema;
          if (!it.opts.discriminator) {
            throw new Error("discriminator: requires discriminator option");
          }
          const tagName = schema.propertyName;
          if (typeof tagName != "string")
            throw new Error("discriminator: requires propertyName");
          if (schema.mapping)
            throw new Error("discriminator: mapping is not supported");
          if (!oneOf)
            throw new Error("discriminator: requires oneOf keyword");
          const valid = gen.let("valid", false);
          const tag = gen.const("tag", (0, codegen_1._)`${data}${(0, codegen_1.getProperty)(tagName)}`);
          gen.if((0, codegen_1._)`typeof ${tag} == "string"`, () => validateMapping(), () => cxt.error(false, { discrError: types_1.DiscrError.Tag, tag, tagName }));
          cxt.ok(valid);
          function validateMapping() {
            const mapping = getMapping();
            gen.if(false);
            for (const tagValue in mapping) {
              gen.elseIf((0, codegen_1._)`${tag} === ${tagValue}`);
              gen.assign(valid, applyTagSchema(mapping[tagValue]));
            }
            gen.else();
            cxt.error(false, { discrError: types_1.DiscrError.Mapping, tag, tagName });
            gen.endIf();
          }
          function applyTagSchema(schemaProp) {
            const _valid = gen.name("valid");
            const schCxt = cxt.subschema({ keyword: "oneOf", schemaProp }, _valid);
            cxt.mergeEvaluated(schCxt, codegen_1.Name);
            return _valid;
          }
          function getMapping() {
            var _a;
            const oneOfMapping = {};
            const topRequired = hasRequired(parentSchema);
            let tagRequired = true;
            for (let i = 0; i < oneOf.length; i++) {
              let sch = oneOf[i];
              if ((sch === null || sch === void 0 ? void 0 : sch.$ref) && !(0, util_1.schemaHasRulesButRef)(sch, it.self.RULES)) {
                const ref = sch.$ref;
                sch = compile_1.resolveRef.call(it.self, it.schemaEnv.root, it.baseId, ref);
                if (sch instanceof compile_1.SchemaEnv)
                  sch = sch.schema;
                if (sch === void 0)
                  throw new ref_error_1.default(it.opts.uriResolver, it.baseId, ref);
              }
              const propSch = (_a = sch === null || sch === void 0 ? void 0 : sch.properties) === null || _a === void 0 ? void 0 : _a[tagName];
              if (typeof propSch != "object") {
                throw new Error(`discriminator: oneOf subschemas (or referenced schemas) must have "properties/${tagName}"`);
              }
              tagRequired = tagRequired && (topRequired || hasRequired(sch));
              addMappings(propSch, i);
            }
            if (!tagRequired)
              throw new Error(`discriminator: "${tagName}" must be required`);
            return oneOfMapping;
            function hasRequired({ required }) {
              return Array.isArray(required) && required.includes(tagName);
            }
            function addMappings(sch, i) {
              if (sch.const) {
                addMapping(sch.const, i);
              } else if (sch.enum) {
                for (const tagValue of sch.enum) {
                  addMapping(tagValue, i);
                }
              } else {
                throw new Error(`discriminator: "properties/${tagName}" must have "const" or "enum"`);
              }
            }
            function addMapping(tagValue, i) {
              if (typeof tagValue != "string" || tagValue in oneOfMapping) {
                throw new Error(`discriminator: "${tagName}" values must be unique strings`);
              }
              oneOfMapping[tagValue] = i;
            }
          }
        }
      };
      exports.default = def;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/schema.json
  var require_schema = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/schema.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/schema",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/core": true,
          "https://json-schema.org/draft/2020-12/vocab/applicator": true,
          "https://json-schema.org/draft/2020-12/vocab/unevaluated": true,
          "https://json-schema.org/draft/2020-12/vocab/validation": true,
          "https://json-schema.org/draft/2020-12/vocab/meta-data": true,
          "https://json-schema.org/draft/2020-12/vocab/format-annotation": true,
          "https://json-schema.org/draft/2020-12/vocab/content": true
        },
        $dynamicAnchor: "meta",
        title: "Core and Validation specifications meta-schema",
        allOf: [
          { $ref: "meta/core" },
          { $ref: "meta/applicator" },
          { $ref: "meta/unevaluated" },
          { $ref: "meta/validation" },
          { $ref: "meta/meta-data" },
          { $ref: "meta/format-annotation" },
          { $ref: "meta/content" }
        ],
        type: ["object", "boolean"],
        $comment: "This meta-schema also defines keywords that have appeared in previous drafts in order to prevent incompatible extensions as they remain in common use.",
        properties: {
          definitions: {
            $comment: '"definitions" has been replaced by "$defs".',
            type: "object",
            additionalProperties: { $dynamicRef: "#meta" },
            deprecated: true,
            default: {}
          },
          dependencies: {
            $comment: '"dependencies" has been split and replaced by "dependentSchemas" and "dependentRequired" in order to serve their differing semantics.',
            type: "object",
            additionalProperties: {
              anyOf: [{ $dynamicRef: "#meta" }, { $ref: "meta/validation#/$defs/stringArray" }]
            },
            deprecated: true,
            default: {}
          },
          $recursiveAnchor: {
            $comment: '"$recursiveAnchor" has been replaced by "$dynamicAnchor".',
            $ref: "meta/core#/$defs/anchorString",
            deprecated: true
          },
          $recursiveRef: {
            $comment: '"$recursiveRef" has been replaced by "$dynamicRef".',
            $ref: "meta/core#/$defs/uriReferenceString",
            deprecated: true
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/applicator.json
  var require_applicator2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/applicator.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/applicator",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/applicator": true
        },
        $dynamicAnchor: "meta",
        title: "Applicator vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          prefixItems: { $ref: "#/$defs/schemaArray" },
          items: { $dynamicRef: "#meta" },
          contains: { $dynamicRef: "#meta" },
          additionalProperties: { $dynamicRef: "#meta" },
          properties: {
            type: "object",
            additionalProperties: { $dynamicRef: "#meta" },
            default: {}
          },
          patternProperties: {
            type: "object",
            additionalProperties: { $dynamicRef: "#meta" },
            propertyNames: { format: "regex" },
            default: {}
          },
          dependentSchemas: {
            type: "object",
            additionalProperties: { $dynamicRef: "#meta" },
            default: {}
          },
          propertyNames: { $dynamicRef: "#meta" },
          if: { $dynamicRef: "#meta" },
          then: { $dynamicRef: "#meta" },
          else: { $dynamicRef: "#meta" },
          allOf: { $ref: "#/$defs/schemaArray" },
          anyOf: { $ref: "#/$defs/schemaArray" },
          oneOf: { $ref: "#/$defs/schemaArray" },
          not: { $dynamicRef: "#meta" }
        },
        $defs: {
          schemaArray: {
            type: "array",
            minItems: 1,
            items: { $dynamicRef: "#meta" }
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/unevaluated.json
  var require_unevaluated2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/unevaluated.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/unevaluated",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/unevaluated": true
        },
        $dynamicAnchor: "meta",
        title: "Unevaluated applicator vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          unevaluatedItems: { $dynamicRef: "#meta" },
          unevaluatedProperties: { $dynamicRef: "#meta" }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/content.json
  var require_content = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/content.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/content",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/content": true
        },
        $dynamicAnchor: "meta",
        title: "Content vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          contentEncoding: { type: "string" },
          contentMediaType: { type: "string" },
          contentSchema: { $dynamicRef: "#meta" }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/core.json
  var require_core3 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/core.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/core",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/core": true
        },
        $dynamicAnchor: "meta",
        title: "Core vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          $id: {
            $ref: "#/$defs/uriReferenceString",
            $comment: "Non-empty fragments not allowed.",
            pattern: "^[^#]*#?$"
          },
          $schema: { $ref: "#/$defs/uriString" },
          $ref: { $ref: "#/$defs/uriReferenceString" },
          $anchor: { $ref: "#/$defs/anchorString" },
          $dynamicRef: { $ref: "#/$defs/uriReferenceString" },
          $dynamicAnchor: { $ref: "#/$defs/anchorString" },
          $vocabulary: {
            type: "object",
            propertyNames: { $ref: "#/$defs/uriString" },
            additionalProperties: {
              type: "boolean"
            }
          },
          $comment: {
            type: "string"
          },
          $defs: {
            type: "object",
            additionalProperties: { $dynamicRef: "#meta" }
          }
        },
        $defs: {
          anchorString: {
            type: "string",
            pattern: "^[A-Za-z_][-A-Za-z0-9._]*$"
          },
          uriString: {
            type: "string",
            format: "uri"
          },
          uriReferenceString: {
            type: "string",
            format: "uri-reference"
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/format-annotation.json
  var require_format_annotation = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/format-annotation.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/format-annotation",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/format-annotation": true
        },
        $dynamicAnchor: "meta",
        title: "Format vocabulary meta-schema for annotation results",
        type: ["object", "boolean"],
        properties: {
          format: { type: "string" }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/meta-data.json
  var require_meta_data = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/meta-data.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/meta-data",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/meta-data": true
        },
        $dynamicAnchor: "meta",
        title: "Meta-data vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          title: {
            type: "string"
          },
          description: {
            type: "string"
          },
          default: true,
          deprecated: {
            type: "boolean",
            default: false
          },
          readOnly: {
            type: "boolean",
            default: false
          },
          writeOnly: {
            type: "boolean",
            default: false
          },
          examples: {
            type: "array",
            items: true
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/validation.json
  var require_validation2 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/meta/validation.json"(exports, module) {
      module.exports = {
        $schema: "https://json-schema.org/draft/2020-12/schema",
        $id: "https://json-schema.org/draft/2020-12/meta/validation",
        $vocabulary: {
          "https://json-schema.org/draft/2020-12/vocab/validation": true
        },
        $dynamicAnchor: "meta",
        title: "Validation vocabulary meta-schema",
        type: ["object", "boolean"],
        properties: {
          type: {
            anyOf: [
              { $ref: "#/$defs/simpleTypes" },
              {
                type: "array",
                items: { $ref: "#/$defs/simpleTypes" },
                minItems: 1,
                uniqueItems: true
              }
            ]
          },
          const: true,
          enum: {
            type: "array",
            items: true
          },
          multipleOf: {
            type: "number",
            exclusiveMinimum: 0
          },
          maximum: {
            type: "number"
          },
          exclusiveMaximum: {
            type: "number"
          },
          minimum: {
            type: "number"
          },
          exclusiveMinimum: {
            type: "number"
          },
          maxLength: { $ref: "#/$defs/nonNegativeInteger" },
          minLength: { $ref: "#/$defs/nonNegativeIntegerDefault0" },
          pattern: {
            type: "string",
            format: "regex"
          },
          maxItems: { $ref: "#/$defs/nonNegativeInteger" },
          minItems: { $ref: "#/$defs/nonNegativeIntegerDefault0" },
          uniqueItems: {
            type: "boolean",
            default: false
          },
          maxContains: { $ref: "#/$defs/nonNegativeInteger" },
          minContains: {
            $ref: "#/$defs/nonNegativeInteger",
            default: 1
          },
          maxProperties: { $ref: "#/$defs/nonNegativeInteger" },
          minProperties: { $ref: "#/$defs/nonNegativeIntegerDefault0" },
          required: { $ref: "#/$defs/stringArray" },
          dependentRequired: {
            type: "object",
            additionalProperties: {
              $ref: "#/$defs/stringArray"
            }
          }
        },
        $defs: {
          nonNegativeInteger: {
            type: "integer",
            minimum: 0
          },
          nonNegativeIntegerDefault0: {
            $ref: "#/$defs/nonNegativeInteger",
            default: 0
          },
          simpleTypes: {
            enum: ["array", "boolean", "integer", "null", "number", "object", "string"]
          },
          stringArray: {
            type: "array",
            items: { type: "string" },
            uniqueItems: true,
            default: []
          }
        }
      };
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/index.js
  var require_json_schema_2020_12 = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/refs/json-schema-2020-12/index.js"(exports) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      var metaSchema = require_schema();
      var applicator = require_applicator2();
      var unevaluated = require_unevaluated2();
      var content = require_content();
      var core = require_core3();
      var format = require_format_annotation();
      var metadata = require_meta_data();
      var validation = require_validation2();
      var META_SUPPORT_DATA = ["/properties"];
      function addMetaSchema2020($data) {
        ;
        [
          metaSchema,
          applicator,
          unevaluated,
          content,
          core,
          with$data(this, format),
          metadata,
          with$data(this, validation)
        ].forEach((sch) => this.addMetaSchema(sch, void 0, false));
        return this;
        function with$data(ajv, sch) {
          return $data ? ajv.$dataMetaSchema(sch, META_SUPPORT_DATA) : sch;
        }
      }
      exports.default = addMetaSchema2020;
    }
  });

  // .goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/2020.js
  var require__ = __commonJS({
    ".goose/out/rc022-prep-20261114-01/source/node_modules/.pnpm/ajv@8.20.0/node_modules/ajv/dist/2020.js"(exports, module) {
      "use strict";
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.MissingRefError = exports.ValidationError = exports.CodeGen = exports.Name = exports.nil = exports.stringify = exports.str = exports._ = exports.KeywordCxt = exports.Ajv2020 = void 0;
      var core_1 = require_core();
      var draft2020_1 = require_draft2020();
      var discriminator_1 = require_discriminator();
      var json_schema_2020_12_1 = require_json_schema_2020_12();
      var META_SCHEMA_ID = "https://json-schema.org/draft/2020-12/schema";
      var Ajv2020 = class extends core_1.default {
        constructor(opts = {}) {
          super({
            ...opts,
            dynamicRef: true,
            next: true,
            unevaluated: true
          });
        }
        _addVocabularies() {
          super._addVocabularies();
          draft2020_1.default.forEach((v) => this.addVocabulary(v));
          if (this.opts.discriminator)
            this.addKeyword(discriminator_1.default);
        }
        _addDefaultMetaSchema() {
          super._addDefaultMetaSchema();
          const { $data, meta } = this.opts;
          if (!meta)
            return;
          json_schema_2020_12_1.default.call(this, $data);
          this.refs["http://json-schema.org/schema"] = META_SCHEMA_ID;
        }
        defaultMeta() {
          return this.opts.defaultMeta = super.defaultMeta() || (this.getSchema(META_SCHEMA_ID) ? META_SCHEMA_ID : void 0);
        }
      };
      exports.Ajv2020 = Ajv2020;
      module.exports = exports = Ajv2020;
      module.exports.Ajv2020 = Ajv2020;
      Object.defineProperty(exports, "__esModule", { value: true });
      exports.default = Ajv2020;
      var validate_1 = require_validate();
      Object.defineProperty(exports, "KeywordCxt", { enumerable: true, get: function() {
        return validate_1.KeywordCxt;
      } });
      var codegen_1 = require_codegen();
      Object.defineProperty(exports, "_", { enumerable: true, get: function() {
        return codegen_1._;
      } });
      Object.defineProperty(exports, "str", { enumerable: true, get: function() {
        return codegen_1.str;
      } });
      Object.defineProperty(exports, "stringify", { enumerable: true, get: function() {
        return codegen_1.stringify;
      } });
      Object.defineProperty(exports, "nil", { enumerable: true, get: function() {
        return codegen_1.nil;
      } });
      Object.defineProperty(exports, "Name", { enumerable: true, get: function() {
        return codegen_1.Name;
      } });
      Object.defineProperty(exports, "CodeGen", { enumerable: true, get: function() {
        return codegen_1.CodeGen;
      } });
      var validation_error_1 = require_validation_error();
      Object.defineProperty(exports, "ValidationError", { enumerable: true, get: function() {
        return validation_error_1.default;
      } });
      var ref_error_1 = require_ref_error();
      Object.defineProperty(exports, "MissingRefError", { enumerable: true, get: function() {
        return ref_error_1.default;
      } });
    }
  });

  // scripts/native/config-projection/entry.ts
  var entry_exports = {};
  __export(entry_exports, {
    LOADER_EXPRESSION_SCHEMA: () => LOADER_EXPRESSION_SCHEMA,
    createConfigProjector: () => createConfigProjector,
    decodeGraph: () => decodeGraph
  });

  // .goose/out/rc022-prep-20261114-01/source/packages/boot/app-boot/src/config-schema/native.ts
  function isNativeConfigSchema(value) {
    if (value === null || typeof value !== "object" && typeof value !== "function") return false;
    const meta = Reflect.get(value, "meta");
    return Reflect.get(value, /* @__PURE__ */ Symbol.for("schemastery")) === true && typeof Reflect.get(value, "type") === "string" && meta !== null && typeof meta === "object";
  }

  // .goose/out/rc022-prep-20261114-01/source/packages/boot/app-boot/src/config-schema/pattern.ts
  function bmpOnly(node) {
    switch (node.type) {
      case "Character":
        return node.value <= 65535 && (node.value < 55296 || node.value > 57343);
      case "CharacterClassRange":
        return bmpOnly(node.min) && bmpOnly(node.max) && (node.max.value < 55296 || node.min.value > 57343);
      case "CharacterClass":
        return !node.negate && node.elements.every(bmpOnly);
      case "CharacterSet":
        return (node.kind === "digit" || node.kind === "space" || node.kind === "word") && !node.negate;
      case "Quantifier":
        return bmpOnly(node.element);
      case "Assertion":
        return ["start", "end", "word"].includes(node.kind);
      default:
        return false;
    }
  }
  function broadSet(node) {
    return node.type === "CharacterSet" && (node.kind === "any" || (node.kind === "digit" || node.kind === "space" || node.kind === "word") && node.negate);
  }
  function portableAlternative(alternative) {
    if (alternative.elements.length === 1 && alternative.elements.some(broadSet)) return true;
    let broadRepetitions = 0;
    const wordAssertion = alternative.elements.some((element) => element.type === "Assertion" && element.kind === "word");
    return alternative.elements.every((element) => {
      if (element.type === "Quantifier" && element.max === Infinity && element.min <= 1 && broadSet(element.element)) {
        return !wordAssertion && ++broadRepetitions === 1;
      }
      return bmpOnly(element);
    });
  }
  function signature(pattern) {
    const incidental = /* @__PURE__ */ new Set(["parent", "start", "end", "raw", "references", "resolved"]);
    return JSON.stringify(pattern, (key, value) => incidental.has(key) ? void 0 : value);
  }
  async function createPatternCheck() {
    const { RegExpParser: RegExpParser2 } = await Promise.resolve().then(() => (init_regexpp(), regexpp_exports));
    const parser = new RegExpParser2();
    return (source, flags = "") => {
      if (flags !== "" && flags !== "u") return false;
      try {
        const unicode = parser.parsePattern(source, 0, source.length, { unicode: true });
        if (flags === "u") return true;
        const native = parser.parsePattern(source, 0, source.length, { unicode: false });
        return signature(native) === signature(unicode) && native.alternatives.every(portableAlternative);
      } catch (error) {
        if (error instanceof SyntaxError) return false;
        throw error;
      }
    };
  }

  // .goose/out/rc022-prep-20261114-01/source/packages/boot/app-boot/src/config-schema/projector.ts
  var LOADER_EXPRESSION_SCHEMA = {
    type: "object",
    properties: { __jsExpr: { type: "string" } },
    required: ["__jsExpr"],
    description: "Inert representation of a YAML !!js scalar from the Cordis entry-list parser. Its result is evaluated and validated only at runtime. Extra marker-object fields are ignored by interpolation."
  };
  function jsonValue(value, nullifyUndefined = false) {
    const visit = (item, active) => {
      if (nullifyUndefined && item === void 0) return;
      if (item === null || typeof item === "string" || typeof item === "boolean") return;
      if (typeof item === "number" && Number.isFinite(item)) return;
      if (typeof item !== "object") throw new Error("schema annotation is not JSON-compatible");
      if (active.has(item)) throw new Error("schema annotation contains a cycle");
      if (!Array.isArray(item) && Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) {
        throw new Error("schema annotation contains a non-JSON object");
      }
      active.add(item);
      for (const child of Object.values(item)) visit(child, active);
      active.delete(item);
    };
    visit(value, /* @__PURE__ */ new Set());
    const result = JSON.parse(JSON.stringify(
      value,
      (_key, item) => nullifyUndefined && item === void 0 ? null : item
    ));
    return result;
  }
  function constant(value, objectComparison) {
    if (Array.isArray(value)) {
      return {
        type: "array",
        minItems: value.length,
        maxItems: value.length,
        items: false,
        ...value.length ? { prefixItems: Array.from(value, (item) => constant(item, objectComparison)) } : {}
      };
    }
    if (value !== null && typeof value === "object") {
      objectComparison();
      const properties = Object.fromEntries(Object.entries(value).map(([key, child]) => [key, constant(child, objectComparison)]));
      const inherited = Object.getOwnPropertyNames(Object.prototype);
      const required = Object.keys(properties).filter((key) => !inherited.includes(key) && Reflect.get(value, key) != null);
      const pattern = inherited.map((key) => key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
      return {
        type: "object",
        properties,
        additionalProperties: { type: "null" },
        patternProperties: { [`^(?:${pattern})$`]: {} },
        ...required.length ? { required } : {}
      };
    }
    return { const: value };
  }
  function nullable(core, accepts) {
    if (typeof core === "boolean") return accepts ? core || { type: "null" } : core && { not: { type: "null" } };
    const types = typeof core.type === "string" ? [core.type] : core.type;
    if (types === void 0) return accepts ? { anyOf: [core, { type: "null" }] } : { ...core, not: { type: "null" } };
    const [single, ...rest] = accepts ? [.../* @__PURE__ */ new Set([...types, "null"])] : types.filter((type) => type !== "null");
    if (single === void 0) return false;
    return { ...core, type: rest.length ? [single, ...rest] : single };
  }
  function expressions(schema, valuePosition = true, enabled = true) {
    const result = { ...schema };
    if (schema.properties) {
      result.properties = Object.fromEntries(Object.entries(schema.properties).map(([key, child]) => [key, expressions(child, true, enabled)]));
    }
    for (const key of ["items", "additionalProperties"]) {
      if (schema[key] !== void 0) result[key] = schema[key] === false ? false : expressions(schema[key], true, enabled);
    }
    if (schema.propertyNames) result.propertyNames = expressions(schema.propertyNames, false, false);
    if (schema.prefixItems) result.prefixItems = schema.prefixItems.map((child) => expressions(child, true, enabled));
    if (schema.anyOf) result.anyOf = schema.anyOf.map((child) => expressions(child, false, enabled));
    if (schema.not !== void 0) result.not = expressions(schema.not, false, false);
    if (!valuePosition || !enabled) return result;
    const annotations = {};
    for (const key of ["title", "description", "default", "$comment", "x-cordis"]) {
      if (Object.hasOwn(result, key)) {
        annotations[key] = result[key];
        Reflect.deleteProperty(result, key);
      }
    }
    return { ...annotations, anyOf: [result, { $ref: "#/$defs/loaderExpression" }] };
  }
  function validateVolatilePlacement(node, path, blocked = false, seen = /* @__PURE__ */ new Map()) {
    const states = seen.get(node) ?? /* @__PURE__ */ new Set();
    if (states.has(blocked)) return;
    states.add(blocked);
    seen.set(node, states);
    if (node.meta.volatile && blocked) throw new Error(`${path}: volatile fields require a fixed object path without an enclosing volatile field`);
    const nested = blocked || !!node.meta.volatile;
    for (const [key, child] of Object.entries(node.dict ?? {})) validateVolatilePlacement(child, `${path}/${key}`, nested, seen);
    if (node.sKey) validateVolatilePlacement(node.sKey, `${path}/keys`, true, seen);
    if (node.inner && (node.type !== "lazy" || isNativeConfigSchema(node.inner))) {
      validateVolatilePlacement(node.inner, `${path}/inner`, true, seen);
    }
    for (const [index, child] of (node.list ?? []).entries()) validateVolatilePlacement(child, `${path}/${index}`, true, seen);
  }
  async function createConfigProjector() {
    const { Ajv2020 } = await Promise.resolve().then(() => __toESM(require__(), 1));
    const validator = new Ajv2020({ strict: false, logger: false, validateFormats: false, addUsedSchema: false });
    const portablePattern = await createPatternCheck();
    const builderResults = /* @__PURE__ */ new Map();
    return (root, prefix) => {
      validateVolatilePlacement(root, "config");
      const completed = /* @__PURE__ */ new Map();
      const strictNodes = /* @__PURE__ */ new Map();
      const active = /* @__PURE__ */ new Set();
      const recursiveNames = /* @__PURE__ */ new Map();
      const definitions = {};
      const limitations = [];
      const metadataEffects = [];
      const limitation = (path, message) => {
        const text = `${path}: ${message}`;
        limitations.push(text);
        return text;
      };
      const visit = (node, path, strict = false) => {
        let key = node;
        if (strict) {
          key = strictNodes.get(node) ?? { ...node };
          strictNodes.set(node, key);
        }
        const cached = completed.get(key);
        if (cached) return cached;
        if (active.has(key)) {
          let name2 = recursiveNames.get(key);
          if (name2 === void 0) {
            name2 = `${prefix}Recursive${recursiveNames.size}`;
            recursiveNames.set(key, name2);
          }
          return {
            schema: { $ref: `#/$defs/${name2}` },
            acceptsMissing: node.type !== "lazy" && node.meta.required ? false : "unknown",
            exact: true,
            recursive: true,
            effectful: true,
            mutating: true
          };
        }
        active.add(key);
        let projection;
        if (node.type === "lazy") {
          let inner = node;
          let meta = node.meta.volatile ? { ...node.meta, volatile: false } : node.meta;
          const chain = /* @__PURE__ */ new Set();
          let looseProjection;
          while (inner.type === "lazy") {
            const cachedInner = isNativeConfigSchema(inner.inner);
            if (meta.loose) {
              const message = limitation(path, "lazy loose fallback can accept inputs rejected by its inner schema");
              if (!cachedInner) metadataEffects.push(limitation(path, "unresolved loose lazy metadata propagation may affect shared schemas"));
              looseProjection = {
                schema: { "x-cordis": { loose: true, limitations: [message] } },
                acceptsMissing: true,
                exact: false,
                recursive: false,
                effectful: true,
                mutating: false
              };
              break;
            }
            if (chain.has(inner)) throw new Error(`${path}: lazy cycle has no concrete schema`);
            chain.add(inner);
            let next = cachedInner ? inner.inner : builderResults.get(inner);
            if (next === void 0 && typeof inner.builder === "function") {
              next = Reflect.apply(inner.builder, inner, []);
              builderResults.set(inner, next);
            }
            if (!isNativeConfigSchema(next)) throw new Error(`${path}: lazy schema has no native builder result or resolved inner schema`);
            if (!cachedInner && ["required", "default", "min", "max", "step", "pattern", "loose", "volatile"].some((key2) => Object.hasOwn(meta, key2) && !Object.hasOwn(next.meta, key2) && (["required", "loose", "volatile"].includes(key2) ? !!Reflect.get(meta, key2) : Reflect.get(meta, key2) != null))) {
              metadataEffects.push(limitation(path, "lazy metadata propagation may affect shared schemas; validation requires native execution"));
            }
            meta = cachedInner ? next.meta : { ...meta, ...next.meta };
            validateVolatilePlacement({ ...next, meta }, `${path}/lazy`, true);
            inner = next;
          }
          projection = looseProjection ?? visit({ ...inner, meta }, `${path}/lazy`, strict);
          if (node.meta.volatile) {
            projection = { ...projection, schema: { ...projection.schema, "x-cordis": { ...projection.schema["x-cordis"], volatile: true } } };
          }
        } else {
          const ownLimitations = [];
          const inputLimitations = [];
          let unsupported = false;
          const inputLimitation = (message) => {
            inputLimitations.push(message);
            ownLimitations.push(limitation(path, message));
          };
          const annotation = (value, name2) => {
            try {
              return { ok: true, value: jsonValue(value) };
            } catch (error) {
              ownLimitations.push(limitation(`${path}/${name2}`, `annotation omitted: ${error instanceof Error ? error.message : String(error)}`));
              return { ok: false };
            }
          };
          const children = [];
          const child = (value, suffix, childStrict = false) => {
            if (value === void 0) throw new Error(`${path}: ${node.type} schema is missing ${suffix}`);
            const result2 = visit(value, `${path}/${suffix}`, childStrict);
            children.push(result2);
            return result2;
          };
          const meta = { ...node.meta };
          for (const key2 of ["min", "max", "step"]) {
            if (meta[key2] === void 0 || Number.isFinite(meta[key2])) continue;
            const inert = key2 === "max" ? meta.max === Infinity : key2 === "min" && meta.min === -Infinity && !meta.step;
            if (!inert) inputLimitation(`non-finite ${key2} constraint is omitted; native validation is required`);
            Reflect.deleteProperty(meta, key2);
          }
          let core;
          let dictionaryValidation;
          switch (node.type) {
            case "any":
              core = true;
              break;
            case "never":
              core = false;
              break;
            case "const": {
              try {
                core = node.value == null ? false : constant(jsonValue(node.value, true), () => {
                  inputLimitation("object constant inherited-member comparison requires native validation");
                });
              } catch (error) {
                core = true;
                inputLimitation(`constant constraint requires native validation: ${error instanceof Error ? error.message : String(error)}`);
              }
              break;
            }
            case "boolean":
              core = { type: "boolean" };
              break;
            case "string": {
              core = { type: "string" };
              if (meta.min !== void 0) {
                if (meta.min <= 1) core.minLength = Math.max(0, Math.ceil(meta.min));
                else inputLimitation("UTF-16 minimum length requires native validation");
              }
              if (meta.max !== void 0) {
                if (meta.max < 0) core = false;
                else {
                  const maximum = Math.floor(meta.max);
                  core.maxLength = maximum;
                  if (maximum > 0) inputLimitation("UTF-16 maximum length requires native validation");
                }
              }
              if (meta.pattern && core !== false) {
                if (portablePattern(meta.pattern.source, meta.pattern.flags)) core.pattern = meta.pattern.source;
                else inputLimitation("regular-expression syntax or Unicode semantics require native validation");
              }
              break;
            }
            case "number": {
              core = { type: "number" };
              if (meta.min !== void 0) core.minimum = meta.min;
              if (meta.max !== void 0) core.maximum = meta.max;
              if (meta.step) {
                const step = Math.abs(meta.step);
                const origin = meta.min ?? 0;
                if (!Number.isInteger(step) || origin % step !== 0) {
                  inputLimitation("fractional or offset numeric step requires native validation");
                } else if (step === 1) core.type = "integer";
                else core.multipleOf = step;
              }
              break;
            }
            case "object": {
              const required = [];
              const properties = Object.fromEntries(Object.entries(node.dict ?? {}).map(([key2, field]) => {
                const value = child(field, key2);
                if (value.acceptsMissing === false) required.push(key2);
                return [key2, value.schema];
              }));
              core = { type: "object", properties };
              if (required.length) core.required = required;
              break;
            }
            case "array": {
              const item = child(node.inner, "items");
              core = { type: "array", items: item.schema };
              if (meta.min !== void 0 && node.inner?.meta.default == null) core.minItems = Math.max(0, Math.ceil(meta.min));
              if (meta.max !== void 0) {
                if (meta.max < 0) core = false;
                else core.maxItems = Math.floor(meta.max);
              }
              break;
            }
            case "dict": {
              const valueSchema = child(node.inner, "values").schema;
              core = { type: "object", additionalProperties: valueSchema };
              if (node.sKey) {
                const key2 = child(node.sKey, "keys");
                const totalString = node.sKey.type === "string" && node.sKey.meta.min === void 0 && node.sKey.meta.max === void 0 && node.sKey.meta.pattern === void 0;
                if (!totalString && (strict || key2.effectful)) {
                  dictionaryValidation = { keySchema: key2.schema, valueSchema };
                  core = { type: "object" };
                  inputLimitation(key2.effectful ? "dictionary key normalization can overwrite unvalidated values; native validation is required" : "strict dictionary filtering and value validation require native validation");
                } else core.propertyNames = key2.schema;
              }
              break;
            }
            case "tuple": {
              if (node.list === void 0) throw new Error(`${path}: tuple schema is missing its list`);
              const values = node.list.map((item, index) => child(item, String(index)));
              core = { type: "array", ...values.length ? { prefixItems: values.map((item) => item.schema) } : {} };
              const minimum = values.reduce((length, value, index) => value.acceptsMissing === false ? index + 1 : length, 0);
              if (minimum) core.minItems = minimum;
              break;
            }
            case "union": {
              if (node.list === void 0) throw new Error(`${path}: union schema is missing its list`);
              const variants = node.list.map((item, index) => child(item, String(index), strict));
              if (variants.slice(0, -1).some((variant) => variant.mutating)) {
                core = true;
                inputLimitation("earlier union branches may alter later validation inputs; native validation is required");
              } else core = variants.length ? { anyOf: variants.map((variant) => variant.schema) } : false;
              break;
            }
            case "transform":
              core = child(node.inner, "input", true).schema;
              inputLimitation("transform callback validation and normalization are not executed or projected");
              break;
            default:
              core = true;
              unsupported = true;
              inputLimitation(`native schema type ${node.type} is not statically projected`);
          }
          if (meta.loose) {
            core = true;
            inputLimitation("loose validation can replace invalid values with defaults");
          }
          const recursive = children.some((value) => value.recursive);
          const container = ["object", "array", "dict", "tuple"].includes(node.type);
          const mutating = unsupported || children.some((value) => value.mutating || container && value.effectful);
          const exact = inputLimitations.length === 0 && children.every((value) => value.exact);
          const fallback = meta.default === void 0 ? void 0 : annotation(meta.default, "default");
          let acceptsMissing;
          if (meta.required) acceptsMissing = false;
          else if (unsupported) acceptsMissing = "unknown";
          else if (meta.default == null) acceptsMissing = true;
          else if (!fallback?.ok) acceptsMissing = "unknown";
          else if (recursive) {
            acceptsMissing = "unknown";
            inputLimitation("recursive default validation cannot be decided statically");
          } else if (!exact) acceptsMissing = "unknown";
          else acceptsMissing = validator.validate(core, fallback.value);
          const annotations = {};
          if (fallback?.ok) annotations.default = fallback.value;
          const native = {};
          if (typeof meta.description === "string") annotations.description = meta.description;
          else if (meta.description) {
            const descriptions = annotation(meta.description, "description");
            if (descriptions.ok) {
              native.descriptions = descriptions.value;
              const description = meta.description.en ?? meta.description[""] ?? Object.values(meta.description)[0];
              if (typeof description === "string") annotations.description = description;
            }
          }
          if (dictionaryValidation) native.dictionaryValidation = dictionaryValidation;
          const copy = (name2, value) => {
            if (value === void 0) return;
            const result2 = annotation(value, name2);
            if (result2.ok) native[name2] = result2.value;
          };
          for (const key2 of ["role", "extra", "hidden", "disabled", "collapse", "link", "comment", "badges", "loose", "volatile"]) {
            copy(key2, meta[key2]);
          }
          if (meta.pattern?.flags) copy("patternFlags", meta.pattern.flags);
          if (node.type === "union") native.branchSelection = "first-success";
          if (acceptsMissing === "unknown") native.omissionValidation = "runtime";
          if (ownLimitations.length) {
            native.type = node.type;
            for (const key2 of ["min", "max", "step", "pattern"]) copy(key2, meta[key2]);
            native.limitations = ownLimitations;
          }
          if (Object.keys(native).length) annotations["x-cordis"] = native;
          const input = nullable(core, acceptsMissing !== false);
          projection = {
            schema: { ...typeof input === "boolean" ? input ? {} : { not: {} } : input, ...annotations },
            acceptsMissing,
            exact: exact && acceptsMissing !== "unknown",
            recursive,
            effectful: unsupported || node.type === "transform" || !!meta.loose || children.some((child2) => child2.effectful),
            mutating
          };
        }
        active.delete(key);
        const name = recursiveNames.get(key);
        if (name !== void 0) {
          definitions[name] = projection.schema;
          projection = { ...projection, schema: { $ref: `#/$defs/${name}` } };
        }
        completed.set(key, projection);
        return projection;
      };
      const result = visit(root, "config");
      const schema = expressions(result.schema);
      return {
        schema: metadataEffects.length ? { anyOf: [schema, {}] } : schema,
        definitions: Object.fromEntries(Object.entries(definitions).map(([key, value]) => [key, expressions(value, false)])),
        acceptsMissing: metadataEffects.length ? "unknown" : result.acceptsMissing,
        limitations: [...new Set(limitations)]
      };
    };
  }

  // scripts/native/config-projection/entry.ts
  function decodeGraph(wire) {
    const values = wire.heap.map((record) => {
      switch (record.kind) {
        case "array":
          return [];
        case "object":
          return {};
        case "schema":
          return { [/* @__PURE__ */ Symbol.for("schemastery")]: true };
        case "date":
          return new Date(record.value);
        case "regexp":
          return new RegExp(record.source, record.flags);
        case "function":
          return () => {
            throw new Error("opaque callback must not execute");
          };
        default:
          throw new Error("invalid graph record kind");
      }
    });
    const decode = (item) => {
      if (item === null || typeof item !== "object") return item;
      if (Object.hasOwn(item, "ref")) {
        if (!Number.isInteger(item.ref) || item.ref < 0 || item.ref >= values.length) throw new Error("invalid graph reference");
        return values[item.ref];
      }
      switch (item.atom) {
        case "undefined":
          return void 0;
        case "nan":
          return NaN;
        case "infinity":
          return Infinity;
        case "-infinity":
          return -Infinity;
        case "bigint":
          return BigInt(item.value);
        case "symbol":
          return Symbol(item.value);
        default:
          throw new Error("invalid graph atom");
      }
    };
    wire.heap.forEach((record, index) => {
      const value = values[index];
      if (record.kind === "array") for (const item of record.items) value.push(decode(item));
      if (record.kind === "object" || record.kind === "schema") {
        for (const [key, item] of record.entries) {
          Object.defineProperty(value, key, { value: decode(item), writable: true, enumerable: true, configurable: true });
        }
      }
      if (record.kind === "schema" && record.builder !== void 0) {
        value.builder = () => {
          wire.builderCalls.push(index);
          if (Object.hasOwn(record.builder, "error")) throw new Error(record.builder.error);
          return decode(record.builder);
        };
      }
    });
    return wire.roots.map(decode);
  }
  return __toCommonJS(entry_exports);
})();
