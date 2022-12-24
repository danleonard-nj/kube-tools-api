from framework.serialization import Serializable


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
