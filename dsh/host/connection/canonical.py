"""Canonical Connection plugin owning the authenticated /api route."""
import math

from dsh.cordis.plugin import Plugin
from dsh.host.connection.api_trust import assert_trusted_authority
from dsh.host.connection.browser_auth import BrowserAuth
from dsh.host.connection.rpc_host import HostConnectionService
from dsh.host.connection.http_bridge import bridge_handler, DEFAULT_MAX_REQUEST_BODY_BYTES


class CanonicalConnectionPlugin(Plugin):
    id = "client-connection"
    inject = ["webServer", "credentials"]

    def apply(self, ctx):
        trusted = self.config.get("trustedHosts", [])
        days = self.config.get("cookieMaxAgeDays", 30)
        limit = self.config.get("maxRequestBodyBytes", DEFAULT_MAX_REQUEST_BODY_BYTES)
        if not isinstance(trusted, list):
            raise ValueError("connection: trustedHosts must be an array")
        for value in trusted:
            assert_trusted_authority(value)
        if any(type(value) is not int or value < 1 for value in (days, limit)):
            raise ValueError("connection: cookieMaxAgeDays and maxRequestBodyBytes must be positive integers")
        def capacity(child):
            attachments = child.get("attachments")
            limits = getattr(attachments, "imageLimits", None) or getattr(attachments, "image_limits", None)
            if limits is not None:
                maximum = limits.get("maxMessageImageBytes") if isinstance(limits, dict) else limits.maxMessageImageBytes
                required = math.ceil(maximum * 4 / 3) + 1024 * 1024
                if limit < required:
                    raise ValueError("client-connection maxRequestBodyBytes must cover the configured aggregate image limit")
        if ctx.get("attachments") is not None:
            capacity(ctx)
        auth = BrowserAuth.create(ctx.root, ctx.get("credentials"), days)
        connection = HostConnectionService(ctx, trusted, auth)
        fetch = connection.create_shared_fetch_handler("/api").fetch
        ctx.effect(lambda: ctx.get("webServer").register("prefix", "/api", bridge_handler(connection, fetch, limit)), "Connection /api route")
        ctx.inject(["attachments"], capacity)
