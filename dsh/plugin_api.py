"""Experimental Python plugin API, version 1; services retain their own contracts."""

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.core.tools import ToolExecutionInput, ToolExecutionResult
from dsh.extensions.packaged_host import python_host_source, python_session_source, host_handler_service
from dsh.plugin_remote import JsonSchemaCodec
from dsh.typert.remote import Remote, RemoteScope, TypertRemoteService

API_VERSION = 1
__all__ = ["API_VERSION", "Context", "Plugin", "Schema", "ToolExecutionInput", "ToolExecutionResult",
           "python_host_source", "python_session_source", "host_handler_service", "JsonSchemaCodec",
           "Remote", "RemoteScope", "TypertRemoteService"]
