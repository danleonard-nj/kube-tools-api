import enum


class BankKey(enum.StrEnum):
    Amex = 'amex'
    WellsFargo = 'wells-fargo'
    WellsFargoChecking = 'wells-fargo-checking'
    WellsFargoActiveCash = 'wells-fargo-active-cash'
    WellsFargoPlatinum = 'wells-fargo-platinum'
    Chase = 'chase'
    CapitalOne = 'capital-one'
    CapitalOneQuickSilver = 'capital-one-quicksilver'
    CapitalOneVenture = 'capital-one-venture'
    CapitalOneSavor = 'capital-one-savorone'
    Discover = 'discover'
    Ally = 'ally'
    AllySavingsAccount = 'ally-savings-account'
    Synchrony = 'synchrony'
    SynchronyAmazon = 'synchrony-amazon'
    SynchronyGuitarCenter = 'synchrony-guitar-center'
    SynchronySweetwater = 'synchrony-sweetwater'
    # Bitcoin = 'bitcoin'
    # Solana = 'solana'

    @classmethod
    def values(
        cls
    ):
        return [x.value for x in cls]


class PlaidTransactionCategory(enum.StrEnum):
    Debit = 'Debit'
    Payroll = 'Payroll'
    Service = 'Service'
    Payment = 'Payment'
    Electric = 'Electric'
    CarDealersAndLeasing = 'Car Dealers and Leasing'
    Hardware_Store = 'Hardware Store'
    Subscription = 'Subscription'
    Shops = 'Shops'
    Withdrawal = 'Withdrawal'
    Credit = 'Credit'
    Credit_Card = 'Credit Card'
    Insurance = 'Insurance'
    TelecommunicationServices = 'Telecommunication Services'
    FoodAndDrink = 'Food and Drink'
    ThirdParty = 'Third Party'
    Restaurants = 'Restaurants'
    Utilities = 'Utilities'
    Rent = 'Rent'
    ATM = 'ATM'
    Transfer = 'Transfer'
    Cable = 'Cable'
    Automotive = 'Automotive'
    Venmo = 'Venmo'
    Financial = 'Financial'
    Interest = 'Interest'
    InterestEarned = 'Interest Earned'
    Deposit = 'Deposit'
    Check = 'Check'
    Undefined = 'Undefined'
    BankFees = 'Bank Fees'


class PlaidPaymentChannel(enum.StrEnum):
    InStore = 'in store'
    Online = 'online'
    Other = 'other'


class PlaidTransactionType(enum.StrEnum):
    Special = 'special'
    Place = 'place'


class SyncActionType(enum.StrEnum):
    Insert = 'insert'
    Update = 'update'
    NoAction = 'no-action'


class SyncType(enum.StrEnum):
    Email = 'email'
    Plaid = 'plaid'
    Coinbase = 'coinbase'


class ProcessGmailRuleResultType(enum.StrEnum):
    Success = 'success'
    Failure = 'failure'
