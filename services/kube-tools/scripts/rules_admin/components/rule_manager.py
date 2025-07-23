# MongoDB Configuration
from datetime import datetime
import uuid
from pymongo import MongoClient


DEFAULT_MONGO_URI = 'mongodb://localhost:27017/?directConnection=true'
DEFAULT_DATABASE_NAME = 'Google'
DEFAULT_COLLECTION_NAME = 'EmailRule'


class RuleManager:
    """Handles CRUD operations for rules"""

    def __init__(self, mongo_uri: str = DEFAULT_MONGO_URI, database_name: str = DEFAULT_DATABASE_NAME, collection_name: str = DEFAULT_COLLECTION_NAME):
        self.mongo_uri = mongo_uri
        self.database_name = database_name
        self.collection_name = collection_name
        self.client = None
        self.db = None
        self.rules_collection = None
        self._connect()

    def _connect(self):
        print(f"🔗 Connecting to MongoDB at {self.mongo_uri}...")
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client[self.database_name]
            self.rules_collection = self.db[self.collection_name]
            self.client.admin.command('ping')
            print(f"✅ Connected to MongoDB at {self.mongo_uri}")
        except Exception as e:
            print(f"❌ Failed to connect to MongoDB: {e}")
            raise

    def get_all_rules(self):
        """Get all rules from MongoDB"""
        return list(self.rules_collection.find().sort('created_date', -1))

    def get_rule_by_id(self, rule_id: str):
        """Get a specific rule by rule_id"""
        return self.rules_collection.find_one({'rule_id': rule_id})

    def create_rule(self, rule_data: dict) -> str:
        """Create a new rule"""
        rule_data['rule_id'] = str(uuid.uuid4())
        rule_data['created_date'] = datetime.utcnow()
        rule_data['modified_date'] = datetime.utcnow()
        rule_data['count_processed'] = 0

        self.rules_collection.insert_one(rule_data)
        return rule_data['rule_id']

    def update_rule(self, rule_id: str, rule_data: dict) -> bool:
        """Update an existing rule"""
        rule_data['modified_date'] = datetime.utcnow()
        rule_data.pop('_id', None)
        rule_data.pop('rule_id', None)
        rule_data.pop('created_date', None)

        result = self.rules_collection.update_one(
            {'rule_id': rule_id},
            {'$set': rule_data}
        )
        return result.modified_count > 0

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule"""
        result = self.rules_collection.delete_one({'rule_id': rule_id})
        return result.deleted_count > 0
