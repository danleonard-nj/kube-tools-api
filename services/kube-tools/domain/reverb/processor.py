
from datetime import datetime
import uuid
from framework.serialization import Serializable
from domain.reverb.listings import ReverbListing
from domain.reverb.product import ReverbProduct


class ListingProcessStatusType:
    Error = 'error'
    ReadyToProcess = 'ready-to-process'
    ReadyToCompare = 'ready-to-compare'
    ReadyForOffer = 'ready-for-offer'
    OutOfRange = 'out-of-range'
    PendingOffer = 'pending-offer'
    DeclinedOffer = 'declined-offer'
    NoComparisonTransactions = 'no-comparison-transactions'
    ReadyForShippingCalculation = 'ready-for-shipping-calculation'
    Closed = 'closed'


class ListingProcessStatus:
    def __init__(self, code, message):
        self.code = code
        self.message = message


class ProcessorListing(Serializable):
    def __init__(
        self,
        listing_id,
        listing_bk,
        product_id,
        condition_id,
        price,
        shipping,
        total,
        created_date,
        listing_url,
        carrier_calculated=None,
        offer_url=None,
        status_code=None,
        status_message=None
    ):
        self.listing_id = listing_id
        self.product_id = product_id
        self.condition_id = condition_id
        self.listing_bk = listing_bk
        self.listing_url = listing_url
        self.offer_url = offer_url
        self.price = price
        self.shipping = shipping
        self.carrier_calculated = carrier_calculated
        self.total = total
        self.status_code = status_code
        self.status_message = status_message
        self.created_date = created_date

    def get_selector(self):
        return {
            'listing_id': self.listing_id
        }

    def update_status(self, status: ListingProcessStatus):
        self.status_code = status.code
        self.status_message = status.message

    @staticmethod
    def from_entity(data):
        return ProcessorListing(
            listing_id=data.get('listing_id'),
            listing_bk=data.get('listing_bk'),
            product_id=data.get('product_id'),
            condition_id=data.get('condition_id'),
            price=data.get('price'),
            shipping=data.get('shipping'),
            total=data.get('total'),
            created_date=data.get('created_date'),
            listing_url=data.get('listing_url'),
            carrier_calculated=data.get('carrier_calculated'),
            offer_url=data.get('offer_url'),
            status_code=data.get('status_code'),
            status_message=data.get('status_message')
        )

    @staticmethod
    def from_listing(
        listing: ReverbListing,
        product: ReverbProduct,
        condition_id: str
    ):
        if (listing.shipping.amount_cents or 0) == 0:
            shipping = 0
        else:
            shipping = listing.shipping.amount_cents / 100

        price = listing.buyer_price.amount_cents / 100
        offer_url = (listing.offer_link or dict()).get('href')

        return ProcessorListing(
            listing_id=str(uuid.uuid4()),
            listing_bk=listing.bk,
            product_id=product.product_id,
            condition_id=condition_id,
            price=price,
            shipping=shipping,
            total=price + shipping,
            created_date=datetime.now(),
            listing_url=listing.listing_url,
            carrier_calculated=listing.carrier_calculated,
            offer_url=offer_url
        )
