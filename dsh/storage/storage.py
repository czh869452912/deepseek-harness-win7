"""
Storage hub (`ctx.storage`): named backend registry plus mounted data-form facilities.
Re-exports storage hub, backends, and plugins for 1:1 alignment with official `@deepseek-ai/dsh-storage`.
"""

from dsh.storage.backend import KvFacet, KvUnit, KvUnitDescriptor, StorageBackend, UNIT_NAME_RE
from dsh.storage.domain_error import DomainError
from dsh.storage.domain_events import DomainChanged
from dsh.storage.domain_impl import DomainFacility, DomainGlobal, DomainImpl, KvTable
from dsh.storage.domain_spec import define_domain, defineDomain, descriptor_of, descriptorOf, domain_table, domainTable, DomainSpec
from dsh.storage.error import StorageError
from dsh.storage.hub import Storage, StoragePlugin, StorageService
from dsh.storage.registry import BackendRegistry
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.storage_sqlite import SqliteStorageBackend, STORAGE_SQLITE_SCHEMA_VERSION

__all__ = [
    "Storage",
    "StorageService",
    "StoragePlugin",
    "BackendRegistry",
    "StorageError",
    "StorageBackend",
    "KvFacet",
    "KvUnit",
    "KvUnitDescriptor",
    "UNIT_NAME_RE",
    "DomainFacility",
    "DomainImpl",
    "DomainSpec",
    "DomainGlobal",
    "KvTable",
    "DomainError",
    "DomainChanged",
    "define_domain",
    "defineDomain",
    "domain_table",
    "domainTable",
    "descriptor_of",
    "descriptorOf",
    "JsonStorageBackend",
    "SqliteStorageBackend",
    "STORAGE_SQLITE_SCHEMA_VERSION",
]
