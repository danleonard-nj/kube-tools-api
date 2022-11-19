
class AzureGatewayCacheKey:
    @staticmethod
    def usage_key(url):
        return f'azure-gateway-usage-{url}'

    @staticmethod
    def token():
        return 'azure-gateway-client-token'
