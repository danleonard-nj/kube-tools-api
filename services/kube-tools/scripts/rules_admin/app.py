#!/usr/bin/env python3
"""
Flask MongoDB Rules Admin Application - Single File Version
A complete admin interface for managing email processing rules stored in MongoDB.

Installation:
    pip install Flask pymongo python-dotenv

Environment Variables:
    MONGO_URI=mongodb://localhost:27017/
    DATABASE_NAME=rules_db
    COLLECTION_NAME=rules
    SECRET_KEY=your-secret-key-change-this

Usage:
    python app.py
    
Then open http://localhost:5000 in your browser.
"""

import json
import os
import uuid
from datetime import datetime
from functools import wraps
from urllib.parse import urljoin
import logging
import pickle

from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from msal import ConfidentialClientApplication
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from components.rule_manager import RuleManager

from pydantic import BaseModel, ValidationError

from components.utils import load_action_types, load_config
from models.app_config import AppConfig

# Pydantic config model


# def load_config():
#     try:
#         if not os.path.exists('config.json'):
#             raise FileNotFoundError("Application config.json file not found.")

#         with open('config.json', 'r') as file:
#             return AppConfig.model_validate_json(file.read())
#     except ValidationError as e:
#         print('Config validation error:', e)
#         exit(1)


# def load_action_types():
#     with open('./components/action_types.json', 'r') as f:
#         return json.load(f)

config = load_config()
ACTION_TYPES = load_action_types()

rule_manager = RuleManager(
    mongo_uri=config.MONGO_URI,
    database_name=config.DATABASE_NAME,
    collection_name=config.COLLECTION_NAME
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY


# Azure AD Config
AZURE_AD_CLIENT_ID = config.AZURE_AD_CLIENT_ID
AZURE_AD_CLIENT_SECRET = config.AZURE_AD_CLIENT_SECRET
AZURE_AD_TENANT_ID = config.AZURE_AD_TENANT_ID
AZURE_AD_AUTHORITY = config.AZURE_AD_AUTHORITY
AZURE_AD_REDIRECT_PATH = config.AZURE_AD_REDIRECT_PATH
AZURE_AD_SCOPE = config.AZURE_AD_SCOPE

# Google OAuth2 Config
GOOGLE_CLIENT_SECRETS_FILE = config.GOOGLE_CLIENT_SECRETS_FILE
GOOGLE_SCOPES = config.GOOGLE_SCOPES.split()
GOOGLE_REDIRECT_URI = config.GOOGLE_REDIRECT_URI

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False

# MSAL instance
msal_app = ConfidentialClientApplication(
    AZURE_AD_CLIENT_ID,
    authority=AZURE_AD_AUTHORITY,
    client_credential=AZURE_AD_CLIENT_SECRET
)


@app.route('/login')
def login():
    logger.info('Login route accessed')
    session['state'] = str(uuid.uuid4())
    auth_url = msal_app.get_authorization_request_url(
        [AZURE_AD_SCOPE],
        state=session['state'],
        redirect_uri=urljoin(request.url_root, AZURE_AD_REDIRECT_PATH)
    )
    logger.info('Generated Azure AD auth URL')
    return redirect(auth_url)


@app.route(AZURE_AD_REDIRECT_PATH)
def authorized():
    logger.info('Azure AD redirect path accessed')
    if request.args.get('state') != session.get('state'):
        logger.info('State mismatch in Azure AD callback')
        return redirect(url_for('index'))
    if 'error' in request.args:
        logger.error(f"Azure AD login error: {request.args['error_description']}")
        flash('Azure AD login error: ' + request.args['error_description'], 'error')
        return redirect(url_for('index'))
    code = request.args.get('code')
    if not code:
        logger.error('No code returned from Azure AD.')
        flash('No code returned from Azure AD.', 'error')
        return redirect(url_for('index'))
    result = msal_app.acquire_token_by_authorization_code(
        code,
        scopes=[AZURE_AD_SCOPE],
        redirect_uri=urljoin(request.url_root, AZURE_AD_REDIRECT_PATH)
    )
    logger.info('Azure AD token acquired')
    if 'id_token_claims' in result:
        logger.info(f"User {result['id_token_claims'].get('name')} authenticated via Azure AD")
        session['user'] = {
            'name': result['id_token_claims'].get('name'),
            'email': result['id_token_claims'].get('preferred_username'),
            'oid': result['id_token_claims'].get('oid')
        }
        flash('Logged in as ' + session['user']['name'], 'success')
    else:
        logger.error('Failed to authenticate with Azure AD.')
        flash('Failed to authenticate with Azure AD.', 'error')
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    logger.info('Logout route accessed')
    session.clear()
    logout_url = f"{AZURE_AD_AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={url_for('index', _external=True)}"
    logger.info('User logged out, redirecting to Azure logout URL')
    return redirect(logout_url)


# Decorator to require login


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            logger.info('User not in session, redirecting to login')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Example: protect the index page


@app.route('/')
@login_required
def index():
    logger.info('Index route accessed')
    rules = rule_manager.get_all_rules()
    logger.info(f"Loaded {len(rules)} rules for dashboard")
    return render_template('index.html', rules=rules, action_types=ACTION_TYPES, user=session.get('user'))


@app.route('/rule/new')
def new_rule():
    logger.info('New rule form accessed')
    return render_template('edit_rule.html', rule=None, action_types=ACTION_TYPES)


@app.route('/rule/<rule_id>')
def view_rule(rule_id):
    logger.info(f'View rule {rule_id} requested')
    rule = rule_manager.get_rule_by_id(rule_id)
    if not rule:
        logger.warning(f'Rule {rule_id} not found')
        flash('Rule not found', 'error')
        return redirect(url_for('index'))
    return render_template('view_rule.html', rule=rule, action_types=ACTION_TYPES)


@app.route('/rule/<rule_id>/edit')
def edit_rule(rule_id):
    logger.info(f'Edit rule {rule_id} requested')
    rule = rule_manager.get_rule_by_id(rule_id)
    if not rule:
        logger.warning(f'Rule {rule_id} not found for editing')
        flash('Rule not found', 'error')
        return redirect(url_for('index'))    # Convert sms_additional_recipients from list back to comma-separated string for display
    if rule and rule.get('data', {}).get('sms_additional_recipients'):
        recipients = rule['data']['sms_additional_recipients']
        if isinstance(recipients, list):
            # Already a list, convert to comma-separated string
            rule['data']['sms_additional_recipients'] = ', '.join(recipients)
        elif isinstance(recipients, str):
            # Check if it's a string representation of a list
            if recipients.startswith('[') and recipients.endswith(']'):
                try:
                    # Try to parse as JSON
                    parsed_recipients = json.loads(recipients)
                    if isinstance(parsed_recipients, list):
                        rule['data']['sms_additional_recipients'] = ', '.join(parsed_recipients)
                except json.JSONDecodeError:
                    # If it fails, leave as is (might already be comma-separated)
                    pass

    return render_template('edit_rule.html', rule=rule, action_types=ACTION_TYPES)


@app.route('/rule/save', methods=['POST'])
def save_rule():
    logger.info('Save rule POST request received')
    try:
        rule_data = {
            'name': request.form['name'].strip(),
            'description': request.form['description'].strip(),
            'max_results': int(request.form['max_results']),
            'query': request.form['query'].strip(),
            'action': request.form['action'],
            'data': {}
        }
        logger.info(f"Processing action type: {rule_data['action']}")
        action_config = ACTION_TYPES.get(rule_data['action'], {})
        for field_name, field_config in action_config.get('fields', {}).items():
            if field_config['type'] == 'boolean':
                if field_name in request.form:
                    rule_data['data'][field_name] = True
            elif field_name in request.form:
                value = request.form[field_name].strip()
                if value:
                    if field_config['type'] == 'json':
                        try:
                            rule_data['data'][field_name] = json.loads(value)
                        except json.JSONDecodeError:
                            logger.error(f'Invalid JSON for {field_config["label"]}')
                            flash(f'Invalid JSON for {field_config["label"]}', 'error')
                            return redirect(request.referrer)
                    elif field_name == 'sms_additional_recipients':
                        recipients = [phone.strip() for phone in value.split(',') if phone.strip()]
                        rule_data['data'][field_name] = recipients
                    else:
                        rule_data['data'][field_name] = value
        rule_id = request.form.get('rule_id')
        if rule_id:
            logger.info(f'Updating rule {rule_id}')
            if rule_manager.update_rule(rule_id, rule_data):
                logger.info(f'Rule {rule_id} updated successfully')
                flash('Rule updated successfully', 'success')
            else:
                logger.error(f'Failed to update rule {rule_id}')
                flash('Failed to update rule', 'error')
        else:
            logger.info('Creating new rule')
            rule_id = rule_manager.create_rule(rule_data)
            logger.info(f'Rule {rule_id} created successfully')
            flash('Rule created successfully', 'success')
        return redirect(url_for('view_rule', rule_id=rule_id))
    except Exception as e:
        logger.exception(f'Error saving rule: {str(e)}')
        flash(f'Error saving rule: {str(e)}', 'error')
        return redirect(request.referrer)


@app.route('/rule/<rule_id>/delete', methods=['POST'])
def delete_rule(rule_id):
    logger.info(f'Delete rule {rule_id} requested')
    if rule_manager.delete_rule(rule_id):
        logger.info(f'Rule {rule_id} deleted successfully')
        flash('Rule deleted successfully', 'success')
    else:
        logger.error(f'Failed to delete rule {rule_id}')
        flash('Failed to delete rule', 'error')
    return redirect(url_for('index'))


@app.route('/api/rules')
@login_required
def api_rules():
    logger.info('API: Get all rules')
    rules = rule_manager.get_all_rules()
    for rule in rules:
        rule['_id'] = str(rule['_id'])
    logger.info(f'API: Returning {len(rules)} rules')
    return jsonify(rules)


@app.route('/api/rule/<rule_id>')
@login_required
def api_rule(rule_id):
    logger.info(f'API: Get rule {rule_id}')
    rule = rule_manager.get_rule_by_id(rule_id)
    if rule:
        rule['_id'] = str(rule['_id'])
        logger.info(f'API: Rule {rule_id} found')
        return jsonify(rule)
    logger.warning(f'API: Rule {rule_id} not found')
    return jsonify({'error': 'Rule not found'}), 404


@app.template_filter('datetime')
def datetime_filter(value):
    """Format datetime for display"""
    if isinstance(value, dict) and '$date' in value:
        # Handle MongoDB date format
        return datetime.fromisoformat(value['$date'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S UTC')
    elif isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S UTC')
    return str(value)


@app.template_filter('json_pretty')
def json_pretty_filter(value):
    """Pretty print JSON"""
    try:
        return json.dumps(value, indent=2, default=str)
    except:
        return str(value)


@app.route('/google/login')
@login_required
def google_login():
    logger.info('Google login route accessed')
    flow = Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=GOOGLE_SCOPES,
        redirect_uri=urljoin(request.url_root, GOOGLE_REDIRECT_URI)
    )
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    session['google_oauth_state'] = state
    logger.info('Google OAuth2 flow started')
    return redirect(auth_url)


@app.route(GOOGLE_REDIRECT_URI)
@login_required
def google_oauth2callback():
    logger.info('Google OAuth2 callback accessed')
    state = session.get('google_oauth_state')
    flow = Flow.from_client_secrets_file(
        GOOGLE_CLIENT_SECRETS_FILE,
        scopes=GOOGLE_SCOPES,
        state=state,
        redirect_uri=urljoin(request.url_root, GOOGLE_REDIRECT_URI)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['google_credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    logger.info('Google account connected and credentials stored in session')
    flash('Google account connected!', 'success')
    return redirect(url_for('google_inbox'))


@app.route('/google/inbox')
@login_required
def google_inbox():
    logger.info('Google inbox route accessed')
    creds = None
    if 'google_credentials' in session:
        from google.oauth2.credentials import Credentials
        creds = Credentials(**session['google_credentials'])
    if not creds or not creds.valid:
        logger.warning('Google credentials are invalid or missing')
        flash('Google credentials are invalid or missing. Please log in again.', 'error')
        return redirect(url_for('google_login'))
    service = build('gmail', 'v1', credentials=creds)
    # Get the user's inbox messages (first 10)
    results = service.users().messages().list(userId='me', maxResults=10).execute()
    messages = results.get('messages', [])
    logger.info(f'Fetched {len(messages)} messages from Gmail inbox')
    email_data = []
    for msg in messages:
        # Get both metadata and snippet
        msg_detail = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='metadata',
            metadataHeaders=['subject', 'from', 'date']
        ).execute()
        headers = {h['name'].lower(): h['value'] for h in msg_detail['payload'].get('headers', [])}
        email_data.append({
            'id': msg['id'],
            'subject': headers.get('subject', ''),
            'from': headers.get('from', ''),
            'date': headers.get('date', ''),
            'snippet': msg_detail.get('snippet', '')
        })
    logger.info('Prepared email data for rendering')
    return render_template('google_inbox.html', emails=email_data, user=session.get('user'))


@app.route('/google')
@login_required
def google_section():
    logger.info('Google section landing page accessed')
    return render_template('google_section.html', user=session.get('user'))


@app.route('/google/disconnect', methods=['POST'])
@login_required
def google_disconnect():
    logger.info('Google disconnect requested')
    if 'google_credentials' in session:
        del session['google_credentials']
        logger.info('Google credentials removed from session')
        flash('Disconnected from Google successfully', 'success')
    return '', 204


@app.route('/google/email/<email_id>')
@login_required
def get_email_details(email_id):
    logger.info(f'Get email details for {email_id}')
    creds = None
    if 'google_credentials' in session:
        from google.oauth2.credentials import Credentials
        creds = Credentials(**session['google_credentials'])
    if not creds or not creds.valid:
        logger.warning('Google credentials are invalid or missing for email details')
        return jsonify({'error': 'Google credentials are invalid or missing'}), 401
    try:
        service = build('gmail', 'v1', credentials=creds)
        msg_detail = service.users().messages().get(
            userId='me',
            id=email_id,
            format='full'
        ).execute()
        logger.info('Fetched email details from Gmail API')
        headers = {h['name'].lower(): h['value'] for h in msg_detail['payload'].get('headers', [])}

        def extract_body(payload):
            body_text = ""
            body_html = ""
            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                        import base64
                        body_text = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    elif part['mimeType'] == 'text/html' and 'data' in part['body']:
                        import base64
                        body_html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    elif 'parts' in part:
                        nested_text, nested_html = extract_body(part)
                        if nested_text:
                            body_text = nested_text
                        if nested_html:
                            body_html = nested_html
            else:
                if payload['mimeType'] == 'text/plain' and 'data' in payload['body']:
                    import base64
                    body_text = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
                elif payload['mimeType'] == 'text/html' and 'data' in payload['body']:
                    import base64
                    body_html = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            return body_text, body_html
        body_text, body_html = extract_body(msg_detail['payload'])
        attachments = []
        if 'parts' in msg_detail['payload']:
            for part in msg_detail['payload']['parts']:
                if part.get('filename'):
                    attachment_id = part['body'].get('attachmentId')
                    attachments.append({
                        'filename': part['filename'],
                        'mimeType': part['mimeType'],
                        'size': part['body'].get('size', 0),
                        'attachmentId': attachment_id
                    })
        email_details = {
            'id': email_id,
            'subject': headers.get('subject', 'No Subject'),
            'from': headers.get('from', 'Unknown Sender'),
            'to': headers.get('to', 'Unknown Recipient'),
            'date': headers.get('date', 'Unknown Date'),
            'snippet': msg_detail.get('snippet', ''),
            'body_text': body_text,
            'body_html': body_html,
            'labels': msg_detail.get('labelIds', []),
            'attachments': attachments,
            'thread_id': msg_detail.get('threadId'),
            'size_estimate': msg_detail.get('sizeEstimate', 0)
        }
        logger.info('Prepared email details for response')
        return jsonify(email_details)
    except Exception as e:
        logger.exception(f'Failed to fetch email details: {str(e)}')
        return jsonify({'error': f'Failed to fetch email details: {str(e)}'}), 500


if __name__ == '__main__':
    logger.info('Starting Flask MongoDB Rules Admin...')
    print("🚀 Starting Flask MongoDB Rules Admin...")
    print("📋 Dashboard: http://localhost:5000")
    print("🔌 API: http://localhost:5000/api/rules")
    print("💡 Create your first rule to get started!")
    app.run(debug=True, host='0.0.0.0', port=5000)
