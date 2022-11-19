import uuid
from datetime import datetime

from framework.serialization import Serializable

from domain.reverb.common import ReverbPrice, generate_key


class ReverbComparison:
    def __init__(
        self,
        comparison_bk,
        product_bk,
        category_bk,
        category_slug,
        product_name
    ):
        self.bk = comparison_bk
        self.product_bk = product_bk
        self.product_name = product_name
        self.category_bk = category_bk
        self.category_slug = category_slug

    @staticmethod
    def from_response(data):
        return ReverbComparison(
            comparison_bk=data.get('id'),
            product_bk=data.get('slug'),
            category_bk=data.get('root_category_uuid'),
            category_slug=data.get('root_category_slug'),
            product_name=data.get('title'))


class ReverbComparisonTransaction(Serializable):
    def __init__(
        self,
        transaction_id,
        transaction_date,
        product_id,
        product_condition_id,
        transaction_source,
        order_bk,
        starting_price: ReverbPrice,
        final_price: ReverbPrice,
        sync_date
    ):
        self.transaction_id = transaction_id
        self.transaction_date = transaction_date
        self.product_id = product_id
        self.product_condition_id = product_condition_id
        self.transaction_source = transaction_source
        self.order_bk = order_bk
        self.starting_price = starting_price
        self.final_price = final_price
        self.sync_date = sync_date

    def get_key(self):
        return generate_key(data=self.order_bk)

    def to_entity(self):
        return self.to_dict() | {
            'final_price': self.final_price.to_dict(),
            'starting_price': self.starting_price.to_dict()
        }

    def to_dict(self):
        return super().to_dict() | {
            'starting_price': self.starting_price.to_dict(),
            'final_price': self.final_price.to_dict()
        }

    @staticmethod
    def from_entity(data):
        return ReverbComparisonTransaction(
            transaction_id=data.get('transaction_id'),
            transaction_date=data.get('transaction_date'),
            product_id=data.get('product_id'),
            product_condition_id=data.get('product_condition_id'),
            transaction_source=data.get('transaction_source'),
            order_bk=data.get('order_bk'),
            sync_date=datetime.now(),
            starting_price=ReverbPrice.from_entity(
                data=data.get('starting_price')),
            final_price=ReverbPrice.from_entity(
                data=data.get('final_price'))
        )

    @staticmethod
    def from_response(
        data,
        product_id,
        product_condition_id,
        transaction_id=None
    ):
        return ReverbComparisonTransaction(
            transaction_id=transaction_id or str(uuid.uuid4()),
            transaction_date=data.get('date'),
            transaction_source=data.get('transaction_source'),
            product_id=product_id,
            product_condition_id=product_condition_id,
            order_bk=data.get('order_id'),
            starting_price=ReverbPrice.from_response(
                data=data.get('price_ask')),
            final_price=ReverbPrice.from_response(
                data=data.get('price_final')),
            sync_date=datetime.now()
        )
