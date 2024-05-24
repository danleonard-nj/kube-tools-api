import enum


class Feature(enum.StrEnum):
    AcrPurge = 'acr-purge-service'
    PodcastSync = 'podcast-sync-service'
    UsageReport = 'azure-usage-report'
    PodcastSyncEmailNotify = 'podcast-sync-email-notify'
    EmailRuleLogIngestion = 'email-rule-log-ingestion'
    NestSensorDataIngestion = 'nest-sensor-data-ingestion'
    BankingBalanceCaptureEmailNotify = 'banking-balance-capture-emails'
    PlaidSync = 'plaid-sync'
    PlaidSyncCacheEnabled = 'plaid-sync-cache'
    CoinbaseSync = 'coinbase-sync'
    BankBalanceDisplayAllAccounts = 'bank-balance-display-all-accounts'
    BankBalanceDisplayCryptoBalances = 'show-crypto-balances'
    BankBalanceUseAgeCutoffThreshold = 'bank-balance-use-age-cutoff-threshold'
    ConversationServiceInboundNoTriggerWord = 'conversation-service-inbound-no-trigger-word'
