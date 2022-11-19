

from datetime import datetime
import uuid

from domain.reverb.common import generate_key
from domain.reverb.listings import ReverbListing
from framework.serialization import Serializable


class ReverbProductCondition(Serializable):
    def __init__(
        self,
        condition_id,
        condition_name,
        condition_bk
    ):
        self.condition_id = condition_id
        self.condition_name = condition_name
        self.condition_bk = condition_bk

    @staticmethod
    def create_condition(condition_name, conditiion_bk):
        return ReverbProductCondition(
            condition_id=str(uuid.uuid4()),
            condition_name=condition_name,
            condition_bk=conditiion_bk
        )

    @ staticmethod
    def from_entity(data):
        return ReverbProductCondition(
            condition_id=data.get('condition_id'),
            condition_name=data.get('condition_name'),
            condition_bk=data.get('condition_bk')
        )


class ReverbProductMake(Serializable):
    def __init__(
        self,
        product_make,
        product_make_id,
        created_date
    ):
        self.product_make_id = product_make_id
        self.product_make = product_make
        self.created_date = created_date

    def to_entity(self):
        return self.to_dict()

    @staticmethod
    def from_entity(data):
        return ReverbProductMake(
            product_make=data.get('product_make'),
            product_make_id=data.get('product_make_id'),
            created_date=data.get('created_date')
        )

    @staticmethod
    def create_product_make(product_make, product_make_id=None):
        return ReverbProductMake(
            product_make_id=product_make_id or str(uuid.uuid4()),
            product_make=product_make,
            created_date=datetime.now()
        )


class ReverbProduct(Serializable):
    def __init__(
        self,
        product_id,
        product_make_id,
        product_model,
        product_year,
        product_finish,
        product_categories,
        product_bk=None,
        created_date=None,
        product_key=None,
        sync_date=None
    ):
        self.product_id = product_id
        self.product_bk = product_bk
        self.product_make_id = product_make_id
        self.product_model = product_model
        self.product_year = product_year
        self.product_finish = product_finish
        self.product_categories = product_categories

        self.sync_date = sync_date or datetime.now()
        self.created_date = created_date or datetime.now()
        self.product_key = product_key or self.get_product_key()

    def get_selector(self):
        return {
            'product_id': self.product_id
        }

    def get_product_key(self):
        return generate_key(data=[
            self.make,
            self.model,
            self.year,
            self.finish
        ])

    def get_hours_since_last_sync(self):
        now = datetime.now()
        delta = now - self.sync_date

        return delta.seconds / (60 * 60)

    @staticmethod
    def from_entity(data):
        return ReverbProduct(
            product_id=data.get('product_id'),
            product_bk=data.get('product_bk'),
            product_key=data.get('product_key'),
            product_make_id=data.get('product_make_id'),
            product_model=data.get('product_model'),
            product_year=data.get('product_year'),
            product_finish=data.get('product_finish'),
            product_categories=data.get('product_categories'),
            created_date=data.get('created_date')
        )

    @staticmethod
    def from_response(data, product_make_id, product_id=None):
        links = data.get('links', dict())
        listing_url = links.get('web')

        return ReverbProduct(
            product_id=product_id or str(uuid.uuid4()),
            product_bk=data.get('id'),
            product_make_id=product_make_id,
            product_model=data.get('model'),
            product_year=data.get('year'),
            product_finish=data.get('finish'),
            product_categories=data.get('categories'),
            listing_url=listing_url
        )

    @staticmethod
    def from_listing(
        listing: ReverbListing,
        product_id=None,
        product_make_id=None,
        product_bk=None
    ):
        return ReverbProduct(
            product_key=listing.get_product_key(),
            product_id=product_id or str(uuid.uuid4()),
            product_make_id=product_make_id,
            product_model=listing.model,
            product_year=listing.year,
            product_finish=listing.finish,
            product_categories=listing.categories,
            product_bk=product_bk,
            created_date=datetime.now()
        )

    def to_dict(self):
        return super().to_dict() | {
            'product_categories': [
                x.to_dict() for x in
                self.product_categories
            ]
        }
