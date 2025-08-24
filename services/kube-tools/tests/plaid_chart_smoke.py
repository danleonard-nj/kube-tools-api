from services.plaid_usage_service import PlaidUsageService

# Create object without running __init__ (we only need the method)
svc = PlaidUsageService.__new__(PlaidUsageService)

plaid_data = {
    'series': [
        {
            'metricName': 'balance-request',
            'start': '2025-07-01',
            'end': '2025-08-24',
            'series': [
                131,134,180,184,186,188,191,3,6,34,45,48,50,52,63,66,68,71,74,77,93,167,178,189,208,226,292,359,368,376
            ]
        }
    ]
}

html = svc.generate_plaid_usage_email(plaid_data, recipient_name='Smoke Test')
with open('plaid_smoke_output.html', 'w', encoding='utf-8') as f:
    f.write(html)
print('WROTE: plaid_smoke_output.html')
