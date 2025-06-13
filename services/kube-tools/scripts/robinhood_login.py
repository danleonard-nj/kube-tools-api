import robin_stocks.robinhood as r

username = ''
password = input('Password: ')

r.login(
    username=username,
    password=password
)
