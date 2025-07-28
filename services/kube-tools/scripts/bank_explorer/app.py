from flask import Flask, render_template_string, request, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
import os
from bson import ObjectId
import json

app = Flask(__name__)

# MongoDB Configuration
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/?directConnection=true')
client = MongoClient(MONGO_URI)
db = client['plaid']

# Collections
accounts_collection = db.accounts
transactions_collection = db.transactions
sync_states_collection = db.sync

# Helper functions


def format_currency(amount):
    """Format amount as currency"""
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def format_date(date_obj):
    """Format date for display"""
    if date_obj:
        return date_obj.strftime('%Y-%m-%d %H:%M:%S')
    return 'N/A'


def get_account_summary():
    """Get summary of all accounts"""
    accounts = list(accounts_collection.find())
    total_balance = sum(acc.get('balances', {}).get('current', 0) for acc in accounts)
    return {
        'total_accounts': len(accounts),
        'total_balance': total_balance,
        'accounts': accounts
    }


def get_sync_status():
    """Get sync status information"""
    sync_states = list(sync_states_collection.find())
    total_transactions = transactions_collection.count_documents({})

    # Get latest sync times
    latest_syncs = {}
    for state in sync_states:
        token = state.get('access_token')
        if token:
            latest_syncs[token] = state.get('last_sync')

    return {
        'sync_states': sync_states,
        'total_transactions': total_transactions,
        'latest_syncs': latest_syncs
    }

# Routes


@app.route('/')
def dashboard():
    """Main dashboard"""
    summary = get_account_summary()
    sync_status = get_sync_status()

    # Recent transactions
    recent_transactions = list(transactions_collection.find().sort('date', -1).limit(10))

    return render_template_string(DASHBOARD_TEMPLATE,
                                  summary=summary,
                                  sync_status=sync_status,
                                  recent_transactions=recent_transactions,
                                  format_currency=format_currency,
                                  format_date=format_date)


@app.route('/accounts')
def accounts():
    """Accounts list page"""
    accounts_data = list(accounts_collection.find())
    return render_template_string(ACCOUNTS_TEMPLATE,
                                  accounts=accounts_data,
                                  format_currency=format_currency,
                                  format_date=format_date)


@app.route('/account/<account_id>')
def account_detail(account_id):
    """Account detail page with transactions"""
    account = accounts_collection.find_one({'account_id': account_id})
    if not account:
        return "Account not found", 404

    # Get transactions for this account
    page = int(request.args.get('page', 1))
    per_page = 50
    skip = (page - 1) * per_page

    transactions = list(transactions_collection.find({'account_id': account_id})
                        .sort('date', -1)
                        .skip(skip)
                        .limit(per_page))

    total_transactions = transactions_collection.count_documents({'account_id': account_id})
    total_pages = (total_transactions + per_page - 1) // per_page

    return render_template_string(ACCOUNT_DETAIL_TEMPLATE,
                                  account=account,
                                  transactions=transactions,
                                  page=page,
                                  total_pages=total_pages,
                                  total_transactions=total_transactions,
                                  format_currency=format_currency,
                                  format_date=format_date)


@app.route('/transactions')
def transactions():
    """All transactions page"""
    page = int(request.args.get('page', 1))
    per_page = 100
    skip = (page - 1) * per_page

    # Filters
    account_filter = request.args.get('account')
    category_filter = request.args.get('category')
    amount_min = request.args.get('amount_min', type=float)
    amount_max = request.args.get('amount_max', type=float)

    # Build query
    query = {}
    if account_filter:
        query['account_id'] = account_filter
    if category_filter:
        query['category'] = {'$in': [category_filter]}
    if amount_min is not None or amount_max is not None:
        amount_query = {}
        if amount_min is not None:
            amount_query['$gte'] = amount_min
        if amount_max is not None:
            amount_query['$lte'] = amount_max
        query['amount'] = amount_query

    transactions_data = list(transactions_collection.find(query)
                             .sort('date', -1)
                             .skip(skip)
                             .limit(per_page))

    total_transactions = transactions_collection.count_documents(query)
    total_pages = (total_transactions + per_page - 1) // per_page

    # Get unique accounts and categories for filters
    unique_accounts = accounts_collection.distinct('account_id')
    unique_categories = transactions_collection.distinct('category')
    unique_categories = [cat for sublist in unique_categories for cat in (sublist if isinstance(sublist, list) else [sublist])]
    unique_categories = list(set(unique_categories))

    return render_template_string(TRANSACTIONS_TEMPLATE,
                                  transactions=transactions_data,
                                  page=page,
                                  total_pages=total_pages,
                                  total_transactions=total_transactions,
                                  unique_accounts=unique_accounts,
                                  unique_categories=unique_categories,
                                  current_filters={
                                      'account': account_filter,
                                      'category': category_filter,
                                      'amount_min': amount_min,
                                      'amount_max': amount_max
                                  },
                                  format_currency=format_currency,
                                  format_date=format_date)


@app.route('/diagnostics')
def diagnostics():
    """System diagnostics page"""
    sync_status = get_sync_status()

    # Database statistics
    db_stats = {
        'accounts_count': accounts_collection.count_documents({}),
        'transactions_count': transactions_collection.count_documents({}),
        'sync_states_count': sync_states_collection.count_documents({})
    }

    # Recent activity
    recent_updates = list(transactions_collection.find()
                          .sort('updated_at', -1)
                          .limit(20))

    return render_template_string(DIAGNOSTICS_TEMPLATE,
                                  sync_status=sync_status,
                                  db_stats=db_stats,
                                  recent_updates=recent_updates,
                                  format_currency=format_currency,
                                  format_date=format_date)


@app.route('/api/account/<account_id>/transactions')
def api_account_transactions(account_id):
    """API endpoint for account transactions"""
    transactions = list(transactions_collection.find({'account_id': account_id})
                        .sort('date', -1)
                        .limit(100))

    # Convert ObjectId to string for JSON serialization
    for tx in transactions:
        tx['_id'] = str(tx['_id'])
        if 'date' in tx and tx['date']:
            tx['date'] = tx['date'].isoformat()
        if 'updated_at' in tx and tx['updated_at']:
            tx['updated_at'] = tx['updated_at'].isoformat()

    return jsonify(transactions)


# Templates
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Bank Explorer{% endblock %}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f8f9fa;
        }
        
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 1rem 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .nav-container {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0 2rem;
        }
        
        .nav-brand {
            color: white;
            font-size: 1.5rem;
            font-weight: bold;
            text-decoration: none;
        }
        
        .nav-links {
            display: flex;
            gap: 2rem;
        }
        
        .nav-links a {
            color: white;
            text-decoration: none;
            font-weight: 500;
            transition: opacity 0.3s;
        }
        
        .nav-links a:hover {
            opacity: 0.8;
        }
        
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 2rem;
        }
        
        .card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            padding: 1.5rem;
            margin-bottom: 2rem;
        }
        
        .card-header {
            border-bottom: 1px solid #eee;
            padding-bottom: 1rem;
            margin-bottom: 1rem;
        }
        
        .card-title {
            font-size: 1.5rem;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        
        .stat-card {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        
        .stat-value {
            font-size: 2rem;
            font-weight: bold;
            color: #2c3e50;
        }
        
        .stat-label {
            color: #666;
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }
        
        .table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        
        .table th,
        .table td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        
        .table th {
            background-color: #f8f9fa;
            font-weight: 600;
            color: #2c3e50;
        }
        
        .table tbody tr:hover {
            background-color: #f8f9fa;
        }
        
        .btn {
            display: inline-block;
            padding: 0.5rem 1rem;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9rem;
            transition: background 0.3s;
        }
        
        .btn:hover {
            background: #5a67d8;
        }
        
        .btn-sm {
            padding: 0.25rem 0.5rem;
            font-size: 0.8rem;
        }
        
        .pagination {
            display: flex;
            justify-content: center;
            gap: 0.5rem;
            margin-top: 2rem;
        }
        
        .pagination a {
            padding: 0.5rem 1rem;
            background: white;
            border: 1px solid #ddd;
            color: #667eea;
            text-decoration: none;
            border-radius: 4px;
        }
        
        .pagination a:hover {
            background: #f8f9fa;
        }
        
        .pagination .current {
            background: #667eea;
            color: white;
        }
        
        .filters {
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .filter-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            align-items: end;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
        }
        
        .form-group label {
            margin-bottom: 0.5rem;
            font-weight: 500;
            color: #2c3e50;
        }
        
        .form-group input,
        .form-group select {
            padding: 0.5rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 0.9rem;
        }
        
        .amount-positive {
            color: #28a745;
        }
        
        .amount-negative {
            color: #dc3545;
        }
        
        .status-badge {
            padding: 0.25rem 0.5rem;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: 500;
        }
        
        .status-success {
            background: #d4edda;
            color: #155724;
        }
        
        .status-warning {
            background: #fff3cd;
            color: #856404;
        }
        
        .status-danger {
            background: #f8d7da;
            color: #721c24;
        }
        
        @media (max-width: 768px) {
            .nav-container {
                flex-direction: column;
                gap: 1rem;
            }
            
            .nav-links {
                gap: 1rem;
            }
            
            .container {
                padding: 0 1rem;
            }
            
            .table-responsive {
                overflow-x: auto;
            }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <div class="nav-container">
            <a href="/" class="nav-brand">🏦 Bank Explorer</a>
            <div class="nav-links">
                <a href="/">Dashboard</a>
                <a href="/accounts">Accounts</a>
                <a href="/transactions">Transactions</a>
                <a href="/diagnostics">Diagnostics</a>
            </div>
        </div>
    </nav>
    
    <div class="container">
        {% block content %}{% endblock %}
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-value">{{ summary.total_accounts }}</div>
        <div class="stat-label">Total Accounts</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ format_currency(summary.total_balance) }}</div>
        <div class="stat-label">Total Balance</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ sync_status.total_transactions }}</div>
        <div class="stat-label">Total Transactions</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ sync_status.sync_states|length }}</div>
        <div class="stat-label">Active Connections</div>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">Recent Transactions</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th>Amount</th>
                    <th>Category</th>
                </tr>
            </thead>
            <tbody>
                {% for tx in recent_transactions %}
                <tr>
                    <td>{{ format_date(tx.date) }}</td>
                    <td>{{ tx.name }}</td>
                    <td class="{% if tx.amount > 0 %}amount-positive{% else %}amount-negative{% endif %}">
                        {{ format_currency(tx.amount) }}
                    </td>
                    <td>
                        {% if tx.category %}
                            {% for cat in tx.category %}
                                <span class="status-badge status-success">{{ cat }}</span>
                            {% endfor %}
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">Accounts Overview</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Account</th>
                    <th>Type</th>
                    <th>Balance</th>
                    <th>Last Updated</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for account in summary.accounts %}
                <tr>
                    <td>
                        <strong>{{ account.name }}</strong><br>
                        <small>****{{ account.mask }}</small>
                    </td>
                    <td>{{ account.type|title }} - {{ account.subtype|title }}</td>
                    <td>{{ format_currency(account.balances.current) }}</td>
                    <td>{{ format_date(account.updated_at) }}</td>
                    <td>
                        <a href="/account/{{ account.account_id }}" class="btn btn-sm">View Details</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
""")

ACCOUNTS_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="card">
    <div class="card-header">
        <h2 class="card-title">All Accounts</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Account Name</th>
                    <th>Official Name</th>
                    <th>Type</th>
                    <th>Available Balance</th>
                    <th>Current Balance</th>
                    <th>Mask</th>
                    <th>Last Updated</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for account in accounts %}
                <tr>
                    <td>{{ account.name }}</td>
                    <td>{{ account.official_name }}</td>
                    <td>
                        <span class="status-badge status-success">{{ account.type|title }}</span>
                        <span class="status-badge status-warning">{{ account.subtype|title }}</span>
                    </td>
                    <td>{{ format_currency(account.balances.available) }}</td>
                    <td>{{ format_currency(account.balances.current) }}</td>
                    <td>****{{ account.mask }}</td>
                    <td>{{ format_date(account.updated_at) }}</td>
                    <td>
                        <a href="/account/{{ account.account_id }}" class="btn btn-sm">View Transactions</a>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
""")

ACCOUNT_DETAIL_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="card">
    <div class="card-header">
        <h2 class="card-title">{{ account.name }} (****{{ account.mask }})</h2>
    </div>
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-value">{{ format_currency(account.balances.available) }}</div>
            <div class="stat-label">Available Balance</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ format_currency(account.balances.current) }}</div>
            <div class="stat-label">Current Balance</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ account.balances.iso_currency_code }}</div>
            <div class="stat-label">Currency</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ total_transactions }}</div>
            <div class="stat-label">Total Transactions</div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">Transactions</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th>Amount</th>
                    <th>Category</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {% for tx in transactions %}
                <tr>
                    <td>{{ format_date(tx.date) }}</td>
                    <td>{{ tx.name }}</td>
                    <td class="{% if tx.amount > 0 %}amount-positive{% else %}amount-negative{% endif %}">
                        {{ format_currency(tx.amount) }}
                    </td>
                    <td>
                        {% if tx.category %}
                            {% for cat in tx.category %}
                                <span class="status-badge status-success">{{ cat }}</span>
                            {% endfor %}
                        {% endif %}
                    </td>
                    <td>{{ format_date(tx.updated_at) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    
    {% if total_pages > 1 %}
    <div class="pagination">
        {% if page > 1 %}
            <a href="?page={{ page - 1 }}">&laquo; Previous</a>
        {% endif %}
        
        {% for p in range(1, total_pages + 1) %}
            {% if p == page %}
                <a href="?page={{ p }}" class="current">{{ p }}</a>
            {% else %}
                <a href="?page={{ p }}">{{ p }}</a>
            {% endif %}
        {% endfor %}
        
        {% if page < total_pages %}
            <a href="?page={{ page + 1 }}">Next &raquo;</a>
        {% endif %}
    </div>
    {% endif %}
</div>
""")

TRANSACTIONS_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="filters">
    <form method="GET">
        <div class="filter-row">
            <div class="form-group">
                <label>Account</label>
                <select name="account">
                    <option value="">All Accounts</option>
                    {% for account_id in unique_accounts %}
                        <option value="{{ account_id }}" {% if current_filters.account == account_id %}selected{% endif %}>
                            {{ account_id }}
                        </option>
                    {% endfor %}
                </select>
            </div>
            <div class="form-group">
                <label>Category</label>
                <select name="category">
                    <option value="">All Categories</option>
                    {% for category in unique_categories %}
                        <option value="{{ category }}" {% if current_filters.category == category %}selected{% endif %}>
                            {{ category }}
                        </option>
                    {% endfor %}
                </select>
            </div>
            <div class="form-group">
                <label>Min Amount</label>
                <input type="number" name="amount_min" step="0.01" value="{{ current_filters.amount_min or '' }}">
            </div>
            <div class="form-group">
                <label>Max Amount</label>
                <input type="number" name="amount_max" step="0.01" value="{{ current_filters.amount_max or '' }}">
            </div>
            <div class="form-group">
                <button type="submit" class="btn">Filter</button>
            </div>
        </div>
    </form>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">All Transactions ({{ total_transactions }})</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Account</th>
                    <th>Description</th>
                    <th>Amount</th>
                    <th>Category</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {% for tx in transactions %}
                <tr>
                    <td>{{ format_date(tx.date) }}</td>
                    <td>****{{ tx.account_id[-4:] }}</td>
                    <td>{{ tx.name }}</td>
                    <td class="{% if tx.amount > 0 %}amount-positive{% else %}amount-negative{% endif %}">
                        {{ format_currency(tx.amount) }}
                    </td>
                    <td>
                        {% if tx.category %}
                            {% for cat in tx.category %}
                                <span class="status-badge status-success">{{ cat }}</span>
                            {% endfor %}
                        {% endif %}
                    </td>
                    <td>{{ format_date(tx.updated_at) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    
    {% if total_pages > 1 %}
    <div class="pagination">
        {% if page > 1 %}
            <a href="?page={{ page - 1 }}&{{ request.query_string.decode() }}">&laquo; Previous</a>
        {% endif %}
        
        {% for p in range(max(1, page - 2), min(total_pages + 1, page + 3)) %}
            {% if p == page %}
                <a href="?page={{ p }}&{{ request.query_string.decode() }}" class="current">{{ p }}</a>
            {% else %}
                <a href="?page={{ p }}&{{ request.query_string.decode() }}">{{ p }}</a>
            {% endif %}
        {% endfor %}
        
        {% if page < total_pages %}
            <a href="?page={{ page + 1 }}&{{ request.query_string.decode() }}">Next &raquo;</a>
        {% endif %}
    </div>
    {% endif %}
</div>
""")

DIAGNOSTICS_TEMPLATE = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", """
<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-value">{{ db_stats.accounts_count }}</div>
        <div class="stat-label">Accounts in DB</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ db_stats.transactions_count }}</div>
        <div class="stat-label">Transactions in DB</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ db_stats.sync_states_count }}</div>
        <div class="stat-label">Sync States</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ sync_status.sync_states|length }}</div>
        <div class="stat-label">Active Tokens</div>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">Sync Status</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Access Token</th>
                    <th>Last Sync</th>
                    <th>Cursor</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for state in sync_status.sync_states %}
                <tr>
                    <td>{{ state.access_token[:20] }}...</td>
                    <td>{{ format_date(state.last_sync) }}</td>
                    <td>{{ state.cursor[:30] }}{% if state.cursor|length > 30 %}...{% endif %}</td>
                    <td>
                        {% set hours_since = ((loop.index0 * 1000000) / 3600000) if state.last_sync else 999 %}
                        {% if state.last_sync %}
                            {% if hours_since < 1 %}
                                <span class="status-badge status-success">Recent</span>
                            {% elif hours_since < 24 %}
                                <span class="status-badge status-warning">{{ "%.1f"|format(hours_since) }}h ago</span>
                            {% else %}
                                <span class="status-badge status-danger">{{ "%.1f"|format(hours_since/24) }}d ago</span>
                            {% endif %}
                        {% else %}
                            <span class="status-badge status-danger">Never</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <h2 class="card-title">Recent Database Updates</h2>
    </div>
    <div class="table-responsive">
        <table class="table">
            <thead>
                <tr>
                    <th>Transaction</th>
                    <th>Amount</th>
                    <th>Account</th>
                    <th>Updated At</th>
                </tr>
            </thead>
            <tbody>
                {% for update in recent_updates %}
                <tr>
                    <td>{{ update.name[:50] }}{% if update.name|length > 50 %}...{% endif %}</td>
                    <td class="{% if update.amount > 0 %}amount-positive{% else %}amount-negative{% endif %}">
                        {{ format_currency(update.amount) }}
                    </td>
                    <td>****{{ update.account_id[-4:] }}</td>
                    <td>{{ format_date(update.updated_at) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
""")

if __name__ == '__main__':
    app.run(debug=True)
