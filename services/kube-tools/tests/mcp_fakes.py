"""In-memory stand-ins for the MCP OAuth storage, shared by the MCP tests."""


class FakeOAuthRepository:
    """Covers exactly what McpAuthService uses, without Redis or Mongo."""

    def __init__(self):
        self.clients = {}
        self.pending = {}
        self.codes = {}
        self.access = {}
        self.refresh = {}
        self.attempts = {}

    async def save_client(self, client_id, document):
        self.clients[client_id] = document

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def put_pending(self, txn_id, payload, ttl):
        self.pending[txn_id] = payload

    async def peek_pending(self, txn_id):
        return self.pending.get(txn_id)

    async def take_pending(self, txn_id):
        return self.pending.pop(txn_id, None)

    async def put_code(self, code, payload, ttl):
        self.codes[code] = payload

    async def peek_code(self, code):
        return self.codes.get(code)

    async def take_code(self, code):
        return self.codes.pop(code, None)

    async def put_access_token(self, token, payload, ttl):
        self.access[token] = payload

    async def get_access_token(self, token):
        return self.access.get(token)

    async def delete_access_token(self, token):
        self.access.pop(token, None)

    async def put_refresh_token(self, token, payload):
        self.refresh[token] = payload

    async def get_refresh_token(self, token):
        return self.refresh.get(token)

    async def delete_refresh_token(self, token):
        return self.refresh.pop(token, None) is not None

    async def record_failed_attempt(self, key, ttl):
        self.attempts[key] = self.attempts.get(key, 0) + 1
        return self.attempts[key]

    async def failed_attempts(self, key):
        return self.attempts.get(key, 0)

    async def clear_failed_attempts(self, key):
        self.attempts.pop(key, None)


class FakeRedis:
    """The Redis commands McpOAuthRepository issues."""

    def __init__(self):
        self.data = {}

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def get(self, key):
        return self.data.get(key)

    async def getdel(self, key):
        return self.data.pop(key, None)

    async def delete(self, key):
        self.data.pop(key, None)


class FakeCacheClient:
    """Stands in for framework's CacheClientAsync, which exposes `.client`."""

    def __init__(self):
        self.client = FakeRedis()


class FakeProvider:
    """A DI container resolving only what it was given."""

    def __init__(self, services):
        self._services = services

    def resolve(self, service_type):
        return self._services[service_type]
