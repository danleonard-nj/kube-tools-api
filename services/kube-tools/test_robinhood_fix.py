import robin_stocks.robinhood as r

print('Testing robin_stocks orders methods:')
print('get_all_stock_orders method exists:', hasattr(r.orders, 'get_all_stock_orders'))
print('get_all_orders method exists:', hasattr(r.orders, 'get_all_orders'))

# Test a simple portfolio data retrieval (without login)
try:
    # This should fail but test if the method exists
    result = r.orders.get_all_stock_orders
    print('get_all_stock_orders method callable:', callable(result))
except Exception as e:
    print('Error testing method:', str(e))
