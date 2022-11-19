

from domain.reverb.common import ReverbPrice, generate_key
from framework.serialization import Serializable


def first(items, func):
    for item in items:
        if func(item) is True:
            return item


class ReverbShippingCode:
    Domestic = 'US_CON'


class ReverbListingCategory(Serializable):
    def __init__(self, data):
        self.bk = data.get('uuid')
        self.name = data.get('full_name')


class ReverbListingShipping(Serializable):
    def __init__(self, data):
        rates = data.get('rates')
        self.domestic = self.get_domestic_price(
            rates=rates)

    def get_domestic_price(self, rates):
        domestic_code = ReverbShippingCode.Domestic
        return first(
            rates, lambda x: x.get('region_code') == domestic_code)


class ReverbListing(Serializable):
    def __init__(self, data):
        self.bk = data.get('id')
        self.make = data.get('make')
        self.model = data.get('model')
        self.finish = data.get('finish')
        self.year = data.get('year')
        self.title = data.get('title')
        self.offers_enabled = data.get('offers_enabled')
        self.published_data = data.get('published_at')
        self.condition_bk = data.get('condition').get('slug')
        self.condition_name = data.get('condition').get('display_name')
        self.listing_url = self.get_listing_url(
            data=data)

        self.local_shipping = self.is_local_shipping(
            data=data)
        self.shipping = self.get_shipping_rate(
            data=data)
        self.carrier_calculated = self.is_carrier_calculated_shipping(
            data=data)

        self.state = data.get(
            'state', dict()).get('slug')
        self.offer_link = data.get(
            '_links', dict()).get('make_offer')

        self.categories = self.get_categories(
            data=data)

        self.price = ReverbPrice.from_response(
            data=data.get('price'))
        self.buyer_price = ReverbPrice.from_response(
            data=data.get('buyer_price'))

    def get_listing_url(self, data):
        return data.get('_links', dict()).get(
            'web', dict()).get('href')

    def get_categories(self, data):
        categories = data.get('categories')

        return [
            ReverbListingCategory(data=category)
            for category in categories
        ]

    def is_local_shipping(self, data):
        rates = data.get('shipping', dict()).get('rates')

        for rate in rates:
            if rate.get('region_code') == 'US_CON':
                return True
        return False

    def __get_us_shipping_rate(self, data):
        rates = data.get('shipping', dict()).get(
            'rates', list())

        for rate in rates:
            if rate.get('region_code') == 'US_CON':
                rate_price = rate.get('rate')

                if rate_price is not None:
                    return rate_price

        return dict()

    def get_shipping_rate(self, data):
        rates = self.__get_us_shipping_rate(data)

        if rates is not None:
            return ReverbPrice.from_response(
                data=rates)

        return ReverbPrice(
            amount=0,
            amount_cents=0,
            currency=None
        )

    def is_carrier_calculated_shipping(self, data):
        return self.__get_us_shipping_rate(data).get(
            'carrier_calculated', False)

    def get_product_key(self):
        return generate_key(data=[
            self.make,
            self.model,
            self.year,
            self.finish
        ])


class ReverbListingDetail:
    def __init__(
        self,
        comparison_shopping,
        local_pickup_only
    ):
        self.comparison_shopping = comparison_shopping
        self.local_pickup_only = local_pickup_only

    @staticmethod
    def from_response(data):
        return ReverbListingDetail(
            comparison_shopping=data.get(
                '_links', dict()).get('comparison_shopping'),
            local_pickup_only=data.get('local_pickup_only')
        )


class ReverbListingDetail:
    def __init__(
        self,
        comparison_shopping,
        local_pickup_only
    ):
        self.comparison_shopping = comparison_shopping
        self.local_pickup_only = local_pickup_only

    @staticmethod
    def from_response(data):
        return ReverbListingDetail(
            comparison_shopping=data.get(
                '_links', dict()).get('comparison_shopping'),
            local_pickup_only=data.get('local_pickup_only')
        )
