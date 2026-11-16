"""Public account bootstrap data and device-local onboarding configuration."""
import re

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z


CONTACT_CONFIG_GLOBAL = '__DSH_CONTACT_CONFIG__'
NOTIFICATIONS_CONFIG_GLOBAL = '__DSH_ACCOUNT_NOTIFICATIONS_CONFIG__'
CONTACT_FORM_URL = 'https://trtgsjkv6r.feishu.cn/share/base/form/shrcnlCoGElW7MQznGy9r3YYXcg?hide_uid=1&hide_device_info=1&hide_harness_version=1'

AccountConfig = z.object(dict(
    contactFormUrl=z.string().pattern(re.compile(r'^https://[^/\s]+/')).default(CONTACT_FORM_URL),
    contactSource=z.string().default(''),
    version=z.const(1).default(1).volatile(),
    step=z.union(['welcome', 'credit', 'purpose', 'process', 'done']).default('welcome').volatile(),
    purpose=z.union(['office', 'development', 'both', z.const(None)]).volatile(),
    process=z.union(['compact', 'standard', 'detailed', z.const(None)]).volatile(),
    completion=z.union(['completed', 'skipped', 'api-key', z.const(None)]).volatile(),
    usage=z.union(['compact', 'detailed']).default('compact').volatile(),
    developerTools=z.boolean().default(False).volatile(),
))
NotificationConfig = z.object(dict(
    notificationPollIntervalMs=z.natural().min(1).max(2147483647).default(600000),
))


class CurrentUiSettingsAccount(Plugin):
    id = 'ui-settings-account'
    name = '@deepseek-ai/dsh-client-ui-settings-account'
    Config = AccountConfig

    def apply(self, ctx):
        def settings(scope):
            scope.effect(lambda: scope.settings.configure(dict(auto=False), ctx.fiber))
        ctx.inject(['settings'], settings)
        ctx.on('webserver/index-inject', lambda table, *args: table.append(dict(
            kind='global', name=CONTACT_CONFIG_GLOBAL,
            value=dict(contactFormUrl=self.config['contactFormUrl'], contactSource=self.config['contactSource']))))


class CurrentUiAccountNotifications(Plugin):
    id = 'ui-account-notifications'
    name = '@deepseek-ai/dsh-client-ui-account-notifications'
    Config = NotificationConfig

    def apply(self, ctx):
        ctx.on('webserver/index-inject', lambda table, *args: table.append(dict(
            kind='global', name=NOTIFICATIONS_CONFIG_GLOBAL, value=self.config)))
