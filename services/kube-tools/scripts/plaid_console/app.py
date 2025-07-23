from flask import Flask, render_template_string, request, jsonify, redirect, url_for
import os
import json
import logging
from datetime import datetime
import uuid
import requests
from pymongo import MongoClient
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

# Configure detailed logging without emojis for Windows compatibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('plaid_console.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.info("Starting Plaid Admin Console with detailed logging...")

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# MongoDB setup
logger.info("Attempting MongoDB connection...")
try:
    mongo_uri = os.environ.get('MONGODB_URI', 'mongodb://localhost:27017/?directConnection=true')
    logger.info(f"MongoDB URI: {mongo_uri[:20]}..." if len(mongo_uri) > 20 else mongo_uri)
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=500)
    client.server_info()
    db = client.plaid_admin
    logger.info("MongoDB connected successfully")

    # Log collection info
    collections = db.list_collection_names()
    logger.info(f"Available collections: {collections}")

except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    print(f"MongoDB connection failed: {e}")
    print("MongoDB is required for this application")
    exit(1)

# No encryption needed for local utility
logger.info("Skipping encryption setup for local utility")


def store_token(token):
    """Store tokens directly (no encryption for local utility)"""
    logger.debug(f"Storing token (length: {len(token)})")
    return token


def retrieve_token(stored_token):
    """Retrieve tokens directly (no decryption for local utility)"""
    logger.debug(f"Retrieving token (length: {len(stored_token)})")
    return stored_token


def mask_token(token):
    if token and len(token) > 8:
        masked = token[:4] + "***" + token[-4:]
        logger.debug(f"Token masked: {masked}")
        return masked
    return "***"


def get_plaid_base_url(environment='production'):
    """Get the correct Plaid API base URL for the environment"""
    urls = {
        'sandbox': 'https://sandbox.plaid.com',
        'development': 'https://development.plaid.com',
        'production': 'https://production.plaid.com'
    }

    url = urls.get(environment, urls['production'])
    logger.info(f"Using Plaid {environment} environment: {url}")
    return url


def log_action(action, target_item_id=None, details=None):
    """Log actions for audit trail"""
    logger.info(f"Logging action: {action} - target: {target_item_id}")

    audit_entry = {
        'action': action,
        'target_item_id': target_item_id,
        'details': details,
        'timestamp': datetime.utcnow()
    }

    try:
        db.audit_logs.insert_one(audit_entry)
        logger.info(f"Action logged successfully: {action}")
        print(f"Action logged: {action} - {target_item_id}")
    except Exception as e:
        logger.error(f"Failed to log action: {e}")
        # Don't fail the operation if logging fails


# Base template
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Plaid Admin Console</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        // Configure Tailwind for dark mode
        tailwind.config = {
            darkMode: 'class'
        }
    </script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <link href="/static/css/styles.css" rel="stylesheet">
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
</head>
<body class="bg-gray-50 dark:bg-gray-900 min-h-screen transition-colors duration-200">
    <!-- Navigation -->
    <nav class="bg-white dark:bg-gray-800 shadow-sm border-b dark:border-gray-700 transition-colors duration-200">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between h-16">
                <div class="flex items-center">
                    <h1 class="text-xl font-bold text-gray-900 dark:text-white">
                        <i class="fas fa-credit-card text-blue-600 dark:text-blue-400 mr-2"></i>
                        Plaid Admin Console
                    </h1>
                    <div class="ml-10 flex space-x-8">
                        <a href="/" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Dashboard
                        </a>
                        <a href="/accounts" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Accounts
                        </a>
                        <a href="/transactions" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Transactions
                        </a>
                        <a href="/statements" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Statements
                        </a>
                        <a href="/export" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Export
                        </a>
                        <a href="/settings" class="text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-500 whitespace-nowrap py-2 px-1 border-b-2 border-transparent font-medium text-sm">
                            Settings
                        </a>
                    </div>
                </div>
                <!-- Dark Mode Toggle -->
                <div class="flex items-center">
                    <button onclick="toggleDarkMode()" 
                            class="p-2 text-gray-500 dark:text-gray-300 hover:text-gray-700 dark:hover:text-gray-100 focus:outline-none">
                        <i id="theme-icon" class="fas fa-moon"></i>
                    </button>
                </div>
            </div>
        </div>
    </nav>

    <!-- Main content -->
    <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        {CONTENT_PLACEHOLDER}
    </main>

    <!-- Notification System -->
    <div id="notifications" class="fixed top-4 right-4 z-50 space-y-4"></div>

    <script src="/static/js/app.js"></script>
</body>
</html>
"""


@app.route('/')
def dashboard():
    """Main dashboard"""
    logger.info("Loading dashboard...")
    try:
        logger.info("Querying database for dashboard stats...")

        total_items = db.plaid_items.count_documents({})
        logger.info(f"Total items: {total_items}")

        active_items = db.plaid_items.count_documents({'status': 'active'})
        logger.info(f"Active items: {active_items}")

        error_items = db.plaid_items.count_documents({'status': 'error'})
        logger.info(f"Error items: {error_items}")

        recent_events = list(db.webhook_events.find().sort('timestamp', -1).limit(5))
        logger.info(f"Recent events found: {len(recent_events)}")

        # Build events HTML
        events_html = ""
        if recent_events:
            logger.info("Building events HTML...")
            for i, event in enumerate(recent_events[:5]):
                logger.debug(f"Processing event {i+1}: {event.get('event_type', 'Unknown')}")
                events_html += """
                <li class="py-4">
                    <div class="flex items-center space-x-4">
                        <div class="flex-shrink-0">
                            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                {event_type}
                            </span>
                        </div>
                        <div class="flex-1 min-w-0">
                            <p class="text-sm font-medium text-gray-900 truncate">
                                Item: {item_id}
                            </p>
                            <p class="text-sm text-gray-500">
                                {timestamp}
                            </p>
                        </div>
                    </div>
                </li>
                """.format(
                    event_type=event.get("event_type", "Unknown"),
                    item_id=event.get("item_id", "Unknown"),
                    timestamp=str(event.get("timestamp", "Unknown time"))
                )
        else:
            events_html = "<p class='text-gray-500'>No recent webhook events</p>"
            logger.info("No recent webhook events found")

        logger.info("Generating dashboard HTML...")
        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <h1 class="text-3xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
                <p class="mt-2 text-gray-600 dark:text-gray-300">Overview of your Plaid integration</p>
            </div>
            
            <!-- Stats Grid -->
            <div class="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
                <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg transition-colors duration-200">
                    <div class="p-5">
                        <div class="flex items-center">
                            <div class="flex-shrink-0">
                                <i class="fas fa-link text-blue-600 dark:text-blue-400 text-2xl"></i>
                            </div>
                            <div class="ml-5 w-0 flex-1">
                                <dl>
                                    <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Total Items</dt>
                                    <dd class="text-lg font-medium text-gray-900 dark:text-white">{total_items}</dd>
                                </dl>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg transition-colors duration-200">
                    <div class="p-5">
                        <div class="flex items-center">
                            <div class="flex-shrink-0">
                                <i class="fas fa-check-circle text-green-600 dark:text-green-400 text-2xl"></i>
                            </div>
                            <div class="ml-5 w-0 flex-1">
                                <dl>
                                    <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Active</dt>
                                    <dd class="text-lg font-medium text-gray-900 dark:text-white">{active_items}</dd>
                                </dl>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg transition-colors duration-200">
                    <div class="p-5">
                        <div class="flex items-center">
                            <div class="flex-shrink-0">
                                <i class="fas fa-exclamation-triangle text-red-600 dark:text-red-400 text-2xl"></i>
                            </div>
                            <div class="ml-5 w-0 flex-1">
                                <dl>
                                    <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Errors</dt>
                                    <dd class="text-lg font-medium text-gray-900 dark:text-white">{error_items}</dd>
                                </dl>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg transition-colors duration-200">
                    <div class="p-5">
                        <div class="flex items-center">
                            <div class="flex-shrink-0">
                                <i class="fas fa-bell text-purple-600 dark:text-purple-400 text-2xl"></i>
                            </div>
                            <div class="ml-5 w-0 flex-1">
                                <dl>
                                    <dt class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Recent Events</dt>
                                    <dd class="text-lg font-medium text-gray-900 dark:text-white">{events_count}</dd>
                                </dl>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Quick Actions -->
            <div class="bg-white dark:bg-gray-800 shadow rounded-lg mb-8 transition-colors duration-200">
                <div class="px-4 py-5 sm:p-6">
                    <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Quick Actions</h2>
                    <div class="flex flex-wrap gap-4">
                        <button onclick="linkNewAccount()" 
                               class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-600">
                            <i class="fas fa-plus mr-2"></i>
                            Link New Account
                        </button>
                        <a href="/settings" 
                           class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                            <i class="fas fa-cog mr-2"></i>
                            Configure Settings
                        </a>
                        <a href="/transactions" 
                           class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                            <i class="fas fa-receipt mr-2"></i>
                            View All Transactions
                        </a>
                        <a href="/statements" 
                           class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                            <i class="fas fa-file-pdf mr-2"></i>
                            Bank Statements
                        </a>
                        <a href="/export" 
                           class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                            <i class="fas fa-download mr-2"></i>
                            Export Data
                        </a>
                    </div>
                </div>
            </div>

            <!-- Recent Webhook Events -->
            <div class="bg-white dark:bg-gray-800 shadow rounded-lg transition-colors duration-200">
                <div class="px-4 py-5 sm:p-6">
                    <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Recent Webhook Events</h2>
                    <div class="overflow-hidden">
                        <ul class="divide-y divide-gray-200 dark:divide-gray-700">
                            {events_html}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
        """.format(
            total_items=total_items,
            active_items=active_items,
            error_items=error_items,
            events_count=len(recent_events),
            events_html=events_html
        )

        logger.info("Dashboard loaded successfully")
        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))

    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        return "<h1>Error loading dashboard: " + str(e) + "</h1>"


@app.route('/settings')
def settings():
    """Settings page"""
    config = db.global_config.find_one() or {}

    content = """
    <div class="px-4 py-6 sm:px-0">
        <div class="mb-8">
            <h1 class="text-3xl font-bold text-gray-900">Global Plaid Settings</h1>
            <p class="mt-2 text-gray-600">Configure your Plaid API credentials and webhook settings</p>
        </div>

        <div class="bg-white shadow rounded-lg">
            <div class="px-4 py-5 sm:p-6">
                <form id="settingsForm">
                    <div class="grid grid-cols-1 gap-6">
                        <!-- Environment -->
                        <div>
                            <label for="environment" class="block text-sm font-medium text-gray-700">
                                Environment
                            </label>
                            <select id="environment" 
                                    class="mt-1 block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500 sm:text-sm">
                                <option value="production" {production_selected}>Production</option>
                                <option value="development" {development_selected}>Development</option>
                                <option value="sandbox" {sandbox_selected}>Sandbox</option>
                            </select>
                            <p class="mt-2 text-sm text-gray-500">
                                Choose the Plaid environment. Production is for live data, Sandbox for testing.
                            </p>
                        </div>

                        <!-- Client ID -->
                        <div>
                            <label for="client_id" class="block text-sm font-medium text-gray-700">
                                Client ID
                            </label>
                            <div class="mt-1">
                                <input type="text" 
                                       id="client_id" 
                                       value="{client_id}"
                                       class="shadow-sm focus:ring-blue-500 focus:border-blue-500 block w-full sm:text-sm border-gray-300 rounded-md"
                                       placeholder="Enter your Plaid Client ID">
                            </div>
                        </div>

                        <!-- Secret -->
                        <div>
                            <label for="secret" class="block text-sm font-medium text-gray-700">
                                Secret Key
                            </label>
                            <div class="mt-1 relative">
                                <input type="password" 
                                       id="secret" 
                                       class="shadow-sm focus:ring-blue-500 focus:border-blue-500 block w-full sm:text-sm border-gray-300 rounded-md pr-10"
                                       placeholder="Enter your Plaid Secret Key">
                                <button type="button" 
                                        onclick="toggleSecret()"
                                        class="absolute inset-y-0 right-0 pr-3 flex items-center">
                                    <i id="secretIcon" class="fas fa-eye text-gray-400"></i>
                                </button>
                            </div>
                        </div>

                        <!-- Webhook URL -->
                        <div>
                            <label for="webhook_url" class="block text-sm font-medium text-gray-700">
                                Default Webhook URL
                            </label>
                            <div class="mt-1">
                                <input type="url" 
                                       id="webhook_url" 
                                       value="{webhook_url}"
                                       class="shadow-sm focus:ring-blue-500 focus:border-blue-500 block w-full sm:text-sm border-gray-300 rounded-md"
                                       placeholder="https://your-domain.com/webhook">
                            </div>
                            <p class="mt-2 text-sm text-gray-500">
                                This URL will receive Plaid webhook notifications for transaction updates, errors, etc.
                            </p>
                        </div>
                    </div>

                    <div class="mt-6 flex justify-between">
                        <button type="button" 
                                onclick="testConnection()"
                                id="testBtn"
                                class="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50">
                            <i class="fas fa-plug mr-2"></i>
                            <span>Test Connection</span>
                        </button>
                        
                        <button type="submit" 
                                id="saveBtn"
                                class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                            <i class="fas fa-save mr-2"></i>
                            <span>Save Settings</span>
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <script>
        let showSecret = false;
        
        function toggleSecret() {{
            const input = document.getElementById('secret');
            const icon = document.getElementById('secretIcon');
            showSecret = !showSecret;
            
            input.type = showSecret ? 'text' : 'password';
            icon.className = showSecret ? 'fas fa-eye-slash text-gray-400' : 'fas fa-eye text-gray-400';
        }}
        
        async function testConnection() {{
            const btn = document.getElementById('testBtn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Testing...';
            btn.disabled = true;
            
            try {{
                const response = await fetch('/test-connection', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }}
                }});
                
                const data = await response.json();
                
                if (data.success) {{
                    window.showNotification('Success', data.message || 'Connection test successful');
                }} else {{
                    window.showNotification('Error', data.error || 'Connection test failed', 'error');
                }}
            }} catch (error) {{
                window.showNotification('Error', 'Network error occurred', 'error');
            }} finally {{
                btn.innerHTML = originalText;
                btn.disabled = false;
            }}
        }}
        
        document.getElementById('settingsForm').onsubmit = async function(e) {{
            e.preventDefault();
            
            const btn = document.getElementById('saveBtn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Saving...';
            btn.disabled = true;
            
            const formData = {{
                environment: document.getElementById('environment').value,
                client_id: document.getElementById('client_id').value,
                secret: document.getElementById('secret').value,
                default_webhook_url: document.getElementById('webhook_url').value
            }};
            
            try {{
                const response = await fetch('/settings', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                    }},
                    body: JSON.stringify(formData)
                }});
                
                const data = await response.json();
                
                if (data.success) {{
                    window.showNotification('Success', 'Settings saved successfully');
                }} else {{
                    window.showNotification('Error', data.error || 'Failed to save settings', 'error');
                }}
            }} catch (error) {{
                window.showNotification('Error', 'Network error occurred', 'error');
            }} finally {{
                btn.innerHTML = originalText;
                btn.disabled = false;
            }}
        }};
    </script>
    """.format(
        client_id=config.get("client_id", ""),
        webhook_url=config.get("default_webhook_url", ""),
        production_selected='selected' if config.get("environment", "production") == "production" else "",
        development_selected='selected' if config.get("environment", "production") == "development" else "",
        sandbox_selected='selected' if config.get("environment", "production") == "sandbox" else ""
    )

    return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))


@app.route('/accounts')
def accounts():
    """Accounts page"""
    try:
        items = list(db.plaid_items.find().sort('date_linked', -1))

        # Build table rows
        table_rows = ""
        if items:
            for item in items:
                status_class = "bg-green-100 text-green-800" if item['status'] == 'active' else "bg-red-100 text-red-800" if item['status'] == 'error' else "bg-gray-100 text-gray-800"
                date_linked = item["date_linked"].strftime('%Y-%m-%d %H:%M') if hasattr(item["date_linked"], 'strftime') else str(item["date_linked"])
                last_sync = item["last_sync"].strftime('%Y-%m-%d %H:%M') if hasattr(item["last_sync"], 'strftime') else str(item["last_sync"])

                table_rows += """
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <div class="flex items-center">
                            <div class="flex-shrink-0 h-10 w-10">
                                <div class="h-10 w-10 rounded-full bg-blue-100 flex items-center justify-center">
                                    <i class="fas fa-university text-blue-600"></i>
                                </div>
                            </div>
                            <div class="ml-4">
                                <div class="text-sm font-medium text-gray-900">
                                    {institution_name}
                                </div>
                                <div class="text-sm text-gray-500">
                                    ID: {item_id}
                                </div>
                            </div>
                        </div>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full {status_class}">
                            {status}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {date_linked}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {last_sync}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                        <div class="flex justify-end space-x-2">
                            <a href="/accounts/{record_id}" 
                               class="text-blue-600 hover:text-blue-900" title="View Details">
                                <i class="fas fa-eye"></i>
                            </a>
                            <a href="/accounts/{record_id}/explore" 
                               class="text-purple-600 hover:text-purple-900" title="Explore Accounts">
                                <i class="fas fa-search-dollar"></i>
                            </a>
                            <button onclick="refreshToken('{record_id}')" 
                                    class="text-green-600 hover:text-green-900" title="Refresh Token">
                                <i class="fas fa-sync"></i>
                            </button>
                            <button onclick="unlinkAccount('{record_id}')" 
                                    class="text-red-600 hover:text-red-900" title="Unlink Account">
                                <i class="fas fa-unlink"></i>
                            </button>
                        </div>
                    </td>
                </tr>
                """.format(
                    institution_name=item["institution_name"],
                    item_id=item["item_id"],
                    status_class=status_class,
                    status=item["status"].title(),
                    date_linked=date_linked,
                    last_sync=last_sync,
                    record_id=str(item['_id'])
                )

        table_html = ""
        if items:
            table_html = """
            <div class="overflow-x-auto">
                <table class="min-w-full divide-y divide-gray-200">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Institution
                            </th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Status
                            </th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Date Linked
                            </th>
                            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Last Sync
                            </th>
                            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                                Actions
                            </th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        {table_rows}
                    </tbody>
                </table>
            </div>
            """.format(table_rows=table_rows)
        else:
            table_html = """
            <div class="text-center py-12">
                <i class="fas fa-credit-card text-gray-400 text-6xl mb-4"></i>
                <h3 class="text-lg font-medium text-gray-900 mb-2">No accounts linked</h3>
                <p class="text-gray-500 mb-6">Get started by linking your first financial account</p>
                <button onclick="linkNewAccount()" 
                        class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                    <i class="fas fa-plus mr-2"></i>
                    Link Your First Account
                </button>
            </div>
            """

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8 flex justify-between items-center">
                <div>
                    <h1 class="text-3xl font-bold text-gray-900">Linked Accounts</h1>
                    <p class="mt-2 text-gray-600">Manage your connected financial institutions</p>
                </div>
                <button onclick="linkNewAccount()" 
                        class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                    <i class="fas fa-plus mr-2"></i>
                    Link New Account
                </button>
            </div>

            <!-- Accounts Table -->
            <div class="bg-white shadow rounded-lg overflow-hidden">
                <div class="px-4 py-5 sm:p-6">
                    {table_html}
                </div>
            </div>
        </div>
        """.format(table_html=table_html)

        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))
    except Exception as e:
        return "<h1>Error loading accounts: " + str(e) + "</h1>"


@app.route('/accounts/<item_id>')
def account_details(item_id):
    """Account details page"""
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})

        if not item:
            return redirect('/accounts')

        events = list(db.webhook_events.find({'item_id': item['item_id']}).sort('timestamp', -1).limit(20))

        # Build events HTML
        events_html = ""
        if events:
            for event in events:
                events_html += """
                <div class="border border-gray-200 rounded-lg p-4">
                    <div class="flex items-center justify-between mb-2">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                            {event_type}
                        </span>
                        <span class="text-xs text-gray-500">
                            {timestamp}
                        </span>
                    </div>
                    <div class="text-sm text-gray-600">
                        <pre class="bg-gray-50 p-2 rounded text-xs overflow-x-auto">{payload}</pre>
                    </div>
                </div>
                """.format(
                    event_type=event.get("event_type", "Unknown"),
                    timestamp=str(event.get("timestamp", "Unknown time")),
                    payload=json.dumps(event.get("payload", {}), indent=2)
                )
        else:
            events_html = "<p class='text-gray-500'>No webhook events recorded</p>"

        status_class = "bg-green-100 text-green-800" if item['status'] == 'active' else "bg-red-100 text-red-800" if item['status'] == 'error' else "bg-gray-100 text-gray-800"
        date_linked = item['date_linked'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(item['date_linked'], 'strftime') else str(item['date_linked'])
        last_sync = item['last_sync'].strftime('%Y-%m-%d %H:%M:%S') if hasattr(item['last_sync'], 'strftime') else str(item['last_sync'])

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <div class="flex items-center space-x-4">
                    <a href="/accounts" 
                       class="text-gray-400 hover:text-gray-600">
                        <i class="fas fa-arrow-left"></i>
                    </a>
                    <div>
                        <h1 class="text-3xl font-bold text-gray-900">{institution_name}</h1>
                        <p class="mt-2 text-gray-600">Account details and webhook events</p>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <!-- Account Information -->
                <div class="bg-white shadow rounded-lg">
                    <div class="px-4 py-5 sm:p-6">
                        <h2 class="text-lg font-medium text-gray-900 mb-4">Account Information</h2>
                        <dl class="space-y-4">
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Item ID</dt>
                                <dd class="mt-1 text-sm text-gray-900">{item_id}</dd>
                            </div>
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Institution</dt>
                                <dd class="mt-1 text-sm text-gray-900">{institution_name}</dd>
                            </div>
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Status</dt>
                                <dd class="mt-1">
                                    <span class="inline-flex px-2 py-1 text-xs font-semibold rounded-full {status_class}">
                                        {status}
                                    </span>
                                </dd>
                            </div>
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Date Linked</dt>
                                <dd class="mt-1 text-sm text-gray-900">{date_linked}</dd>
                            </div>
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Last Sync</dt>
                                <dd class="mt-1 text-sm text-gray-900">{last_sync}</dd>
                            </div>
                            <div>
                                <dt class="text-sm font-medium text-gray-500">Access Token</dt>
                                <dd class="mt-1 text-sm text-gray-900 font-mono">{access_token}</dd>
                            </div>
                        </dl>
                        
                        <!-- Quick Actions -->
                        <div class="mt-6 pt-6 border-t border-gray-200">
                            <h3 class="text-sm font-medium text-gray-900 mb-3">Quick Actions</h3>
                            <div class="space-y-2">
                                <a href="/accounts/{record_id}/explore" 
                                   class="inline-flex items-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 w-full justify-center">
                                    <i class="fas fa-search-dollar mr-2"></i>
                                    Explore Accounts & Balances
                                </a>
                                <button onclick="refreshToken('{record_id}')" 
                                        class="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 w-full justify-center">
                                    <i class="fas fa-sync mr-2"></i>
                                    Refresh Connection
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Recent Webhook Events -->
                <div class="bg-white shadow rounded-lg">
                    <div class="px-4 py-5 sm:p-6">
                        <h2 class="text-lg font-medium text-gray-900 mb-4">Recent Webhook Events</h2>
                        <div class="space-y-4 max-h-96 overflow-y-auto">
                            {events_html}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """.format(
            institution_name=item['institution_name'],
            item_id=item['item_id'],
            status_class=status_class,
            status=item['status'].title(),
            date_linked=date_linked,
            last_sync=last_sync,
            access_token=mask_token(item['access_token']),
            record_id=str(item['_id']),
            events_html=events_html
        )

        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))
    except Exception as e:
        return "<h1>Error loading account details: " + str(e) + "</h1>"


@app.route('/accounts/<item_id>/explore')
def account_explorer(item_id):
    """Account explorer page - shows actual account data from Plaid"""
    logger.info(f"🔍 Loading account explorer for item: {item_id}")
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})

        if not item:
            logger.warning(f"⚠️ Item not found for explorer: {item_id}")
            return redirect('/accounts')

        logger.info(f"🏛️ Loading explorer for institution: {item['institution_name']}")

        # Fetch actual account data from Plaid
        config = db.global_config.find_one()
        if not config:
            logger.error("❌ No Plaid configuration found for explorer")
            return "<h1>Error: No Plaid configuration found</h1>"

        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        logger.info(f"🌐 Using {environment} environment for account data")

        # Get accounts from Plaid
        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token'])
        }

        logger.info(f"📤 Fetching accounts from: {base_url}/accounts/get")

        response = requests.post(
            f'{base_url}/accounts/get',
            headers=headers,
            json=payload,
            timeout=10
        )

        logger.info(f"📥 Accounts response status: {response.status_code}")

        accounts_data = []
        if response.status_code == 200:
            data = response.json()
            accounts_data = data.get('accounts', [])
            logger.info(f"✅ Retrieved {len(accounts_data)} accounts")
        else:
            logger.error(f"❌ Failed to fetch accounts: {response.status_code}")
            try:
                error_data = response.json()
                logger.error(f"❌ Accounts error: {error_data}")
            except:
                logger.error(f"❌ Raw accounts error: {response.text}")

        # Build accounts HTML
        accounts_html = ""
        if accounts_data:
            for i, account in enumerate(accounts_data):
                logger.debug(f"📋 Processing account {i+1}: {account.get('name', 'Unknown')}")

                # Get account details
                account_id = account.get('account_id', 'Unknown')
                name = account.get('name', 'Unknown Account')
                official_name = account.get('official_name', '')
                account_type = account.get('type', 'unknown').title()
                subtype = account.get('subtype', 'unknown').title()

                # Get balance information
                balances = account.get('balances', {})
                available = balances.get('available')
                current = balances.get('current')
                limit = balances.get('limit')
                iso_currency_code = balances.get('iso_currency_code', 'USD')

                # Format balances
                def format_currency(amount, currency='USD'):
                    if amount is None:
                        return 'N/A'
                    return f"${amount:,.2f} {currency}"

                available_str = format_currency(available, iso_currency_code)
                current_str = format_currency(current, iso_currency_code)
                limit_str = format_currency(limit, iso_currency_code) if limit else 'N/A'

                # Get account mask
                mask = account.get('mask', '')

                # Choose icon based on account type
                icon_class = {
                    'depository': 'fas fa-piggy-bank text-green-600',
                    'credit': 'fas fa-credit-card text-blue-600',
                    'loan': 'fas fa-money-bill-wave text-orange-600',
                    'investment': 'fas fa-chart-line text-purple-600'
                }.get(account.get('type', ''), 'fas fa-wallet text-gray-600')

                accounts_html += f"""
                <div class="bg-white rounded-lg shadow p-6 mb-4">
                    <div class="flex items-start justify-between mb-4">
                        <div class="flex items-center space-x-3">
                            <div class="flex-shrink-0">
                                <i class="{icon_class} text-2xl"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-gray-900">{name}</h3>
                                {f'<p class="text-sm text-gray-600">{official_name}</p>' if official_name and official_name != name else ''}
                                <p class="text-sm text-gray-500">{account_type} • {subtype}</p>
                                {f'<p class="text-xs text-gray-400 font-mono">****{mask}</p>' if mask else ''}
                            </div>
                        </div>
                        <div class="text-right">
                            <p class="text-sm text-gray-500">Account ID</p>
                            <p class="text-xs text-gray-400 font-mono">{account_id[:15]}...</p>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div class="bg-gray-50 rounded-lg p-4">
                            <p class="text-sm font-medium text-gray-700">Available Balance</p>
                            <p class="text-lg font-semibold text-gray-900">{available_str}</p>
                        </div>
                        <div class="bg-gray-50 rounded-lg p-4">
                            <p class="text-sm font-medium text-gray-700">Current Balance</p>
                            <p class="text-lg font-semibold text-gray-900">{current_str}</p>
                        </div>
                        <div class="bg-gray-50 rounded-lg p-4">
                            <p class="text-sm font-medium text-gray-700">Credit Limit</p>
                            <p class="text-lg font-semibold text-gray-900">{limit_str}</p>
                        </div>
                    </div>
                </div>
                """
        else:
            accounts_html = """
            <div class="text-center py-12">
                <i class="fas fa-exclamation-triangle text-gray-400 text-6xl mb-4"></i>
                <h3 class="text-lg font-medium text-gray-900 mb-2">No Account Data Available</h3>
                <p class="text-gray-500">Unable to retrieve account information from Plaid</p>
            </div>
            """

        status_class = "bg-green-100 text-green-800" if item['status'] == 'active' else "bg-red-100 text-red-800" if item['status'] == 'error' else "bg-gray-100 text-gray-800"

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <div class="flex items-center space-x-4">
                    <a href="/accounts" 
                       class="text-gray-400 hover:text-gray-600">
                        <i class="fas fa-arrow-left"></i>
                    </a>
                    <div>
                        <h1 class="text-3xl font-bold text-gray-900">
                            <i class="fas fa-search-dollar text-purple-600 mr-2"></i>
                            Account Explorer
                        </h1>
                        <p class="mt-2 text-gray-600">Live account data from {institution_name}</p>
                    </div>
                </div>
            </div>

            <!-- Institution Summary -->
            <div class="bg-white shadow rounded-lg p-6 mb-8">
                <div class="flex items-center justify-between">
                    <div class="flex items-center space-x-4">
                        <div class="h-12 w-12 rounded-full bg-blue-100 flex items-center justify-center">
                            <i class="fas fa-university text-blue-600 text-xl"></i>
                        </div>
                        <div>
                            <h2 class="text-xl font-semibold text-gray-900">{institution_name}</h2>
                            <p class="text-sm text-gray-500">Item ID: {item_id}</p>
                        </div>
                    </div>
                    <div class="text-right">
                        <span class="inline-flex px-3 py-1 text-sm font-semibold rounded-full {status_class}">
                            {status}
                        </span>
                        <p class="text-xs text-gray-500 mt-1">{account_count} accounts</p>
                    </div>
                </div>
            </div>

            <!-- Accounts List -->
            <div class="space-y-4">
                <div class="flex justify-between items-center">
                    <h2 class="text-xl font-semibold text-gray-900">Accounts</h2>
                    <div class="flex space-x-2">
                        <button onclick="refreshAccountData('{record_id}')" 
                                class="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50">
                            <i class="fas fa-sync mr-2"></i>
                            Refresh Data
                        </button>
                        <button onclick="showTransactionDatePrompt('{record_id}')" 
                                class="inline-flex items-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                            <i class="fas fa-receipt mr-2"></i>
                            View Transactions
                        </button>
                    </div>
                </div>
                
                {accounts_html}
            </div>
        </div>

        <script>
            // Pass the item ID to JavaScript
            window.currentItemId = '{record_id}';

            async function refreshAccounts() {{
                await window.refreshAccountData(window.currentItemId);
            }}

            // Prompt for date range and call loadTransactions
            function showTransactionDatePrompt(itemId) {{
                // Create a simple prompt for start and end date
                const today = new Date();
                const defaultEnd = today.toISOString().split('T')[0];
                const defaultStart = new Date(today.getTime() - 30*24*60*60*1000).toISOString().split('T')[0];
                const start = prompt('Enter start date (YYYY-MM-DD):', defaultStart);
                if (!start) return;
                const end = prompt('Enter end date (YYYY-MM-DD):', defaultEnd);
                if (!end) return;
                window.loadTransactions(itemId, start, end);
            }}
        </script>
        """.format(
            institution_name=item['institution_name'],
            item_id=item['item_id'],
            status_class=status_class,
            status=item['status'].title(),
            account_count=len(accounts_data),
            record_id=str(item['_id']),
            accounts_html=accounts_html
        )

        logger.info("✅ Account explorer loaded successfully")
        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))

    except Exception as e:
        logger.error(f"Error loading account explorer: {e}", exc_info=True)
        return f"<h1>Error loading account explorer: {str(e)}</h1>"


@app.route('/transactions')
def transactions_page():
    """Transactions overview page"""
    logger.info("Loading transactions page...")
    try:
        # Get all items with transactions
        items = list(db.plaid_items.find({'status': 'active'}))

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <h1 class="text-3xl font-bold text-gray-900 dark:text-white">
                    <i class="fas fa-receipt text-green-600 dark:text-green-400 mr-2"></i>
                    Transaction Center
                </h1>
                <p class="mt-2 text-gray-600 dark:text-gray-300">View transactions by account across all your linked institutions</p>
            </div>

            <!-- Step 1: Institution Selection -->
            <div class="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8 transition-colors duration-200">
                <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Step 1: Select Institution</h2>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        """

        for item in items:
            content += f"""
                    <button onclick="selectInstitution('{str(item['_id'])}', '{item['institution_name']}')" 
                            class="institution-card p-4 border border-gray-300 dark:border-gray-600 rounded-lg hover:border-blue-500 dark:hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors text-left">
                        <div class="flex items-center space-x-3">
                            <div class="h-10 w-10 rounded-full bg-blue-100 dark:bg-blue-900/20 flex items-center justify-center">
                                <i class="fas fa-university text-blue-600 dark:text-blue-400"></i>
                            </div>
                            <div>
                                <h3 class="text-sm font-semibold text-gray-900 dark:text-white">{item['institution_name']}</h3>
                                <p class="text-xs text-gray-500 dark:text-gray-400">Click to view accounts</p>
                            </div>
                        </div>
                    </button>
            """

        if not items:
            content += """
                    <div class="col-span-full text-center py-8">
                        <i class="fas fa-credit-card text-gray-400 dark:text-gray-500 text-4xl mb-4"></i>
                        <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2">No Active Accounts</h3>
                        <p class="text-gray-500 dark:text-gray-400 mb-6">Link your first account to view transactions</p>
                        <button onclick="linkNewAccount()" 
                                class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                            <i class="fas fa-plus mr-2"></i>
                            Link Account
                        </button>
                    </div>
            """

        content += """
                </div>
            </div>

            <!-- Step 2: Account Selection (Hidden initially) -->
            <div id="account-selection" class="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8 transition-colors duration-200 hidden">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-lg font-medium text-gray-900 dark:text-white">Step 2: Select Account</h2>
                    <button onclick="clearInstitutionSelection()" class="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                        <i class="fas fa-arrow-left mr-1"></i>
                        Back to Institutions
                    </button>
                </div>
                <div id="selected-institution" class="mb-4">
                    <!-- Selected institution info will go here -->
                </div>
                <div id="accounts-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    <!-- Accounts will be loaded here -->
                </div>
            </div>

            <!-- Step 3: Transaction Filters (Hidden initially) -->
            <div id="transaction-filters" class="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8 transition-colors duration-200 hidden">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-lg font-medium text-gray-900 dark:text-white">Step 3: Transaction Filters</h2>
                    <button onclick="clearAccountSelection()" class="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
                        <i class="fas fa-arrow-left mr-1"></i>
                        Back to Accounts
                    </button>
                </div>
                <div id="selected-account-info" class="mb-4">
                    <!-- Selected account info will go here -->
                </div>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label for="startDate" class="block text-sm font-medium text-gray-700 dark:text-gray-300">Start Date</label>
                        <input type="date" id="startDate" class="mt-1 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                    </div>
                    <div>
                        <label for="endDate" class="block text-sm font-medium text-gray-700 dark:text-gray-300">End Date</label>
                        <input type="date" id="endDate" class="mt-1 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                    </div>
                    <div>
                        <label for="searchQuery" class="block text-sm font-medium text-gray-700 dark:text-gray-300">Search</label>
                        <input type="text" id="searchQuery" placeholder="Search transactions..." class="mt-1 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                    </div>
                </div>
                <div class="mt-4 flex space-x-3">
                    <button onclick="loadAccountTransactions()" 
                            class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700">
                        <i class="fas fa-search mr-2"></i>
                        Load Transactions
                    </button>
                    <button onclick="exportCurrentAccount()" 
                            class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                        <i class="fas fa-download mr-2"></i>
                        Export CSV
                    </button>
                </div>
            </div>
            
            <!-- Transaction Results -->
            <div id="transaction-results" class="hidden">
                <div class="bg-white dark:bg-gray-800 shadow rounded-lg transition-colors duration-200">
                    <div class="px-4 py-5 sm:p-6">
                        <div class="flex justify-between items-center mb-4">
                            <h2 class="text-lg font-medium text-gray-900 dark:text-white">Transaction Results</h2>
                            <button onclick="closeTransactionResults()" class="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300">
                                <i class="fas fa-times"></i>
                            </button>
                        </div>
                        <div id="transaction-content">
                            <!-- Transaction data will be loaded here -->
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let selectedInstitutionId = null;
            let selectedInstitutionName = null;
            let selectedAccountId = null;
            let selectedAccountName = null;
            
            // Set default date range (last 30 days)
            document.addEventListener('DOMContentLoaded', function() {
                const endDate = new Date();
                const startDate = new Date();
                startDate.setDate(startDate.getDate() - 30);
                
                document.getElementById('endDate').value = endDate.toISOString().split('T')[0];
                document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
            });
            
            async function selectInstitution(institutionId, institutionName) {
                selectedInstitutionId = institutionId;
                selectedInstitutionName = institutionName;
                
                // Show loading state
                window.showNotification('Info', 'Loading accounts...', 'info');
                
                try {
                    const response = await fetch('/api/accounts/' + institutionId + '/data');
                    const data = await response.json();
                    
                    if (data.success && data.accounts && data.accounts.length > 0) {
                        displayAccounts(data.accounts, institutionName);
                        document.getElementById('account-selection').classList.remove('hidden');
                        document.getElementById('account-selection').scrollIntoView({ behavior: 'smooth' });
                        window.showNotification('Success', `Loaded ${data.accounts.length} accounts`);
                    } else if (data.success && data.accounts && data.accounts.length === 0) {
                        window.showNotification('Warning', 'No accounts found for this institution', 'warning');
                    } else {
                        const errorMsg = data.error || 'Failed to load accounts - unknown error';
                        console.error('Account loading failed:', data);
                        window.showNotification('Error', errorMsg, 'error');
                    }
                } catch (error) {
                    console.error('Network error loading accounts:', error);
                    window.showNotification('Error', 'Network error - check console for details', 'error');
                }
            }
            
            function displayAccounts(accounts, institutionName) {
                // Update selected institution display
                document.getElementById('selected-institution').innerHTML = `
                    <div class="flex items-center space-x-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                        <i class="fas fa-university text-blue-600 dark:text-blue-400"></i>
                        <span class="font-medium text-gray-900 dark:text-white">${institutionName}</span>
                    </div>
                `;
                
                // Display accounts
                let html = '';
                accounts.forEach(account => {
                    const balances = account.balances || {};
                    const currentBalance = balances.current ? window.formatCurrency(balances.current, balances.iso_currency_code || 'USD') : 'N/A';
                    const availableBalance = balances.available ? window.formatCurrency(balances.available, balances.iso_currency_code || 'USD') : 'N/A';
                    
                    // Choose icon based on account type
                    const iconClass = {
                        'depository': 'fas fa-piggy-bank text-green-600 dark:text-green-400',
                        'credit': 'fas fa-credit-card text-blue-600 dark:text-blue-400', 
                        'loan': 'fas fa-money-bill-wave text-orange-600 dark:text-orange-400',
                        'investment': 'fas fa-chart-line text-purple-600 dark:text-purple-400'
                    }[account.type] || 'fas fa-wallet text-gray-600 dark:text-gray-400';
                    
                    html += `
                        <button onclick="selectAccount('${account.account_id}', '${account.name.replace(/'/g, "\\'")}', '${account.type}', '${account.subtype || 'N/A'}')" 
                                class="account-card p-4 border border-gray-300 dark:border-gray-600 rounded-lg hover:border-green-500 dark:hover:border-green-400 hover:bg-green-50 dark:hover:bg-green-900/20 transition-colors text-left">
                            <div class="flex items-start justify-between mb-3">
                                <div class="flex items-center space-x-3">
                                    <i class="${iconClass} text-xl"></i>
                                    <div>
                                        <h3 class="text-sm font-semibold text-gray-900 dark:text-white">${account.name}</h3>
                                        <p class="text-xs text-gray-500 dark:text-gray-400">${account.type} • ${account.subtype || 'N/A'}</p>
                                        ${account.mask ? `<p class="text-xs text-gray-400 dark:text-gray-500 font-mono">****${account.mask}</p>` : ''}
                                    </div>
                                </div>
                            </div>
                            <div class="space-y-1">
                                <div class="flex justify-between text-xs">
                                    <span class="text-gray-500 dark:text-gray-400">Current:</span>
                                    <span class="font-medium text-gray-900 dark:text-white">${currentBalance}</span>
                                </div>
                                ${balances.available !== null ? `
                                <div class="flex justify-between text-xs">
                                    <span class="text-gray-500 dark:text-gray-400">Available:</span>
                                    <span class="font-medium text-gray-900 dark:text-white">${availableBalance}</span>
                                </div>
                                ` : ''}
                            </div>
                        </button>
                    `;
                });
                
                document.getElementById('accounts-grid').innerHTML = html;
            }
            
            function selectAccount(accountId, accountName, accountType, accountSubtype) {
                selectedAccountId = accountId;
                selectedAccountName = accountName;
                
                // Update selected account display
                document.getElementById('selected-account-info').innerHTML = `
                    <div class="flex items-center space-x-3 p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
                        <i class="fas fa-piggy-bank text-green-600 dark:text-green-400"></i>
                        <div>
                            <span class="font-medium text-gray-900 dark:text-white">${accountName}</span>
                            <span class="text-sm text-gray-500 dark:text-gray-400 ml-2">(${accountType} • ${accountSubtype})</span>
                        </div>
                    </div>
                `;
                
                document.getElementById('transaction-filters').classList.remove('hidden');
                document.getElementById('transaction-filters').scrollIntoView({ behavior: 'smooth' });
            }
            
            async function loadAccountTransactions() {
                if (!selectedInstitutionId || !selectedAccountId) {
                    window.showNotification('Error', 'Please select an account first', 'error');
                    return;
                }
                
                const startDate = document.getElementById('startDate').value;
                const endDate = document.getElementById('endDate').value;
                const searchQuery = document.getElementById('searchQuery').value;
                
                try {
                    window.showNotification('Info', 'Loading transactions...', 'info');
                    
                    const params = new URLSearchParams({
                        start_date: startDate,
                        end_date: endDate,
                        account_id: selectedAccountId
                    });
                    
                    const response = await fetch(`/api/accounts/${selectedInstitutionId}/transactions?${params}`);
                    const data = await response.json();
                    
                    if (data.success) {
                        let filteredTransactions = data.transactions;
                        
                        // Filter by account ID
                        filteredTransactions = filteredTransactions.filter(t => t.account_id === selectedAccountId);
                        
                        // Client-side search filtering
                        if (searchQuery) {
                            filteredTransactions = filteredTransactions.filter(t => 
                                t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                                (t.category && t.category.some(c => c.toLowerCase().includes(searchQuery.toLowerCase())))
                            );
                        }
                        
                        displayTransactions(filteredTransactions);
                        window.showNotification('Success', `Found ${filteredTransactions.length} transactions`);
                    } else {
                        window.showNotification('Error', data.error || 'Failed to load transactions', 'error');
                    }
                } catch (error) {
                    window.showNotification('Error', 'Network error occurred', 'error');
                }
            }
            
            function displayTransactions(transactions) {
                let html = '<div class="overflow-x-auto"><table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">';
                html += '<thead class="bg-gray-50 dark:bg-gray-700"><tr>';
                html += '<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Date</th>';
                html += '<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Description</th>';
                html += '<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Amount</th>';
                html += '<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase tracking-wider">Category</th>';
                html += '</tr></thead><tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">';
                
                transactions.slice(0, 100).forEach(transaction => {
                    const amount = transaction.amount;
                    const amountClass = amount > 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400';
                    const amountText = window.formatCurrency(Math.abs(amount));
                    
                    html += '<tr>';
                    html += `<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">${transaction.date}</td>`;
                    html += `<td class="px-6 py-4 text-sm text-gray-900 dark:text-gray-100">${transaction.name}</td>`;
                    html += `<td class="px-6 py-4 whitespace-nowrap text-sm ${amountClass}">${amount > 0 ? '-' : '+'}${amountText}</td>`;
                    html += `<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">${transaction.category ? transaction.category.join(', ') : 'N/A'}</td>`;
                    html += '</tr>';
                });
                
                html += '</tbody></table></div>';
                
                if (transactions.length > 100) {
                    html += `<p class="text-sm text-gray-500 dark:text-gray-400 mt-4 text-center">Showing first 100 of ${transactions.length} transactions</p>`;
                }
                
                document.getElementById('transaction-content').innerHTML = html;
                document.getElementById('transaction-results').classList.remove('hidden');
                document.getElementById('transaction-results').scrollIntoView({ behavior: 'smooth' });
            }
            
            function clearInstitutionSelection() {
                selectedInstitutionId = null;
                selectedInstitutionName = null;
                document.getElementById('account-selection').classList.add('hidden');
                document.getElementById('transaction-filters').classList.add('hidden');
                document.getElementById('transaction-results').classList.add('hidden');
            }
            
            function clearAccountSelection() {
                selectedAccountId = null;
                selectedAccountName = null;
                document.getElementById('transaction-filters').classList.add('hidden');
                document.getElementById('transaction-results').classList.add('hidden');
            }
            
            function closeTransactionResults() {
                document.getElementById('transaction-results').classList.add('hidden');
            }
            
            async function exportCurrentAccount() {
                if (!selectedInstitutionId || !selectedAccountId) {
                    window.showNotification('Error', 'Please select an account first', 'error');
                    return;
                }
                
                const startDate = document.getElementById('startDate').value;
                const endDate = document.getElementById('endDate').value;
                
                try {
                    window.showNotification('Info', 'Preparing export...', 'info');
                    
                    const params = new URLSearchParams({
                        accounts: selectedAccountId,
                        start_date: startDate,
                        end_date: endDate
                    });
                    
                    window.location.href = `/export/accounts/${selectedInstitutionId}/csv?${params}`;
                    window.showNotification('Success', 'Export started');
                } catch (error) {
                    window.showNotification('Error', 'Export failed', 'error');
                }
            }
        </script>
        """

        logger.info("Transactions page loaded successfully")
        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))

    except Exception as e:
        logger.error(f"Error loading transactions page: {e}", exc_info=True)
        return "<h1>Error loading transactions page: " + str(e) + "</h1>"


@app.route('/export')
def export_page():
    """Export data page"""
    logger.info("Loading export page...")
    try:
        items = list(db.plaid_items.find({'status': 'active'}))

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <h1 class="text-3xl font-bold text-gray-900">
                    <i class="fas fa-download text-indigo-600 mr-2"></i>
                    Data Export Center
                </h1>
                <p class="mt-2 text-gray-600">Export account and transaction data in various formats</p>
            </div>

            <!-- Export Options -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
                <!-- Individual Institution Exports -->
                <div class="bg-white dark:bg-gray-800 shadow rounded-lg transition-colors duration-200">
                    <div class="px-4 py-5 sm:p-6">
                        <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Institution Data</h2>
                        <p class="text-sm text-gray-600 dark:text-gray-300 mb-4">Export data for individual institutions</p>
                        
                        <div class="space-y-3">
        """

        for item in items:
            content += f"""
                            <div class="flex items-center justify-between p-3 border border-gray-200 dark:border-gray-600 rounded-lg">
                                <div>
                                    <h3 class="text-sm font-medium text-gray-900 dark:text-white">{item['institution_name']}</h3>
                                    <p class="text-xs text-gray-500 dark:text-gray-400">Item ID: {item['item_id']}</p>
                                </div>
                                <div class="flex space-x-2">
                                    <a href="/export/institution/{str(item['_id'])}/csv" 
                                       class="inline-flex items-center px-2 py-1 border border-gray-300 dark:border-gray-600 text-xs font-medium rounded text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                                        CSV
                                    </a>
                                    <a href="/export/institution/{str(item['_id'])}/json" 
                                       class="inline-flex items-center px-2 py-1 border border-gray-300 dark:border-gray-600 text-xs font-medium rounded text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                                        JSON
                                    </a>
                                </div>
                            </div>
            """

        if not items:
            content += """
                            <div class="text-center py-8">
                                <i class="fas fa-exclamation-triangle text-gray-400 dark:text-gray-500 text-3xl mb-2"></i>
                                <p class="text-gray-500 dark:text-gray-400">No active institutions to export</p>
                            </div>
            """

        content += """
                        </div>
                    </div>
                </div>
                
                <!-- Account-Level Exports -->
                <div class="bg-white dark:bg-gray-800 shadow rounded-lg transition-colors duration-200">
                    <div class="px-4 py-5 sm:p-6">
                        <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Account Data</h2>
                        <p class="text-sm text-gray-600 dark:text-gray-300 mb-4">Export transaction data for specific accounts</p>
                        
                        <div class="space-y-4">
                            <div>
                                <label for="accountInstitutionSelect" class="block text-sm font-medium text-gray-700 dark:text-gray-300">Select Institution</label>
                                <select id="accountInstitutionSelect" onchange="loadAccountsForExport(this.value)" class="mt-1 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                                    <option value="">Choose an institution...</option>
        """

        for item in items:
            content += f'<option value="{str(item["_id"])}">{item["institution_name"]}</option>'

        content += """
                                </select>
                            </div>
                            
                            <div id="accountsList" class="hidden">
                                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Available Accounts</label>
                                <div id="accountsContent" class="space-y-2">
                                    <!-- Accounts will be loaded here -->
                                </div>
                            </div>
                            
                            <div id="accountExportOptions" class="hidden">
                                <div class="grid grid-cols-2 gap-2">
                                    <div>
                                        <label for="accountStartDate" class="block text-xs text-gray-600 dark:text-gray-400">Start Date</label>
                                        <input type="date" id="accountStartDate" class="mt-1 block w-full px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                                    </div>
                                    <div>
                                        <label for="accountEndDate" class="block text-xs text-gray-600 dark:text-gray-400">End Date</label>
                                        <input type="date" id="accountEndDate" class="mt-1 block w-full px-2 py-1 border border-gray-300 dark:border-gray-600 rounded text-xs bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                                    </div>
                                </div>
                                <button onclick="exportSelectedAccounts()" 
                                        class="mt-3 w-full inline-flex items-center justify-center px-3 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700">
                                    <i class="fas fa-download mr-2"></i>
                                    Export Selected Accounts
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- Bulk Export Options -->
                <div class="bg-white dark:bg-gray-800 shadow rounded-lg transition-colors duration-200">
                    <div class="px-4 py-5 sm:p-6">
                        <h2 class="text-lg font-medium text-gray-900 dark:text-white mb-4">Bulk Export</h2>
                        <p class="text-sm text-gray-600 dark:text-gray-300 mb-4">Export data from all institutions</p>
                        
                        <div class="space-y-3">
                            <a href="/export/all/accounts/csv" 
                               class="w-full inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700">
                                <i class="fas fa-piggy-bank mr-2"></i>
                                Export All Accounts (CSV)
                            </a>
                            <a href="/export/all/transactions/csv" 
                               class="w-full inline-flex items-center justify-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                                <i class="fas fa-receipt mr-2"></i>
                                Export All Transactions (CSV)
                            </a>
                            <a href="/export/all/complete/json" 
                               class="w-full inline-flex items-center justify-center px-4 py-2 border border-gray-300 dark:border-gray-600 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                                <i class="fas fa-database mr-2"></i>
                                Complete Data Export (JSON)
                            </a>
                        </div>
                        
                        <!-- Export Configuration -->
                        <div class="mt-6 pt-6 border-t border-gray-200 dark:border-gray-600">
                            <h3 class="text-sm font-medium text-gray-900 dark:text-white mb-3">Export Options</h3>
                            <form id="exportConfigForm">
                                <div class="space-y-3">
                                    <div>
                                        <label class="flex items-center">
                                            <input type="checkbox" id="includePII" class="rounded border-gray-300 dark:border-gray-600 text-indigo-600">
                                            <span class="ml-2 text-sm text-gray-700 dark:text-gray-300">Include sensitive data (account numbers, etc.)</span>
                                        </label>
                                    </div>
                                    <div>
                                        <label class="flex items-center">
                                            <input type="checkbox" id="includeBalances" checked class="rounded border-gray-300 dark:border-gray-600 text-indigo-600">
                                            <span class="ml-2 text-sm text-gray-700 dark:text-gray-300">Include current balances</span>
                                        </label>
                                    </div>
                                    <div>
                                        <label for="dateRange" class="block text-sm font-medium text-gray-700 dark:text-gray-300">Transaction Date Range</label>
                                        <select id="dateRange" class="mt-1 block w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white">
                                            <option value="30">Last 30 days</option>
                                            <option value="90">Last 90 days</option>
                                            <option value="365">Last year</option>
                                            <option value="all">All available</option>
                                        </select>
                                    </div>
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // Set default date range for account exports
            document.addEventListener('DOMContentLoaded', function() {
                const endDate = new Date();
                const startDate = new Date();
                startDate.setDate(startDate.getDate() - 90); // Default to 90 days
                
                document.getElementById('accountEndDate').value = endDate.toISOString().split('T')[0];
                document.getElementById('accountStartDate').value = startDate.toISOString().split('T')[0];
            });
            
            async function loadAccountsForExport(itemId) {
                if (!itemId) {
                    document.getElementById('accountsList').classList.add('hidden');
                    document.getElementById('accountExportOptions').classList.add('hidden');
                    return;
                }
                
                try {
                    window.showNotification('Info', 'Loading accounts...', 'info');
                    
                    const response = await fetch('/api/accounts/' + itemId + '/data');
                    const data = await response.json();
                    
                    if (data.success && data.accounts.length > 0) {
                        displayAccountsForExport(data.accounts);
                        document.getElementById('accountsList').classList.remove('hidden');
                        document.getElementById('accountExportOptions').classList.remove('hidden');
                        window.showNotification('Success', `Loaded ${data.accounts.length} accounts`);
                    } else {
                        window.showNotification('Error', 'No accounts found or failed to load', 'error');
                        document.getElementById('accountsList').classList.add('hidden');
                        document.getElementById('accountExportOptions').classList.add('hidden');
                    }
                } catch (error) {
                    window.showNotification('Error', 'Failed to load accounts', 'error');
                    document.getElementById('accountsList').classList.add('hidden');
                    document.getElementById('accountExportOptions').classList.add('hidden');
                }
            }
            
            function displayAccountsForExport(accounts) {
                const container = document.getElementById('accountsContent');
                
                let html = '';
                accounts.forEach(account => {
                    const balances = account.balances || {};
                    const currentBalance = balances.current ? window.formatCurrency(balances.current) : 'N/A';
                    
                    html += `
                        <label class="flex items-center p-3 border border-gray-200 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700">
                            <input type="checkbox" value="${account.account_id}" class="account-checkbox rounded border-gray-300 dark:border-gray-600 text-green-600">
                            <div class="ml-3 flex-1">
                                <div class="flex justify-between items-center">
                                    <div>
                                        <p class="text-sm font-medium text-gray-900 dark:text-white">${account.name}</p>
                                        <p class="text-xs text-gray-500 dark:text-gray-400">${account.type} • ${account.subtype || 'N/A'}</p>
                                    </div>
                                    <div class="text-right">
                                        <p class="text-sm font-medium text-gray-900 dark:text-white">${currentBalance}</p>
                                        <p class="text-xs text-gray-500 dark:text-gray-400">Current Balance</p>
                                    </div>
                                </div>
                            </div>
                        </label>
                    `;
                });
                
                container.innerHTML = html;
            }
            
            async function exportSelectedAccounts() {
                const selectedAccounts = Array.from(document.querySelectorAll('.account-checkbox:checked')).map(cb => cb.value);
                const institutionId = document.getElementById('accountInstitutionSelect').value;
                const startDate = document.getElementById('accountStartDate').value;
                const endDate = document.getElementById('accountEndDate').value;
                
                if (selectedAccounts.length === 0) {
                    window.showNotification('Error', 'Please select at least one account', 'error');
                    return;
                }
                
                try {
                    window.showNotification('Info', 'Preparing account export...', 'info');
                    
                    const params = new URLSearchParams({
                        accounts: selectedAccounts.join(','),
                        start_date: startDate,
                        end_date: endDate
                    });
                    
                    window.location.href = `/export/accounts/${institutionId}/csv?${params}`;
                    window.showNotification('Success', 'Export started');
                } catch (error) {
                    window.showNotification('Error', 'Export failed', 'error');
                }
            }
        </script>
        """

        logger.info("Export page loaded successfully")
        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))

    except Exception as e:
        logger.error(f"Error loading export page: {e}", exc_info=True)
        return "<h1>Error loading export page: " + str(e) + "</h1>"


@app.route('/statements')
def statements_page():
    """PDF Statements page"""
    logger.info("Loading statements page...")
    try:
        items = list(db.plaid_items.find({'status': 'active'}))

        content = """
        <div class="px-4 py-6 sm:px-0">
            <div class="mb-8">
                <h1 class="text-3xl font-bold text-gray-900 dark:text-white">
                    <i class="fas fa-file-pdf text-red-600 dark:text-red-400 mr-2"></i>
                    Bank Statements
                </h1>
                <p class="mt-2 text-gray-600 dark:text-gray-300">Download official PDF statements from your banks</p>
                <div class="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
                    <div class="flex">
                        <i class="fas fa-info-circle text-blue-400 mr-2 mt-1"></i>
                        <div class="text-sm text-blue-700 dark:text-blue-300">
                            <p><strong>Note:</strong> PDF statements are only available for US institutions that support Plaid's Statements product. Not all banks provide this feature.</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Institution Cards -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        """

        for item in items:
            content += f"""
                <div class="bg-white dark:bg-gray-800 rounded-lg shadow p-6 transition-colors duration-200">
                    <div class="flex items-center justify-between mb-4">
                        <div class="flex items-center space-x-3">
                            <div class="h-10 w-10 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center">
                                <i class="fas fa-university text-red-600 dark:text-red-400"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{item['institution_name']}</h3>
                                <p class="text-sm text-gray-500 dark:text-gray-400">Item ID: {item['item_id'][:20]}...</p>
                            </div>
                        </div>
                    </div>
                    
                    <div class="space-y-2">
                        <button onclick="loadStatementsList('{str(item['_id'])}')" 
                                class="w-full inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 dark:bg-red-700 dark:hover:bg-red-600">
                            <i class="fas fa-list mr-2"></i>
                            View Available Statements
                        </button>
                        <div id="statements-list-{str(item['_id'])}" class="hidden mt-4">
                            <!-- Statements will be loaded here -->
                        </div>
                    </div>
                </div>
            """

        if not items:
            content += """
                <div class="col-span-full text-center py-12">
                    <i class="fas fa-credit-card text-gray-400 dark:text-gray-500 text-6xl mb-4"></i>
                    <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2">No Active Accounts</h3>
                    <p class="text-gray-500 dark:text-gray-400 mb-6">Link your first account to view statements</p>
                    <button onclick="linkNewAccount()" 
                            class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700">
                        <i class="fas fa-plus mr-2"></i>
                        Link Account
                    </button>
                </div>
            """

        content += """
            </div>
        </div>

        <script>
            async function loadStatementsList(itemId) {
                try {
                    window.showNotification('Info', 'Loading available statements...', 'info');
                    
                    const response = await fetch('/api/statements/' + itemId + '/list');
                    const data = await response.json();
                    
                    if (data.success && data.statements.length > 0) {
                        displayStatements(data.statements, itemId);
                        window.showNotification('Success', `Found ${data.statements.length} statements`);
                    } else if (data.success && data.statements.length === 0) {
                        window.showNotification('Info', 'No statements available for this institution', 'info');
                        displayNoStatements(itemId);
                    } else {
                        window.showNotification('Error', data.error || 'Failed to load statements', 'error');
                        displayError(data.error || 'Failed to load statements', itemId);
                    }
                } catch (error) {
                    console.error('Error loading statements:', error);
                    window.showNotification('Error', 'Network error occurred', 'error');
                    displayError('Network error occurred', itemId);
                }
            }
            
            function displayStatements(statements, itemId) {
                const container = document.getElementById('statements-list-' + itemId);
                
                let html = '<div class="border-t pt-4 mt-4"><h4 class="text-sm font-medium text-gray-900 dark:text-white mb-3">Available Statements</h4>';
                html += '<div class="space-y-2">';
                
                statements.forEach(statement => {
                    const startDate = new Date(statement.start_date).toLocaleDateString();
                    const endDate = new Date(statement.end_date).toLocaleDateString();
                    
                    html += `
                        <div class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                            <div>
                                <p class="text-sm font-medium text-gray-900 dark:text-white">${startDate} - ${endDate}</p>
                                <p class="text-xs text-gray-500 dark:text-gray-400">Account: ${statement.account_id.substring(0, 8)}...</p>
                            </div>
                            <button onclick="downloadStatement('${statement.statement_id}', '${startDate}_${endDate}')" 
                                    class="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded text-white bg-red-600 hover:bg-red-700">
                                <i class="fas fa-download mr-1"></i>
                                PDF
                            </button>
                        </div>
                    `;
                });
                
                html += '</div></div>';
                
                container.innerHTML = html;
                container.classList.remove('hidden');
            }
            
            function displayNoStatements(itemId) {
                const container = document.getElementById('statements-list-' + itemId);
                container.innerHTML = `
                    <div class="border-t pt-4 mt-4">
                        <div class="text-center py-4">
                            <i class="fas fa-exclamation-triangle text-yellow-500 text-2xl mb-2"></i>
                            <p class="text-sm text-gray-600 dark:text-gray-400">No statements available</p>
                            <p class="text-xs text-gray-500 dark:text-gray-500 mt-1">This institution may not support PDF statements</p>
                        </div>
                    </div>
                `;
                container.classList.remove('hidden');
            }
            
            function displayError(error, itemId) {
                const container = document.getElementById('statements-list-' + itemId);
                container.innerHTML = `
                    <div class="border-t pt-4 mt-4">
                        <div class="text-center py-4">
                            <i class="fas fa-exclamation-circle text-red-500 text-2xl mb-2"></i>
                            <p class="text-sm text-red-600 dark:text-red-400">${error}</p>
                        </div>
                    </div>
                `;
                container.classList.remove('hidden');
            }
            
            async function downloadStatement(statementId, filename) {
                try {
                    window.showNotification('Info', 'Downloading statement PDF...', 'info');
                    
                    // Create a download link
                    const downloadUrl = '/api/statements/download/' + statementId;
                    const link = document.createElement('a');
                    link.href = downloadUrl;
                    link.download = 'statement_' + filename + '.pdf';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    
                    window.showNotification('Success', 'Statement download started');
                } catch (error) {
                    window.showNotification('Error', 'Download failed', 'error');
                }
            }
        </script>
        """

        logger.info("Statements page loaded successfully")
        return render_template_string(BASE_TEMPLATE.replace('{CONTENT_PLACEHOLDER}', content))

    except Exception as e:
        logger.error(f"Error loading statements page: {e}", exc_info=True)
        return "<h1>Error loading statements page: " + str(e) + "</h1>"

# API Routes


@app.route('/api/accounts/<item_id>/data')
def get_account_data(item_id):
    """API endpoint to get fresh account data"""
    logger.info(f"📊 API request for account data: {item_id}")
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})

        if not item:
            logger.warning(f"⚠️ Item not found for API request: {item_id}")
            return jsonify({'success': False, 'error': 'Item not found'})

        config = db.global_config.find_one()
        if not config:
            logger.error("❌ No Plaid configuration found for API")
            return jsonify({'success': False, 'error': 'No Plaid configuration found'})

        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        # Get accounts from Plaid
        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token'])
        }

        logger.info(f"📤 API fetching accounts from Plaid...")

        response = requests.post(
            f'{base_url}/accounts/get',
            headers=headers,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            accounts = data.get('accounts', [])
            logger.info(f"✅ API retrieved {len(accounts)} accounts")

            # Update last sync time
            db.plaid_items.update_one(
                {'_id': ObjectId(item_id)},
                {'$set': {'last_sync': datetime.utcnow()}}
            )

            return jsonify({
                'success': True,
                'accounts': accounts,
                'item': data.get('item', {}),
                'total_accounts': len(accounts)
            })
        else:
            logger.error(f"❌ API accounts fetch failed: {response.status_code}")
            try:
                error_data = response.json()
                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error: {error_data.get('error_message', 'Unknown error')}"
                })
            except:
                return jsonify({
                    'success': False,
                    'error': f"API request failed with HTTP {response.status_code}"
                })

    except Exception as e:
        logger.error(f"❌ API error getting account data: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/export/institution/<item_id>/csv')
def export_institution_csv(item_id):
    """Export institution data as CSV"""
    logger.info(f"Exporting CSV for institution: {item_id}")
    try:
        from bson.objectid import ObjectId
        import csv
        import io

        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})
        if not item:
            return "Institution not found", 404

        config = db.global_config.find_one()
        if not config:
            return "No Plaid configuration found", 500

        # Get data from Plaid
        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        headers = {'Content-Type': 'application/json'}

        # Get accounts
        accounts_payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token'])
        }

        accounts_response = requests.post(f'{base_url}/accounts/get', headers=headers, json=accounts_payload, timeout=10)
        accounts_data = accounts_response.json().get('accounts', []) if accounts_response.status_code == 200 else []

        # Get transactions
        from datetime import timedelta
        start_date = (datetime.utcnow() - timedelta(days=90)).date()
        end_date = datetime.utcnow().date()

        transactions_payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token']),
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }

        transactions_response = requests.post(f'{base_url}/transactions/get', headers=headers, json=transactions_payload, timeout=15)
        transactions_data = transactions_response.json().get('transactions', []) if transactions_response.status_code == 200 else []

        # Create CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write accounts data
        writer.writerow(['=== ACCOUNTS ==='])
        writer.writerow(['Account ID', 'Name', 'Type', 'Subtype', 'Available Balance', 'Current Balance', 'Currency'])

        for account in accounts_data:
            balances = account.get('balances', {})
            writer.writerow([
                account.get('account_id', ''),
                account.get('name', ''),
                account.get('type', ''),
                account.get('subtype', ''),
                balances.get('available', ''),
                balances.get('current', ''),
                balances.get('iso_currency_code', 'USD')
            ])

        writer.writerow([])

        # Write transactions data
        writer.writerow(['=== TRANSACTIONS ==='])
        writer.writerow(['Date', 'Name', 'Amount', 'Account ID', 'Category', 'Transaction ID'])

        for transaction in transactions_data:
            writer.writerow([
                transaction.get('date', ''),
                transaction.get('name', ''),
                transaction.get('amount', ''),
                transaction.get('account_id', ''),
                ', '.join(transaction.get('category', [])),
                transaction.get('transaction_id', '')
            ])

        # Prepare response
        output_str = output.getvalue()
        output.close()

        from flask import Response

        response = Response(
            output_str,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename={item["institution_name"]}_export.csv'}
        )

        logger.info(f"CSV export completed for {item['institution_name']}")
        return response

    except Exception as e:
        logger.error(f"Error exporting CSV: {e}", exc_info=True)
        return f"Export failed: {str(e)}", 500


@app.route('/api/statements/<item_id>/list')
def list_statements(item_id):
    """List available PDF statements for an institution"""
    logger.info(f"Listing statements for institution: {item_id}")
    try:
        from bson.objectid import ObjectId

        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})
        if not item:
            return jsonify({'success': False, 'error': 'Institution not found'})

        config = db.global_config.find_one()
        if not config:
            return jsonify({'success': False, 'error': 'No Plaid configuration found'})

        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        # Get statements list from Plaid
        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token'])
        }

        logger.info(f"Fetching statements from: {base_url}/statements/list")

        response = requests.post(
            f'{base_url}/statements/list',
            headers=headers,
            json=payload,
            timeout=15
        )

        logger.info(f"Statements list response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            statements = data.get('statements', [])
            logger.info(f"Retrieved {len(statements)} statements")

            return jsonify({
                'success': True,
                'statements': statements,
                'total_statements': len(statements)
            })
        else:
            logger.error(f"Failed to fetch statements: {response.status_code}")
            try:
                error_data = response.json()
                error_msg = error_data.get('error_message', 'Unknown error')
                logger.error(f"Statements error: {error_data}")
                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error: {error_msg}"
                })
            except:
                return jsonify({
                    'success': False,
                    'error': f"API request failed with HTTP {response.status_code}"
                })

    except Exception as e:
        logger.error(f"Error listing statements: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/statements/download/<statement_id>')
def download_statement(statement_id):
    """Download a PDF statement by statement ID"""
    logger.info(f"Downloading statement: {statement_id}")
    try:
        # Find which item this statement belongs to by checking recent API calls
        # For simplicity, we'll need to pass the item info or store it differently
        # For now, let's get the first active item and try to download
        # In a real implementation, you'd want to store statement-to-item mapping

        config = db.global_config.find_one()
        if not config:
            return "No Plaid configuration found", 500

        # Get the first active item (this is a simplification)
        # In production, you'd want to properly map statement_id to item_id
        item = db.plaid_items.find_one({'status': 'active'})
        if not item:
            return "No active items found", 404

        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token']),
            'statement_id': statement_id
        }

        logger.info(f"Downloading statement from: {base_url}/statements/download")

        response = requests.post(
            f'{base_url}/statements/download',
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            logger.info(f"Statement download successful for {statement_id}")

            from flask import Response

            return Response(
                response.content,
                mimetype='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename=statement_{statement_id}.pdf',
                    'Content-Type': 'application/pdf'
                }
            )
        else:
            logger.error(f"Failed to download statement: {response.status_code}")
            try:
                error_data = response.json()
                return f"Download failed: {error_data.get('error_message', 'Unknown error')}", 400
            except:
                return f"Download failed with HTTP {response.status_code}", 400

    except Exception as e:
        logger.error(f"Error downloading statement: {e}", exc_info=True)
        return f"Download failed: {str(e)}", 500


@app.route('/export/institution/<item_id>/json')
def export_institution_json(item_id):
    """Export institution data as JSON"""
    logger.info(f"Exporting JSON for institution: {item_id}")
    try:
        from bson.objectid import ObjectId

        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})
        if not item:
            return "Institution not found", 404

        config = db.global_config.find_one()
        if not config:
            return "No Plaid configuration found", 500

        # Get data from Plaid API (similar to CSV export)
        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        headers = {'Content-Type': 'application/json'}

        # Get accounts and transactions
        accounts_payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token'])
        }

        accounts_response = requests.post(f'{base_url}/accounts/get', headers=headers, json=accounts_payload, timeout=10)
        accounts_data = accounts_response.json() if accounts_response.status_code == 200 else {}

        # Prepare JSON response
        export_data = {
            'institution': {
                'name': item['institution_name'],
                'item_id': item['item_id'],
                'date_linked': item['date_linked'].isoformat() if hasattr(item['date_linked'], 'isoformat') else str(item['date_linked']),
                'last_sync': item['last_sync'].isoformat() if hasattr(item['last_sync'], 'isoformat') else str(item['last_sync']),
                'status': item['status']
            },
            'accounts': accounts_data.get('accounts', []),
            'export_timestamp': datetime.utcnow().isoformat()
        }

        from flask import Response

        response = Response(
            json.dumps(export_data, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename={item["institution_name"]}_export.json'}
        )

        logger.info(f"JSON export completed for {item['institution_name']}")
        return response

    except Exception as e:
        logger.error(f"Error exporting JSON: {e}", exc_info=True)
        return f"Export failed: {str(e)}", 500


@app.route('/api/accounts/<item_id>/transactions')
def get_account_transactions(item_id):
    """API endpoint to get recent transactions"""
    logger.info(f"💳 API request for transactions: {item_id}")
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})

        if not item:
            return jsonify({'success': False, 'error': 'Item not found'})

        config = db.global_config.find_one()
        if not config:
            return jsonify({'success': False, 'error': 'No Plaid configuration found'})

        environment = item.get('environment', config.get('environment', 'production'))
        base_url = get_plaid_base_url(environment)

        # Accept start_date and end_date as query parameters
        from datetime import timedelta
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        try:
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            else:
                start_date = (datetime.utcnow() - timedelta(days=30)).date()
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                end_date = datetime.utcnow().date()
        except Exception as e:
            logger.error(f"Invalid date format for start_date or end_date: {e}")
            return jsonify({'success': False, 'error': 'Invalid date format. Use YYYY-MM-DD.'})

        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'access_token': retrieve_token(item['access_token']),
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        }

        logger.info(f"📤 API fetching transactions from Plaid for {start_date} to {end_date}...")

        response = requests.post(
            f'{base_url}/transactions/get',
            headers=headers,
            json=payload,
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            transactions = data.get('transactions', [])
            logger.info(f"✅ API retrieved {len(transactions)} transactions")

            return jsonify({
                'success': True,
                'transactions': transactions,
                'total_transactions': data.get('total_transactions', len(transactions)),
                'accounts': data.get('accounts', [])
            })
        else:
            logger.error(f"❌ API transactions fetch failed: {response.status_code}")
            try:
                error_data = response.json()
                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error: {error_data.get('error_message', 'Unknown error')}"
                })
            except:
                return jsonify({
                    'success': False,
                    'error': f"API request failed with HTTP {response.status_code}"
                })

    except Exception as e:
        logger.error(f"❌ API error getting transactions: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/get-plaid-config')
def get_plaid_config():
    """Get Plaid configuration for frontend"""
    logger.info("Frontend requesting Plaid configuration...")
    try:
        config = db.global_config.find_one() or {}
        logger.info(f"Config found: {bool(config)}")

        environment = config.get('environment', 'production')
        client_id = config.get('client_id', '')
        has_credentials = bool(config.get('client_id') and config.get('secret'))

        logger.info(f"Environment: {environment}")
        logger.info(f"Client ID: {client_id[:10]}..." if client_id else "No Client ID")
        logger.info(f"Has credentials: {has_credentials}")

        response_data = {
            'environment': environment,
            'client_id': client_id,
            'has_credentials': has_credentials
        }

        logger.info("Plaid config sent to frontend")
        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error getting Plaid config: {e}", exc_info=True)
        return jsonify({'environment': 'production', 'has_credentials': False})


@app.route('/create-link-token', methods=['POST'])
def create_link_token():
    """Create a Plaid Link token"""
    logger.info("Creating Plaid Link token...")
    try:
        logger.info("Loading Plaid configuration from database...")
        config = db.global_config.find_one()

        if not config:
            logger.error("No Plaid configuration found in database")
            return jsonify({'success': False, 'error': 'Plaid credentials not configured. Please configure in Settings first.'})

        if not config.get('client_id'):
            logger.error("No client_id found in configuration")
            return jsonify({'success': False, 'error': 'Plaid client_id not configured. Please configure in Settings first.'})

        if not config.get('secret'):
            logger.error("No secret found in configuration")
            return jsonify({'success': False, 'error': 'Plaid secret not configured. Please configure in Settings first.'})

        environment = config.get('environment', 'production')
        base_url = get_plaid_base_url(environment)

        logger.info(f"Using environment: {environment}")
        logger.info(f"Base URL: {base_url}")
        logger.info(f"Client ID: {config['client_id'][:10]}...")

        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'client_name': 'Plaid Admin Console',
            'country_codes': ['US'],
            'language': 'en',
            'user': {
                'client_user_id': 'user-' + str(uuid.uuid4())
            },
            'products': ['transactions']
        }

        # Add webhook URL if configured
        webhook_url = config.get('default_webhook_url')
        if webhook_url:
            payload['webhook'] = webhook_url
            logger.info(f"Adding webhook URL: {webhook_url}")
        else:
            logger.info("No webhook URL configured")

        logger.info(f"Making request to Plaid API: {base_url}/link/token/create")
        logger.debug(f"Payload keys: {list(payload.keys())}")

        response = requests.post(
            f'{base_url}/link/token/create',
            headers=headers,
            json=payload,
            timeout=10
        )

        logger.info(f"Plaid response status: {response.status_code}")
        logger.info(f"Response headers: {dict(response.headers)}")
        logger.debug(f"Response text (first 200 chars): {response.text[:200]}...")

        if response.status_code == 200:
            data = response.json()
            link_token = data.get('link_token', '')
            logger.info(f"Link token created successfully: {link_token[:20]}...")
            logger.info(f"Token expiration: {data.get('expiration', 'Not specified')}")

            return jsonify({'success': True, 'link_token': data['link_token']})
        else:
            logger.error(f"Plaid API returned error status: {response.status_code}")
            try:
                error_data = response.json()
                error_msg = error_data.get('error_message', 'Unknown error')
                error_code = error_data.get('error_code', 'UNKNOWN')
                error_type = error_data.get('error_type', 'UNKNOWN')

                logger.error(f"Plaid error code: {error_code}")
                logger.error(f"Plaid error type: {error_type}")
                logger.error(f"Plaid error message: {error_msg}")
                logger.error(f"Full error response: {error_data}")

                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error ({error_code}): {error_msg}"
                })
            except json.JSONDecodeError:
                logger.error(f"Could not parse error response as JSON: {response.text}")
                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error: HTTP {response.status_code} - {response.text[:100]}"
                })

    except requests.exceptions.Timeout:
        logger.error("Request to Plaid API timed out")
        return jsonify({'success': False, 'error': 'Request to Plaid API timed out'})
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Could not connect to Plaid API: {e}")
        return jsonify({'success': False, 'error': 'Could not connect to Plaid API'})
    except Exception as e:
        logger.error(f"Unexpected error creating link token: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'Failed to create link token: {str(e)}'})


@app.route('/settings', methods=['POST'])
def save_settings():
    """Save global Plaid settings"""
    logger.info("⚙️ Saving Plaid settings...")
    try:
        data = request.get_json()
        logger.info(f"📥 Received settings data keys: {list(data.keys()) if data else 'None'}")

        if not data:
            logger.error("❌ No settings data received")
            return jsonify({'success': False, 'error': 'No data received'})

        environment = data.get('environment', 'production')
        client_id = data.get('client_id', '')
        secret = data.get('secret', '')
        webhook_url = data.get('default_webhook_url', '')

        logger.info(f"🌐 Environment: {environment}")
        logger.info(f"🆔 Client ID: {client_id[:10]}..." if client_id else "🆔 No Client ID provided")
        logger.info(f"🔑 Secret provided: {bool(secret)}")
        logger.info(f"🪝 Webhook URL: {webhook_url}")

        config_data = {
            'environment': environment,
            'client_id': client_id,
            'secret': store_token(secret) if secret else None,
            'default_webhook_url': webhook_url,
            'updated_at': datetime.utcnow()
        }

        # Don't overwrite secret if not provided
        existing_config = db.global_config.find_one()
        if existing_config and not secret:
            logger.info("🔄 Keeping existing secret (not provided in update)")
            config_data['secret'] = existing_config.get('secret')

        logger.info("💾 Saving configuration to database...")
        db.global_config.replace_one({}, config_data, upsert=True)

        log_action('config_update', details={'environment': environment})
        logger.info("✅ Settings saved successfully")

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"❌ Error saving settings: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/test-connection', methods=['POST'])
def test_connection():
    """Test Plaid API connection"""
    logger.info("🔌 Testing Plaid API connection...")
    try:
        logger.info("🔍 Loading configuration for connection test...")
        config = db.global_config.find_one()

        if not config:
            logger.error("❌ No configuration found for connection test")
            return jsonify({'success': False, 'error': 'Missing Plaid configuration'})

        if not config.get('client_id'):
            logger.error("❌ No client_id found for connection test")
            return jsonify({'success': False, 'error': 'Missing client_id in configuration'})

        if not config.get('secret'):
            logger.error("❌ No secret found for connection test")
            return jsonify({'success': False, 'error': 'Missing secret in configuration'})

        environment = config.get('environment', 'production')
        base_url = get_plaid_base_url(environment)

        logger.info(f"🌐 Testing {environment} environment")
        logger.info(f"🔗 Testing URL: {base_url}")
        logger.info(f"🆔 Using Client ID: {config['client_id'][:10]}...")

        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'country_codes': ['US']
        }

        logger.info(f"📤 Making test request to: {base_url}/institutions/get")

        response = requests.post(
            f'{base_url}/institutions/get',
            headers=headers,
            json=payload,
            timeout=10
        )

        logger.info(f"📥 Test response status: {response.status_code}")
        logger.debug(f"📥 Test response headers: {dict(response.headers)}")

        if response.status_code == 200:
            data = response.json()
            institution_count = len(data.get('institutions', []))
            logger.info(f"✅ Connection test successful - {institution_count} institutions found")

            return jsonify({
                'success': True,
                'message': f'Connection successful! Found {institution_count} institutions in {environment} environment.'
            })
        else:
            logger.error(f"❌ Connection test failed with status: {response.status_code}")
            try:
                error_data = response.json()
                error_msg = error_data.get('error_message', 'Connection failed')
                error_code = error_data.get('error_code', 'UNKNOWN')

                logger.error(f"❌ Test error code: {error_code}")
                logger.error(f"❌ Test error message: {error_msg}")

                return jsonify({
                    'success': False,
                    'error': f"Plaid API Error: {error_msg}"
                })
            except json.JSONDecodeError:
                logger.error(f"❌ Could not parse test error response: {response.text}")
                return jsonify({
                    'success': False,
                    'error': f"Connection failed with HTTP {response.status_code}"
                })

    except requests.exceptions.Timeout:
        logger.error("⏰ Connection test timed out")
        return jsonify({'success': False, 'error': 'Request to Plaid API timed out'})
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 Could not connect to Plaid API during test: {e}")
        return jsonify({'success': False, 'error': 'Could not connect to Plaid API'})
    except Exception as e:
        logger.error(f"❌ Unexpected error during connection test: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/link-account', methods=['POST'])
def link_account():
    """Handle account linking from Plaid Link"""
    logger.info("🔗 Processing account linking request...")
    try:
        data = request.get_json()
        logger.info(f"📥 Received link data keys: {list(data.keys()) if data else 'None'}")

        if not data:
            logger.error("❌ No JSON data received")
            return jsonify({'success': False, 'error': 'No data received'})

        public_token = data.get('public_token')
        if not public_token:
            logger.error("❌ No public_token in request")
            return jsonify({'success': False, 'error': 'No public_token provided'})

        logger.info(f"🎫 Public token received: {public_token[:20]}...")
        logger.info(f"🏛️ Institution: {data.get('institution_name', 'Unknown')}")
        logger.info(f"🆔 Institution ID: {data.get('institution_id', 'Unknown')}")
        logger.info(f"💳 Accounts count: {len(data.get('accounts', []))}")

        logger.info("🔍 Loading Plaid configuration...")
        config = db.global_config.find_one()

        if not config:
            logger.error("❌ No Plaid configuration found")
            return jsonify({'success': False, 'error': 'No Plaid configuration found'})

        environment = config.get('environment', 'production')
        base_url = get_plaid_base_url(environment)

        logger.info(f"🌐 Using environment: {environment}")
        logger.info(f"🔗 Base URL: {base_url}")

        # Exchange public token for access token
        headers = {'Content-Type': 'application/json'}
        payload = {
            'client_id': config['client_id'],
            'secret': retrieve_token(config['secret']),
            'public_token': public_token
        }

        logger.info(f"📤 Exchanging public token at: {base_url}/item/public_token/exchange")
        logger.debug(f"📋 Exchange payload keys: {list(payload.keys())}")

        response = requests.post(
            f'{base_url}/item/public_token/exchange',
            headers=headers,
            json=payload,
            timeout=10
        )

        logger.info(f"📥 Exchange response status: {response.status_code}")
        logger.debug(f"📥 Exchange response (first 200 chars): {response.text[:200]}...")

        if response.status_code != 200:
            logger.error(f"❌ Token exchange failed with status: {response.status_code}")
            try:
                error_data = response.json()
                error_msg = error_data.get('error_message', 'Unknown error')
                error_code = error_data.get('error_code', 'UNKNOWN')

                logger.error(f"❌ Exchange error code: {error_code}")
                logger.error(f"❌ Exchange error message: {error_msg}")
                logger.error(f"❌ Full exchange error: {error_data}")

                return jsonify({
                    'success': False,
                    'error': f"Token exchange failed: {error_msg}"
                })
            except json.JSONDecodeError:
                logger.error(f"❌ Could not parse exchange error response: {response.text}")
                return jsonify({
                    'success': False,
                    'error': f"Token exchange failed with HTTP {response.status_code}"
                })

        exchange_data = response.json()
        logger.info(f"✅ Token exchange successful")
        logger.info(f"🆔 Item ID: {exchange_data.get('item_id', 'Unknown')}")
        logger.info(f"🔑 Access token received: {exchange_data.get('access_token', '')[:20]}...")

        # Store item data in database
        logger.info("💾 Storing item in database...")
        item_data = {
            'item_id': exchange_data['item_id'],
            'access_token': store_token(exchange_data['access_token']),
            'public_token': store_token(public_token),
            'institution_name': data.get('institution_name', 'Unknown Institution'),
            'institution_id': data.get('institution_id', 'unknown'),
            'date_linked': datetime.utcnow(),
            'last_sync': datetime.utcnow(),
            'status': 'active',
            'environment': environment,
            'config': {},
            'accounts': data.get('accounts', [])
        }

        logger.debug(f"📋 Item data keys: {list(item_data.keys())}")

        result = db.plaid_items.insert_one(item_data)
        logger.info(f"💾 Item stored with ID: {result.inserted_id}")

        log_action('link', target_item_id=exchange_data['item_id'])

        logger.info("✅ Account linking completed successfully")
        return jsonify({'success': True, 'id': str(result.inserted_id)})

    except requests.exceptions.Timeout:
        logger.error("⏰ Request to Plaid API timed out during token exchange")
        return jsonify({'success': False, 'error': 'Request to Plaid API timed out'})
    except requests.exceptions.ConnectionError as e:
        logger.error(f"🔌 Could not connect to Plaid API during token exchange: {e}")
        return jsonify({'success': False, 'error': 'Could not connect to Plaid API'})
    except Exception as e:
        logger.error(f"❌ Unexpected error linking account: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/unlink-account/<item_id>', methods=['POST'])
def unlink_account(item_id):
    """Unlink a Plaid account"""
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})
        if not item:
            return jsonify({'success': False, 'error': 'Item not found'})

        config = db.global_config.find_one()
        if config:
            environment = item.get('environment', config.get('environment', 'production'))
            base_url = get_plaid_base_url(environment)

            # Remove item from Plaid
            headers = {'Content-Type': 'application/json'}
            payload = {
                'client_id': config['client_id'],
                'secret': retrieve_token(config['secret']),
                'access_token': retrieve_token(item['access_token'])
            }

            requests.post(
                f'{base_url}/item/remove',
                headers=headers,
                json=payload,
                timeout=10
            )

        db.plaid_items.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': {'status': 'disconnected', 'unlinked_at': datetime.utcnow()}}
        )

        log_action('unlink', target_item_id=item.get('item_id'))
        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/refresh-token/<item_id>', methods=['POST'])
def refresh_token(item_id):
    """Refresh access token for an item"""
    try:
        from bson.objectid import ObjectId
        item = db.plaid_items.find_one({'_id': ObjectId(item_id)})
        if not item:
            return jsonify({'success': False, 'error': 'Item not found'})

        db.plaid_items.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': {'last_sync': datetime.utcnow(), 'status': 'active'}}
        )

        log_action('refresh', target_item_id=item.get('item_id'))
        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/webhook', methods=['POST'])
def webhook_handler():
    """Handle Plaid webhooks"""
    logger.info("🪝 Received Plaid webhook")
    try:
        data = request.get_json()

        if not data:
            logger.warning("⚠️ Webhook received with no JSON data")
            return jsonify({'status': 'error', 'message': 'No data received'})

        webhook_type = data.get('webhook_type', 'UNKNOWN')
        webhook_code = data.get('webhook_code', 'UNKNOWN')
        item_id = data.get('item_id', 'Unknown')

        logger.info(f"🪝 Webhook type: {webhook_type}")
        logger.info(f"🪝 Webhook code: {webhook_code}")
        logger.info(f"🪝 Item ID: {item_id}")
        logger.debug(f"🪝 Full webhook data: {data}")

        event_data = {
            'item_id': item_id,
            'event_type': f"{webhook_type}.{webhook_code}",
            'payload': data,
            'timestamp': datetime.utcnow()
        }

        logger.info("💾 Storing webhook event in database...")
        db.webhook_events.insert_one(event_data)
        logger.info("✅ Webhook event stored successfully")

        # Update item status based on webhook type
        if webhook_type == 'ITEM' and webhook_code == 'ERROR':
            logger.warning(f"⚠️ Item error detected for {item_id}, updating status")
            result = db.plaid_items.update_one(
                {'item_id': item_id},
                {'$set': {'status': 'error'}}
            )
            logger.info(f"📝 Updated {result.modified_count} items to error status")

        elif webhook_type == 'ITEM' and webhook_code == 'PENDING_EXPIRATION':
            logger.warning(f"⚠️ Item expiration pending for {item_id}, updating status")
            result = db.plaid_items.update_one(
                {'item_id': item_id},
                {'$set': {'status': 'expiring'}}
            )
            logger.info(f"📝 Updated {result.modified_count} items to expiring status")

        logger.info("✅ Webhook processed successfully")
        return jsonify({'status': 'received'})

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/health')
def health():
    """Health check endpoint"""
    logger.info("❤️ Health check requested")
    try:
        config = db.global_config.find_one() or {}

        # Test MongoDB connection
        db.command('ping')
        logger.info("✅ MongoDB health check passed")

        environment = config.get('environment', 'production')
        has_plaid_config = bool(config.get('client_id') and config.get('secret'))

        logger.info(f"🌐 Current environment: {environment}")
        logger.info(f"🔑 Has Plaid config: {has_plaid_config}")

        status = {
            'status': 'ok',
            'mongodb': 'connected',
            'environment': environment,
            'has_plaid_config': has_plaid_config,
            'timestamp': datetime.utcnow().isoformat()
        }

        logger.info("✅ Health check completed successfully")
        return jsonify(status)

    except Exception as e:
        logger.error(f"❌ Health check failed: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


if __name__ == '__main__':
    logger.info("Starting Plaid Admin Console...")
    logger.info("Dashboard: http://localhost:5000")
    logger.info("Settings: http://localhost:5000/settings")
    logger.info("Accounts: http://localhost:5000/accounts")
    logger.info("Transactions: http://localhost:5000/transactions")
    logger.info("Statements: http://localhost:5000/statements")
    logger.info("Export: http://localhost:5000/export")
    logger.info("Health: http://localhost:5000/health")
    logger.info("Logs: plaid_console.log")
    logger.info("=" * 50)

    print("Starting Plaid Admin Console...")
    print("Dashboard: http://localhost:5000")
    print("Settings: http://localhost:5000/settings")
    print("Accounts: http://localhost:5000/accounts")
    print("Transactions: http://localhost:5000/transactions")
    print("Statements: http://localhost:5000/statements")
    print("Export: http://localhost:5000/export")
    print("Health: http://localhost:5000/health")
    print("Logs: plaid_console.log")
    print("=" * 50)

    app.run(debug=True, host='0.0.0.0', port=5000)
