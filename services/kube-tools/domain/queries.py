from domain.mongo import Queryable


class GetWeatherByZipCodeCardinalityKeyQuery(Queryable):
    def __init__(
        self,
        location_zipcode: str,
        cardinality_key: str
    ):
        self.location_zipcode = location_zipcode
        self.cardinality_key = cardinality_key

    def get_query(
        self
    ) -> dict:
        return {
            'location_zipcode': self.location_zipcode,
            'cardinality_key': self.cardinality_key
        }


class GetChatGptHistoryQuery(Queryable):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int,
        endpoint: str = None
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.endpoint = endpoint

    def get_query(
        self
    ) -> dict:
        query = {
            'created_date': {
                '$gte': self.start_timestamp,
                '$lt': self.end_timestamp
            }
        }

        if self.endpoint is not None:
            query['endpoint'] = self.endpoint

        return query


class GetBalanceByBankKeyQuery(Queryable):
    def __init__(
        self,
        bank_key: str,
        sync_type: str = None
    ):
        self.bank_key = bank_key
        self.sync_type = sync_type

    def get_query(
        self
    ):
        query = {
            'bank_key': self.bank_key
        }

        if self.sync_type is not None:
            query['sync_type'] = self.sync_type

        return query

    def get_sort(
        self
    ) -> list:
        return [('timestamp', -1)]


class GetBalanceHistoryQuery(Queryable):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: list[str] = None
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.bank_keys = bank_keys

    def get_query(
        self
    ) -> dict:
        query_filter = {
            'timestamp': {
                '$gte': self.start_timestamp,
                '$lte': self.end_timestamp
            }
        }

        if (self.bank_keys is not None
                and any(self.bank_keys)):

            query_filter['bank_key'] = {
                '$in': self.bank_keys
            }

        return query_filter

    def get_sort(
        self
    ) -> list:
        return [('timestamp', -1)]


class GetTransactionsQuery(Queryable):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: list[str] = None
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.bank_keys = bank_keys

    def get_query(
        self
    ):
        query_filter = {
            'transaction_date': {
                '$gte': self.start_timestamp,
                '$lte': self.end_timestamp
            }
        }

        if self.bank_keys is not None:
            query_filter['bank_key'] = {
                '$in': self.bank_keys
            }

        return query_filter


class GetTransactionsByTransactionBksQuery(Queryable):
    def __init__(
        self,
        bank_key: str,
        transaction_bks: list[str]
    ):
        self.bank_key = bank_key
        self.transaction_bks = transaction_bks

    def get_query(
        self
    ):
        return {
            'bank_key': self.bank_key,
            'transaction_bk': {
                '$in': self.transaction_bks
            }
        }


class GetApiEventsQuery(Queryable):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp

    def get_query(
        self
    ):
        return {
            'timestamp': {
                '$gte': self.start_timestamp,
                '$lte': self.end_timestamp
            }
        }


class GetApiEventsByLogIdsQuery(Queryable):
    def __init__(
        self,
        cutoff_timestamp: int,
        log_ids: list[str]
    ):
        self.cutoff_timestamp = cutoff_timestamp
        self.log_ids = log_ids

    def get_query(
        self
    ):
        return {
            'timestamp': {
                '$gte': self.cutoff_timestamp
            },
            'log_id': {
                '$nin': self.log_ids
            }
        }


class GetErrorApiEventsQuery(Queryable):
    def __init__(
        self,
    ):
        pass

    def get_query(
        self
    ):
        return {
            'status_code': {
                '$ne': 200
            }
        }


class EmailRulesByNamesQuery(Queryable):
    def __init__(
        self,
        rule_names: list[str]
    ):
        self.rule_names = rule_names

    def get_query(
        self
    ):
        return {
            'name': {
                '$in': self.rule_names
            }
        }
