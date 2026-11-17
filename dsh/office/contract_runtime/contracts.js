const CODES = /* @__PURE__ */ new Set([
	"input-too-large",
	"output-too-large",
	"invalid-document",
	"unsupported-format",
	"invalid-output",
	"timeout",
	"unavailable",
	"failed"
]);
/** An actionable converter failure; operating-system errors and caller abort reasons remain unchanged. */
var ConversionError = class extends Error {
	/** Published failure category carried across worker and helper transports. */
	code;
	/**
	* @param code - Published failure category.
	* @param message - Consumer-facing failure description.
	* @param options - Standard error options; a cause is preserved for diagnostics.
	*/
	constructor(code, message, options) {
		super(message, options);
		this.name = "ConversionError";
		this.code = code;
	}
};
/**
* Only published categories cross worker/helper messages; unknown errors use the generic failure category.
* @param error - The thrown value, which may be any type and may carry an unpublished `code`.
* @returns The published category, or `failed` when no published category is present.
*/
function failureCode(error) {
	const code = error?.code;
	return typeof code === "string" && CODES.has(code) ? code : "failed";
}
/**
* Describe any thrown value, including caller callbacks that throw non-Error values.
* @param error - The thrown value.
* @returns The Error message, or the value's string form.
*/
function failureMessage(error) {
	return error instanceof Error ? error.message : String(error);
}

const MAX_COLUMN = 16383;
const MAX_ROW = 1048575;
function column(index) {
	let name = "";
	for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) name = String.fromCharCode(65 + (value - 1) % 26) + name;
	return name;
}
function rangeName(range) {
	return `${column(range.firstColumn)}${range.firstRow + 1}:${column(range.lastColumn)}${range.lastRow + 1}`;
}
function parseCellRange(value) {
	const match = /^\$?([A-Z]{1,3})\$?([1-9]\d{0,6})(?::\$?([A-Z]{1,3})\$?([1-9]\d{0,6}))?$/i.exec(value);
	if (!match) throw new TypeError("range must be an A1 cell or rectangle without a sheet prefix.");
	const col = (name) => [...name.toUpperCase()].reduce((sum, c) => sum * 26 + c.charCodeAt(0) - 64, 0) - 1;
	const firstColumn = col(match[1]);
	const firstRow = Number(match[2]) - 1;
	const lastColumn = col(match[3] ?? match[1]);
	const lastRow = Number(match[4] ?? match[2]) - 1;
	if (lastColumn < firstColumn || lastRow < firstRow || lastColumn > MAX_COLUMN || lastRow > MAX_ROW) throw new TypeError("range exceeds Calc worksheet bounds or has reversed endpoints.");
	return {
		firstColumn,
		firstRow,
		lastColumn,
		lastRow
	};
}

const IMAGE_FORMATS = [
	"doc",
	"docx",
	"odt",
	"xls",
	"xlsx",
	"ods",
	"ppt",
	"pptx",
	"odp",
	"pdf"
];
function resolveImageRender(request) {
	if (!request || typeof request.inputPath !== "string" || typeof request.outputDir !== "string" || !isAbsolute(request.inputPath) || !isAbsolute(request.outputDir) || request.inputPath.includes("\0") || request.outputDir.includes("\0")) throw new TypeError("inputPath and outputDir must be absolute filesystem paths.");
	const inputPath = resolve(request.inputPath), outputDir = resolve(request.outputDir);
	const within = relative(outputDir, inputPath);
	if (!within || !within.startsWith("..") && !isAbsolute(within)) throw new TypeError("Input cannot be inside the newly owned output directory.");
	const extension = extname(inputPath).slice(1).toLowerCase();
	if (!IMAGE_FORMATS.includes(extension)) throw new ConversionError("unsupported-format", `Unsupported image input: ${extension}.`);
	const calc = [
		"xls",
		"xlsx",
		"ods"
	].includes(extension);
	if (calc && request.pages !== void 0) throw new TypeError("Worksheets use sheet and A1 range, not printed page numbers.");
	if (!calc && (request.sheet !== void 0 || request.range !== void 0)) throw new TypeError("sheet and range apply only to worksheets.");
	if (request.sheet !== void 0 && (typeof request.sheet !== "string" || !request.sheet.trim() || request.sheet.includes("\0"))) throw new TypeError("sheet must be a nonempty exact worksheet name.");
	if (request.range !== void 0 && request.sheet === void 0) throw new TypeError("range requires an exact sheet name.");
	const range = request.range === void 0 ? void 0 : rangeName(parseCellRange(request.range));
	const pages = request.pages ?? "all";
	if (pages !== "all" && (!Array.isArray(pages) || pages.length === 0 || pages.some((page) => !Number.isSafeInteger(page) || page < 1) || new Set(pages).size !== pages.length)) throw new TypeError("pages must be all or distinct positive one-based page numbers.");
	const dpi = request.dpi ?? 144;
	const maxPages = request.maxPages ?? 100;
	const maxPixels = request.maxPixels ?? 16777216;
	const maxDimension = request.maxDimension ?? 8192;
	if (!Number.isFinite(dpi) || dpi < 24 || dpi > 600) throw new TypeError("dpi must be between 24 and 600.");
	if (!Number.isSafeInteger(maxPages) || maxPages < 1 || maxPages > 1e4) throw new TypeError("maxPages must be an integer between 1 and 10000.");
	if (!Number.isSafeInteger(maxPixels) || maxPixels < 1 || maxPixels > 16777216) throw new TypeError("maxPixels must be between 1 and 16777216.");
	if (!Number.isSafeInteger(maxDimension) || maxDimension < 1 || maxDimension > 16777216) throw new TypeError("maxDimension must be between 1 and 16777216.");
	if (pages !== "all" && pages.length > maxPages) throw new ConversionError("output-too-large", "Selected page count exceeds maxPages.");
	return {
		kind: "images",
		inputPath,
		outputDir,
		extension,
		dpi,
		maxPages,
		maxPixels,
		maxDimension,
		...calc ? {} : { pages: pages === "all" ? "all" : [...pages] },
		...request.sheet === void 0 ? {} : { sheet: request.sheet },
		...range === void 0 ? {} : { range }
	};
}

const SANS_CJK_FAMILIES = [
	"Microsoft YaHei",
	"Microsoft YaHei UI",
	"微软雅黑",
	"PingFang SC",
	"Noto Sans CJK SC",
	"Noto Sans SC",
	"Source Han Sans SC",
	"SimHei",
	"黑体",
	"Heiti SC",
	"STHeiti"
];
/** Ordered family groups used when the caller supplies none. */
const FONT_FALLBACKS = [
	["Calibri", "Carlito"],
	[
		"Calibri Light",
		"Carlito",
		"Calibri"
	],
	["Cambria", "Caladea"],
	[
		"宋体",
		"SimSun",
		"NSimSun",
		"Songti SC",
		"STSong",
		"Noto Serif CJK SC",
		"Noto Serif SC",
		"Source Han Serif SC"
	],
	[
		"黑体",
		"SimHei",
		"Heiti SC",
		"STHeiti",
		"Noto Sans CJK SC",
		"Noto Sans SC",
		"Source Han Sans SC"
	],
	[
		"微软雅黑",
		"Microsoft YaHei",
		"Microsoft YaHei UI",
		"PingFang SC",
		"Noto Sans CJK SC",
		"Noto Sans SC"
	],
	[
		"楷体",
		"KaiTi",
		"Kaiti SC",
		"STKaiti",
		"LXGW WenKai"
	],
	[
		"仿宋",
		"FangSong",
		"STFangsong",
		"Songti SC",
		"Noto Serif CJK SC"
	],
	[
		"sans-serif",
		"Arial",
		"Liberation Sans",
		"Helvetica",
		"DejaVu Sans",
		"Calibri",
		"Calibri Light",
		"Carlito",
		...SANS_CJK_FAMILIES
	],
	[
		"serif",
		"Times New Roman",
		"Liberation Serif",
		"Times",
		"DejaVu Serif",
		"Cambria",
		"Caladea",
		"SimSun",
		"NSimSun",
		"宋体",
		"Songti SC",
		"STSong",
		"Noto Serif CJK SC",
		"Noto Serif SC",
		"Source Han Serif SC"
	],
	[
		"monospace",
		"Courier New",
		"Liberation Mono",
		"DejaVu Sans Mono",
		"Menlo",
		"Monaco",
		"Courier",
		"NSimSun",
		"Noto Sans Mono CJK SC",
		...SANS_CJK_FAMILIES
	],
	[
		"Symbol",
		"Standard Symbols PS",
		"Symbola",
		"Segoe UI Symbol",
		"Apple Symbols",
		"FreeSerif",
		"DejaVu Sans"
	]
];
const DEFAULT_LIMITS = {
	timeoutMs: 12e4,
	maxInputBytes: 67108864,
	maxOutputBytes: 134217728,
	maxImageResolution: 144,
	maxArchiveEntries: 2e4,
	maxUncompressedBytes: 536870912,
	maxFontFiles: 2e4,
	maxFontFileBytes: 268435456,
	maxLoadedFontBytes: 536870912,
	maxFontResolutionEntries: 4096,
	maxFontMetadataCacheBytes: 33554432
};
const FONT_COLLECTION_NAMES = ["fontDirectories", "initialFontFamilies"];
function positiveSafeInteger(value, name) {
	if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) throw new RangeError(`${name} must be a positive safe integer.`);
	if (name.endsWith("Ms") && value > 2147483647) throw new RangeError(`${name} exceeds the Node timer range.`);
	return value;
}
function fontNames(value, name) {
	if (!Array.isArray(value)) throw new TypeError(`${name} must contain nonempty strings.`);
	const names = [];
	for (const entry of value) {
		if (typeof entry !== "string" || entry.length === 0 || entry.includes("\0")) throw new TypeError(`${name} must contain nonempty strings.`);
		names.push(entry);
	}
	return names;
}
function fontGroups(value) {
	if (!Array.isArray(value) || value.some((group) => !Array.isArray(group) || group.length < 2 || group.some((entry) => typeof entry !== "string" || !entry.trim()))) throw new TypeError("fontFallbacks must contain groups of at least two nonblank font names.");
	return value.map((group) => [...group]);
}
/**
* Validate an optional caller-supplied engine package resolver.
* @param value - The `resolveEnginePackage` option value.
* @returns the resolver, or undefined when absent.
* @throws TypeError when the value is defined and not a function.
*/
function enginePackageResolver(value) {
	if (value !== void 0 && typeof value !== "function") throw new TypeError("resolveEnginePackage must be a function.");
	return value;
}
/**
* Resolve defaults once; reject misspelled options and malformed font settings.
* @param input - Caller options; absent fields keep their documented default.
* @returns The validated limits and font settings, with caller arrays copied.
* @throws TypeError for a non-object argument, an unknown option name, or a non-function `resolveEnginePackage`.
* @throws RangeError for a limit outside the positive safe-integer timer range.
*/
function resolveOptions(input = {}) {
	const callerOptions = input;
	if (callerOptions === null || typeof callerOptions !== "object" || Array.isArray(callerOptions)) throw new TypeError("Converter options must be an object.");
	const merged = {
		...DEFAULT_LIMITS,
		fontDirectories: systemFontDirectories(),
		fontFallbacks: FONT_FALLBACKS,
		initialFontFamilies: [],
		...input
	};
	for (const key of Object.keys(input)) if (!(key in DEFAULT_LIMITS) && !FONT_COLLECTION_NAMES.includes(key) && key !== "fontFallbacks" && key !== "fontMetadataCacheDirectory" && key !== "resolveEnginePackage") throw new TypeError(`Unknown converter option: ${key}`);
	enginePackageResolver(input.resolveEnginePackage);
	const cacheDirectory = input.fontMetadataCacheDirectory === void 0 ? defaultFontMetadataCacheDirectory() : input.fontMetadataCacheDirectory;
	if (cacheDirectory !== false && (typeof cacheDirectory !== "string" || !isAbsolute(cacheDirectory) || cacheDirectory.includes("\0"))) throw new TypeError("fontMetadataCacheDirectory must be an absolute path or false.");
	return {
		fontMetadataCacheDirectory: cacheDirectory,
		maxFontMetadataCacheBytes: positiveSafeInteger(merged.maxFontMetadataCacheBytes, "maxFontMetadataCacheBytes"),
		timeoutMs: positiveSafeInteger(merged.timeoutMs, "timeoutMs"),
		maxInputBytes: positiveSafeInteger(merged.maxInputBytes, "maxInputBytes"),
		maxOutputBytes: positiveSafeInteger(merged.maxOutputBytes, "maxOutputBytes"),
		maxImageResolution: positiveSafeInteger(merged.maxImageResolution, "maxImageResolution"),
		maxArchiveEntries: positiveSafeInteger(merged.maxArchiveEntries, "maxArchiveEntries"),
		maxUncompressedBytes: positiveSafeInteger(merged.maxUncompressedBytes, "maxUncompressedBytes"),
		maxFontFiles: positiveSafeInteger(merged.maxFontFiles, "maxFontFiles"),
		maxFontFileBytes: positiveSafeInteger(merged.maxFontFileBytes, "maxFontFileBytes"),
		maxLoadedFontBytes: positiveSafeInteger(merged.maxLoadedFontBytes, "maxLoadedFontBytes"),
		maxFontResolutionEntries: positiveSafeInteger(merged.maxFontResolutionEntries, "maxFontResolutionEntries"),
		fontDirectories: fontNames(merged.fontDirectories, "fontDirectories"),
		includeOfficeFonts: input.fontDirectories === void 0,
		initialFontFamilies: fontNames(merged.initialFontFamilies, "initialFontFamilies"),
		fontFallbacks: fontGroups(merged.fontFallbacks)
	};
}

const CONVERSION_FORMATS = [
	{
		inputs: [
			"doc",
			"docx",
			"odt"
		],
		outputs: [
			"pdf",
			"docx",
			"odt",
			"txt"
		]
	},
	{
		inputs: [
			"xls",
			"xlsx",
			"ods"
		],
		outputs: [
			"pdf",
			"xlsx",
			"ods",
			"csv"
		]
	},
	{
		inputs: [
			"ppt",
			"pptx",
			"odp"
		],
		outputs: [
			"pdf",
			"pptx",
			"odp"
		]
	}
];
/**
* Validate paths and the format matrix before file access or queue admission.
* @param request - Public conversion parameters.
* @param operation - PDF compatibility entry, general conversion, or workbook recalculation.
* @returns The explicit engine operation.
*/
function resolveConversion(request, operation) {
	if (!request || typeof request.inputPath !== "string" || typeof request.outputPath !== "string" || !isAbsolute(request.inputPath) || !isAbsolute(request.outputPath) || request.inputPath.includes("\0") || request.outputPath.includes("\0")) throw new TypeError("inputPath and outputPath must be absolute filesystem paths.");
	if (resolve(request.inputPath) === resolve(request.outputPath)) throw new TypeError("Input and output paths must differ.");
	const extension = extname(request.inputPath).slice(1).toLowerCase();
	const format = operation === "render" ? "pdf" : extname(request.outputPath).slice(1).toLowerCase();
	const family = CONVERSION_FORMATS.find((group) => group.inputs.includes(extension));
	if (!family || !family.outputs.includes(format)) throw new ConversionError("unsupported-format", `Unsupported conversion: ${extension || "(no input extension)"} → ${format || "(no output extension)"}.`);
	if (operation === "recalculate" && (![
		"xls",
		"xlsx",
		"ods"
	].includes(extension) || !["xlsx", "ods"].includes(format))) throw new ConversionError("unsupported-format", "Recalculation requires XLS, XLSX, or ODS input and XLSX or ODS output.");
	if (request.sheet !== void 0 && (format !== "csv" || typeof request.sheet !== "string" || !request.sheet.trim() || request.sheet.includes("\0"))) throw new TypeError("sheet must be a nonempty exact worksheet name and is supported only for CSV output.");
	return {
		inputPath: request.inputPath,
		outputPath: request.outputPath,
		extension,
		format,
		recalculate: operation === "recalculate",
		...request.sheet === void 0 ? {} : { sheet: request.sheet }
	};
}

