from typing import List, Optional, Dict
from datetime import datetime, timedelta
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase
from domain.google import (
    EmailRuleExecutionLog,
    EmailProcessingLog,
    EmailRuleErrorLog,
    EmailRulePerformanceLog,
    EmailRuleLogType
)


class GoogleEmailLogRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Google,
            collection=MongoCollection.EmailServiceLog)

    async def log_rule_execution(self, log: EmailRuleExecutionLog) -> str:
        """Log a rule execution event."""
        result = await self.collection.insert_one(log.model_dump())
        return str(result.inserted_id)

    async def log_email_processing(self, log: EmailProcessingLog) -> str:
        """Log an individual email processing event."""
        result = await self.collection.insert_one(log.model_dump())
        return str(result.inserted_id)

    async def log_error(self, log: EmailRuleErrorLog) -> str:
        """Log an error event."""
        result = await self.collection.insert_one(log.model_dump())
        return str(result.inserted_id)

    async def log_performance_metric(self, log: EmailRulePerformanceLog) -> str:
        """Log a performance metric."""
        result = await self.collection.insert_one(log.model_dump())
        return str(result.inserted_id)

    async def update_rule_execution_status(
        self,
        execution_id: str,
        status: str,
        end_time: datetime = None,
        emails_processed: int = None,
        emails_failed: int = None,
        error_message: str = None
    ) -> bool:
        """Update the status of a rule execution."""
        update_data = {'status': status}

        if end_time:
            update_data['end_time'] = end_time
            # Calculate duration if start_time exists
            existing_log = await self.collection.find_one({
                'execution_id': execution_id,
                'log_type': EmailRuleLogType.RULE_EXECUTION
            })
            if existing_log and existing_log.get('start_time'):
                start_time = existing_log['start_time']
                if isinstance(start_time, datetime):
                    duration_ms = int((end_time - start_time).total_seconds() * 1000)
                    update_data['execution_duration_ms'] = duration_ms

        if emails_processed is not None:
            update_data['emails_processed'] = emails_processed

        if emails_failed is not None:
            update_data['emails_failed'] = emails_failed

        if error_message:
            update_data['error_message'] = error_message

        result = await self.collection.update_one(
            {
                'execution_id': execution_id,
                'log_type': EmailRuleLogType.RULE_EXECUTION
            },
            {'$set': update_data}
        )
        return result.modified_count > 0

    async def get_rule_execution_logs(
        self,
        rule_id: str = None,
        start_date: datetime = None,
        end_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get rule execution logs with optional filtering."""
        query = {'log_type': EmailRuleLogType.RULE_EXECUTION}

        if rule_id:
            query['rule_id'] = rule_id

        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query['$gte'] = start_date
            if end_date:
                date_query['$lte'] = end_date
            query['created_date'] = date_query

        cursor = self.collection.find(query).sort('created_date', -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_email_processing_logs(
        self,
        execution_id: str = None,
        rule_id: str = None,
        email_id: str = None,
        status: str = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get email processing logs with optional filtering."""
        query = {'log_type': EmailRuleLogType.EMAIL_PROCESSING}

        if execution_id:
            query['execution_id'] = execution_id
        if rule_id:
            query['rule_id'] = rule_id
        if email_id:
            query['email_id'] = email_id
        if status:
            query['status'] = status

        cursor = self.collection.find(query).sort('created_date', -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_error_logs(
        self,
        execution_id: str = None,
        rule_id: str = None,
        error_type: str = None,
        start_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get error logs with optional filtering."""
        query = {'log_type': EmailRuleLogType.ERROR}

        if execution_id:
            query['execution_id'] = execution_id
        if rule_id:
            query['rule_id'] = rule_id
        if error_type:
            query['error_type'] = error_type
        if start_date:
            query['created_date'] = {'$gte': start_date}

        cursor = self.collection.find(query).sort('created_date', -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_performance_metrics(
        self,
        execution_id: str = None,
        rule_id: str = None,
        metric_name: str = None,
        start_date: datetime = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get performance metrics with optional filtering."""
        query = {'log_type': EmailRuleLogType.PERFORMANCE_METRIC}

        if execution_id:
            query['execution_id'] = execution_id
        if rule_id:
            query['rule_id'] = rule_id
        if metric_name:
            query['metric_name'] = metric_name
        if start_date:
            query['created_date'] = {'$gte': start_date}

        cursor = self.collection.find(query).sort('created_date', -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_rule_execution_summary(
        self,
        rule_id: str,
        days: int = 30
    ) -> Dict:
        """Get a summary of rule executions for the last N days."""
        start_date = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {
                '$match': {
                    'log_type': EmailRuleLogType.RULE_EXECUTION,
                    'rule_id': rule_id,
                    'created_date': {'$gte': start_date}
                }
            },
            {
                '$group': {
                    '_id': None,
                    'total_executions': {'$sum': 1},
                    'successful_executions': {
                        '$sum': {'$cond': [{'$eq': ['$status', 'completed']}, 1, 0]}
                    },
                    'failed_executions': {
                        '$sum': {'$cond': [{'$eq': ['$status', 'failed']}, 1, 0]}
                    },
                    'total_emails_processed': {'$sum': '$emails_processed'},
                    'total_emails_failed': {'$sum': '$emails_failed'},
                    'avg_execution_duration_ms': {'$avg': '$execution_duration_ms'},
                    'last_execution': {'$max': '$created_date'}
                }
            }
        ]

        result = await self.collection.aggregate(pipeline).to_list(length=1)
        return result[0] if result else {}

    async def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """Clean up logs older than the specified number of days."""
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        result = await self.collection.delete_many({
            'created_date': {'$lt': cutoff_date}
        })
        return result.deleted_count
