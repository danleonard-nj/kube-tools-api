from framework.serialization import Serializable


class TransactionSyncResult(Serializable):
    def __init__(self, existing, synced):
        self.existing = existing
        self.synced = synced

    def to_dict(self):
        return {
            'existing': [x.to_dict() for x in self.existing],
            'synced': [x.to_dict() for x in self.synced]
        }
