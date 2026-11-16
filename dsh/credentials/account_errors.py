"""Client-safe Platform account failure classifications."""


class PlatformAuthError(Exception):
    def __init__(self, code):
        self.code = code
        self.message = 'account: '+code
        super().__init__(self.message)


class AccountUnauthorizedError(PlatformAuthError):
    def __init__(self):
        super().__init__('expired')
