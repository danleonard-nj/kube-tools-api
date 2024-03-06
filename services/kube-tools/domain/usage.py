

REPORT_EMAIL_SUBJECT = 'Azure Usage'
REPORT_SORT_KEY = 'Cost'
REPORT_COLUMNS = [
    'Cost',
    'CostUSD',
    'Currency',
    'Product'
]

REPORT_GROUP_KEYS = [
    'Product',
    'Currency'
]


def format_date(date):
    return date.strftime('%Y-%m-%d')


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
