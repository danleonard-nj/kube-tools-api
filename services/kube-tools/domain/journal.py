from framework.serialization import Serializable


class JournalEntry(Serializable):
    def __init__(
        self,
        entry_id: str,
        entry_date: str,
        category_id: str,
        unit_id: str,
        quantity: float,
        note: str,
        timestamp: int
    ):
        self.entry_id = entry_id
        self.entry_date = entry_date
        self.category_id = category_id
        self.unit_id = unit_id
        self.quantity = quantity
        self.note = note
        self.timestamp = timestamp

    @staticmethod
    def from_entity(data: dict):
        return JournalEntry(
            entry_id=data.get('entry_id'),
            entry_date=data.get('entry_date'),
            category_id=data.get('category_id'),
            unit_id=data.get('unit_id'),
            quantity=data.get('quantity'),
            note=data.get('note'),
            timestamp=data.get('timestamp')
        )


class JournalUnit(Serializable):
    def __init__(
        self,
        unit_id: str,
        unit_name: str,
        symbol_name: str,
        timestamp: int
    ):
        self.unit_id = unit_id
        self.unit_name = unit_name
        self.unit_symbol = symbol_name
        self.timestamp = timestamp

    @staticmethod
    def from_entity(data: dict):
        return JournalUnit(
            unit_id=data.get('unit_id'),
            unit_name=data.get('unit_name'),
            symbol_name=data.get('symbol_name'),
            timestamp=data.get('timestamp')
        )


class JournalCategory(Serializable):
    def __init__(
        self,
        category_id: str,
        category_name: str,
        symbol_name: str,
        timestamp: int
    ):
        self.category_id = category_id
        self.category_name = category_name
        self.symbol_name = symbol_name
        self.timestamp = timestamp

    @staticmethod
    def from_entity(data: dict):
        return JournalCategory(
            category_id=data.get('category_id'),
            category_name=data.get('category_name'),
            symbol_name=data.get('symbol_name'),
            timestamp=data.get('timestamp')
        )
