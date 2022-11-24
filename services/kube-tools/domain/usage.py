from framework.serialization import Serializable


class UsageReport(Serializable):
    @property
    def product_date(
        self
    ) -> str:

        return f'{self.product}-{self.date}'

    def __init__(
        self,
        data
    ):
        self.date = data.get('date')
        self.meter_category = data.get('meterCategory')
        self.meter_name = data.get('meterName')
        self.billing_profile_name = data.get('billingProfileName')
        self.charge_type = data.get('chargeType')
        self.consumed_service = data.get('consumedService')
        self.cost_in_usd = data.get('costInUSD')
        self.effective_price = data.get('effectivePrice')
        self.meter_category = data.get('meterCategory')
        self.meter_name = data.get('meterName')
        self.meter_region = data.get('meterRegion')
        self.meter_sub_category = data.get('meterSubCategory')
        self.pay_g_price = data.get('payGPrice')
        self.payg_cost_in_usd = data.get('paygCostInUSD')
        self.pricing_currency_code = data.get('pricingCurrencyCode')
        self.product = data.get('product')
        self.quantity = data.get('quantity')
        self.resource_group = data.get('resourceGroup')
        self.resource_location = data.get('resourceLocationNormalized')
        self.unit_of_measure = data.get('unitOfMeasure')
        self.unit_price = data.get('unitPrice')


class UsageArgs:
    def __init__(
        self,
        request
    ):
        self.range_key = request.args.get('range_key')


class ReportDateRange:
    YearToDate = 'ytd'
    MonthToDate = 'mtd'
    LastNDays = 'last'
