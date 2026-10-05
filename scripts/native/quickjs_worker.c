#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include "quickjs.h"

typedef struct {
    uint64_t deadline;
    int enabled;
} SliceDeadline;

static char *read_line(void) {
    size_t capacity = 4096;
    size_t length = 0;
    char *buffer = malloc(capacity);
    if (buffer == NULL) return NULL;
    for (;;) {
        int character = getchar();
        if (character == EOF || character == '\n') break;
        if (length + 1 >= capacity) {
            if (capacity > SIZE_MAX / 2) { free(buffer); return NULL; }
            char *grown = realloc(buffer, capacity * 2);
            if (grown == NULL) { free(buffer); return NULL; }
            capacity *= 2;
            buffer = grown;
        }
        buffer[length++] = (char) character;
    }
    if (length == 0 && feof(stdin)) { free(buffer); return NULL; }
    buffer[length] = '\0';
    return buffer;
}

static int interrupted(JSRuntime *runtime, void *opaque) {
    SliceDeadline *slice = opaque;
    return slice->enabled && GetTickCount64() >= slice->deadline;
}

static JSValue emit(JSContext *context, JSValueConst receiver, int count, JSValueConst *arguments) {
    if (count != 1) return JS_ThrowTypeError(context, "protocol emission requires one string");
    const char *message = JS_ToCString(context, arguments[0]);
    if (message == NULL) return JS_EXCEPTION;
    int failed = fputs(message, stdout) == EOF || fputc('\n', stdout) == EOF || fflush(stdout) == EOF;
    JS_FreeCString(context, message);
    if (failed) return JS_ThrowInternalError(context, "worker protocol output failed");
    return JS_UNDEFINED;
}

static void emit_exception(JSContext *context, const char *type) {
    JSValue exception = JS_GetException(context);
    JSValue message = JS_GetPropertyStr(context, exception, "message");
    if (!JS_IsString(message)) {
        JS_FreeValue(context, message);
        message = JS_ToString(context, exception);
    }
    JSValue report = JS_NewObject(context);
    JS_SetPropertyStr(context, report, "type", JS_NewString(context, type));
    JS_SetPropertyStr(context, report, "error", message);
    JSValue encoded = JS_JSONStringify(context, report, JS_UNDEFINED, JS_UNDEFINED);
    const char *text = JS_ToCString(context, encoded);
    if (text != NULL) { puts(text); fflush(stdout); JS_FreeCString(context, text); }
    JS_FreeValue(context, encoded);
    JS_FreeValue(context, report);
    JS_FreeValue(context, exception);
}

static int deliver(JSContext *host, JSValueConst global, const char *source) {
    JSValue message = JS_ParseJSON(host, source, strlen(source), "worker-message");
    if (JS_IsException(message)) { emit_exception(host, "protocol-error"); return -1; }
    JSValue receiver = JS_GetPropertyStr(host, global, "__receive");
    JSValue delivered = JS_Call(host, receiver, JS_UNDEFINED, 1, &message);
    int failed = JS_IsException(delivered);
    if (failed) emit_exception(host, "protocol-error");
    JS_FreeValue(host, delivered);
    JS_FreeValue(host, receiver);
    JS_FreeValue(host, message);
    return failed ? -1 : 0;
}

int main(void) {
    int exit_code = 0;
    JSRuntime *runtime = NULL;
    JSContext *host = NULL;
    JSContext *script = NULL;
    JSValue request = JS_UNDEFINED;
    JSValue compiled = JS_UNDEFINED;
    JSValue host_global = JS_UNDEFINED;
    JSValue script_global = JS_UNDEFINED;
    JSValue drive = JS_UNDEFINED;
    char *initial = NULL;
    char *wrapped = NULL;
    char *control = NULL;
    const char *body = NULL;
    const char *name = NULL;
    JSValue body_value = JS_UNDEFINED;
    JSValue name_value = JS_UNDEFINED;
    SliceDeadline slice = {0, 0};
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    initial = read_line();
    if (initial == NULL) { exit_code = 2; goto cleanup; }
    runtime = JS_NewRuntime();
    if (runtime == NULL) { exit_code = 3; goto cleanup; }
    host = JS_NewContext(runtime);
    script = JS_NewContext(runtime);
    if (host == NULL || script == NULL) { exit_code = 4; goto cleanup; }
    JS_SetInterruptHandler(runtime, interrupted, &slice);
    request = JS_ParseJSON(host, initial, strlen(initial), "worker-init");
    if (JS_IsException(request)) { emit_exception(host, "protocol-error"); exit_code = 5; goto cleanup; }
    body_value = JS_GetPropertyStr(host, request, "body");
    name_value = JS_GetPropertyStr(host, request, "name");
    if (!JS_IsString(body_value) || !JS_IsString(name_value)) {
        JS_ThrowTypeError(host, "worker body and name must be strings");
        emit_exception(host, "protocol-error"); exit_code = 6; goto cleanup;
    }
    size_t body_length;
    body = JS_ToCStringLen(host, &body_length, body_value);
    name = JS_ToCString(host, name_value);
    if (body == NULL || name == NULL) { emit_exception(host, "protocol-error"); exit_code = 6; goto cleanup; }
    const char *prefix = "(async () => {\n";
    const char *suffix = "\n})()";
    if (body_length > SIZE_MAX - strlen(prefix) - strlen(suffix) - 1) { exit_code = 3; goto cleanup; }
    size_t wrapped_length = strlen(prefix) + body_length + strlen(suffix);
    wrapped = malloc(wrapped_length + 1);
    if (wrapped == NULL) { exit_code = 3; goto cleanup; }
    memcpy(wrapped, prefix, strlen(prefix));
    memcpy(wrapped + strlen(prefix), body, body_length);
    memcpy(wrapped + strlen(prefix) + body_length, suffix, strlen(suffix) + 1);
    compiled = JS_Eval(script, wrapped, wrapped_length, name, JS_EVAL_TYPE_GLOBAL | JS_EVAL_FLAG_COMPILE_ONLY);
    if (JS_IsException(compiled)) { emit_exception(script, "parse-error"); exit_code = 7; goto cleanup; }
    JSValue mode = JS_GetPropertyStr(host, request, "mode");
    const char *mode_name = JS_ToCString(host, mode);
    int parse_only = mode_name != NULL && strcmp(mode_name, "parse") == 0;
    JS_FreeCString(host, mode_name);
    JS_FreeValue(host, mode);
    if (parse_only) { puts("{\"type\":\"parsed\",\"ok\":true}"); fflush(stdout); goto cleanup; }
    host_global = JS_GetGlobalObject(host);
    JS_SetPropertyStr(host, host_global, "__emit", JS_NewCFunction(host, emit, "emit", 1));
    JS_SetPropertyStr(host, host_global, "__request", JS_DupValue(host, request));
    JSValue bootstrap = JS_GetPropertyStr(host, request, "bootstrap");
    size_t bootstrap_length;
    const char *bootstrap_source = JS_ToCStringLen(host, &bootstrap_length, bootstrap);
    if (bootstrap_source == NULL) {
        JS_FreeValue(host, bootstrap); emit_exception(host, "bootstrap-error"); exit_code = 8; goto cleanup;
    }
    JSValue boot = JS_Eval(host, bootstrap_source, bootstrap_length, "host-bootstrap", JS_EVAL_TYPE_GLOBAL);
    JS_FreeCString(host, bootstrap_source);
    JS_FreeValue(host, bootstrap);
    int boot_failed = JS_IsException(boot);
    JS_FreeValue(host, boot);
    if (boot_failed) { emit_exception(host, "bootstrap-error"); exit_code = 9; goto cleanup; }
    script_global = JS_GetGlobalObject(script);
    const char *properties[] = {"args", "agent", "parallel", "pipeline", "phase", "log", NULL};
    for (const char **property = properties; *property != NULL; property++) {
        if (JS_SetPropertyStr(script, script_global, *property, JS_GetPropertyStr(host, host_global, *property)) < 0) {
            emit_exception(script, "bootstrap-error"); exit_code = 9; goto cleanup;
        }
    }
    puts("{\"type\":\"ready\"}");
    fflush(stdout);
    control = read_line();
    if (control == NULL) { exit_code = 10; goto cleanup; }
    JSValue instruction = JS_ParseJSON(host, control, strlen(control), "worker-control");
    if (JS_IsException(instruction)) { emit_exception(host, "protocol-error"); exit_code = 5; goto cleanup; }
    JSValue control_type = JS_GetPropertyStr(host, instruction, "type");
    const char *control_name = JS_ToCString(host, control_type);
    int go = control_name != NULL && strcmp(control_name, "go") == 0;
    int cancel = control_name != NULL && strcmp(control_name, "cancel") == 0;
    JS_FreeCString(host, control_name);
    JS_FreeValue(host, control_type);
    JS_FreeValue(host, instruction);
    if (!go && !cancel) {
        JS_ThrowTypeError(host, "worker startup requires go or cancel");
        emit_exception(host, "protocol-error"); exit_code = 5; goto cleanup;
    }
    JSValue promise = JS_UNDEFINED;
    if (cancel) {
        if (deliver(host, host_global, control) < 0) { exit_code = 5; goto cleanup; }
    } else {
        JSValue timeout = JS_GetPropertyStr(host, request, "timeoutMs");
        double milliseconds = 5000;
        int timeout_failed = JS_ToFloat64(host, &milliseconds, timeout) < 0;
        JS_FreeValue(host, timeout);
        if (timeout_failed || !(milliseconds >= 1 && milliseconds <= 9007199254740991.0)
                || (uint64_t) milliseconds != milliseconds) {
            if (!timeout_failed) JS_ThrowTypeError(host, "worker timeout must be a positive safe integer");
            emit_exception(host, "protocol-error"); exit_code = 5; goto cleanup;
        }
        slice.deadline = GetTickCount64() + (uint64_t) milliseconds;
        slice.enabled = 1;
        promise = JS_EvalFunction(script, compiled);
        compiled = JS_UNDEFINED;
        slice.enabled = 0;
        if (JS_IsException(promise)) { emit_exception(script, "execution-error"); exit_code = 11; goto cleanup; }
    }
    JS_SetPropertyStr(host, host_global, "__scriptPromise", promise);
    const char *drive_source = "globalThis.__drive(__scriptPromise)";
    drive = JS_Eval(host, drive_source, strlen(drive_source), "host-drive", JS_EVAL_TYPE_GLOBAL);
    if (JS_IsException(drive)) { emit_exception(host, "drive-error"); exit_code = 12; goto cleanup; }
    while (JS_PromiseState(host, drive) == JS_PROMISE_PENDING) {
        JSContext *pending_context = NULL;
        int pending = JS_ExecutePendingJob(runtime, &pending_context);
        if (pending < 0) { emit_exception(pending_context, "job-error"); exit_code = 13; goto cleanup; }
        if (pending == 0) {
            char *message = read_line();
            if (message == NULL) { exit_code = 14; goto cleanup; }
            int delivered = deliver(host, host_global, message);
            free(message);
            if (delivered < 0) { exit_code = 5; goto cleanup; }
        }
    }
    if (JS_PromiseState(host, drive) == JS_PROMISE_REJECTED) {
        JSValue rejection = JS_PromiseResult(host, drive);
        JS_Throw(host, rejection);
        emit_exception(host, "drive-error"); exit_code = 12;
    }
cleanup:
    free(initial);
    free(wrapped);
    free(control);
    if (host != NULL) {
        if (body != NULL) JS_FreeCString(host, body);
        if (name != NULL) JS_FreeCString(host, name);
        JS_FreeValue(host, body_value);
        JS_FreeValue(host, name_value);
        JS_FreeValue(host, drive);
        JS_FreeValue(host, host_global);
        JS_FreeValue(host, request);
    }
    if (script != NULL) {
        JS_FreeValue(script, compiled);
        JS_FreeValue(script, script_global);
        JS_FreeContext(script);
    }
    if (host != NULL) JS_FreeContext(host);
    if (runtime != NULL) JS_FreeRuntime(runtime);
    return exit_code;
}
