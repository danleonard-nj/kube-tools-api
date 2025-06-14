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

from flask import Flask, request, redirect, url_for, flash, jsonify, render_template_string
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
import uuid
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'abc123')

# MongoDB Configuration
MONGO_URI = 'mongodb://localhost:27017/?directConnection=true'
DATABASE_NAME = 'Google'
COLLECTION_NAME = 'EmailRule'

# Initialize MongoDB connection
try:
    client = MongoClient(MONGO_URI)
    db = client[DATABASE_NAME]
    rules_collection = db[COLLECTION_NAME]
    # Test connection
    client.admin.command('ping')
    print(f"✅ Connected to MongoDB at {MONGO_URI}")
except Exception as e:
    print(f"❌ Failed to connect to MongoDB: {e}")
    exit(1)

# Action type configurations
ACTION_TYPES = {'sms': {
    'name': 'SMS Alert',
    'fields': {
            'chat_gpt_include_summary': {'type': 'boolean', 'label': 'Include ChatGPT Summary'},
            'chat_gpt_prompt_template': {'type': 'text', 'label': 'ChatGPT Prompt Template'},
            'sms_additional_recipients': {'type': 'text', 'label': 'Additional Recipients (comma-separated phone numbers)'}
    }
},
    'bank-sync': {
        'name': 'Bank Sync',
        'fields': {
            'bank_sync_bank_key': {'type': 'text', 'label': 'Bank Key'},
            'bank_sync_alert_type': {'type': 'select', 'label': 'Alert Type', 'options': ['none', 'email', 'sms']}
        }
},
    'archive': {
        'name': 'Archive',
        'fields': {
            'archive_label': {'type': 'text', 'label': 'Archive Label'},
            'archive_folder': {'type': 'text', 'label': 'Archive Folder'},
            'archive_keep_unread': {'type': 'boolean', 'label': 'Keep Unread Status'}
        }
},
    'email-forward': {
        'name': 'Email Forward',
        'fields': {
            'email_to': {'type': 'email', 'label': 'Forward To Email'},
            'email_subject_prefix': {'type': 'text', 'label': 'Subject Prefix'},
            'email_include_original': {'type': 'boolean', 'label': 'Include Original Message'}
        }
},
    'webhook': {
        'name': 'Webhook',
        'fields': {
            'webhook_url': {'type': 'url', 'label': 'Webhook URL'},
            'webhook_method': {'type': 'select', 'label': 'HTTP Method', 'options': ['POST', 'PUT', 'PATCH']},
            'webhook_headers': {'type': 'json', 'label': 'Custom Headers (JSON)'}
        }
},
    'mark-read': {
        'name': 'Mark as Read',
        'fields': {
            'mark_read_apply_label': {'type': 'text', 'label': 'Apply Label (Optional)'},
            'mark_read_star': {'type': 'boolean', 'label': 'Add Star'}
        }
}
}


class RuleManager:
    """Handles CRUD operations for rules"""

    @staticmethod
    def get_all_rules():
        """Get all rules from MongoDB"""
        return list(rules_collection.find().sort('created_date', -1))

    @staticmethod
    def get_rule_by_id(rule_id: str):
        """Get a specific rule by rule_id"""
        return rules_collection.find_one({'rule_id': rule_id})

    @staticmethod
    def create_rule(rule_data: dict) -> str:
        """Create a new rule"""
        rule_data['rule_id'] = str(uuid.uuid4())
        rule_data['created_date'] = datetime.utcnow()
        rule_data['modified_date'] = datetime.utcnow()
        rule_data['count_processed'] = 0

        result = rules_collection.insert_one(rule_data)
        return rule_data['rule_id']

    @staticmethod
    def update_rule(rule_id: str, rule_data: dict) -> bool:
        """Update an existing rule"""
        rule_data['modified_date'] = datetime.utcnow()
        rule_data.pop('_id', None)
        rule_data.pop('rule_id', None)
        rule_data.pop('created_date', None)

        result = rules_collection.update_one(
            {'rule_id': rule_id},
            {'$set': rule_data}
        )
        return result.modified_count > 0

    @staticmethod
    def delete_rule(rule_id: str) -> bool:
        """Delete a rule"""
        result = rules_collection.delete_one({'rule_id': rule_id})
        return result.deleted_count > 0


# HTML Templates as strings
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Rules Admin{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        body {
            background-color: #f8f9fa;
        }
        .navbar-brand {
            font-weight: 600;
        }
        .card {
            box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
            border: 1px solid rgba(0, 0, 0, 0.125);
        }
        .action-badge {
            font-size: 0.75rem;
            padding: 0.375rem 0.75rem;
        }
        .rule-card {
            transition: transform 0.2s ease-in-out;
        }
        .rule-card:hover {
            transform: translateY(-2px);
        }
        .json-display {
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 0.375rem;
            padding: 1rem;
            font-family: 'Courier New', monospace;
            font-size: 0.875rem;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
        }
        .form-section {
            background-color: white;
            border-radius: 0.5rem;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            border: 1px solid #dee2e6;
        }
        .form-section h5 {
            color: #495057;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #e9ecef;
        }
        .sidebar {
            position: fixed;
            top: 0;
            left: -400px;
            width: 400px;
            height: 100vh;
            background: white;
            box-shadow: 2px 0 10px rgba(0,0,0,0.1);
            transition: left 0.3s ease;
            z-index: 1050;
            border-right: 1px solid #dee2e6;
        }
        .sidebar.open {
            left: 0;
        }
        .sidebar-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0,0,0,0.5);
            z-index: 1040;
            opacity: 0;
            visibility: hidden;
            transition: all 0.3s ease;
        }
        .sidebar-overlay.show {
            opacity: 1;
            visibility: visible;
        }
        .sidebar-header {
            padding: 1rem 1.5rem;
            border-bottom: 1px solid #dee2e6;
            background: #f8f9fa;
        }
        .sidebar-header .position-relative input {
            padding-right: 2.5rem;
        }
        .sidebar-content {
            height: calc(100vh - 140px);
            overflow-y: auto;
            padding: 1rem;
        }
        .rule-list-item {
            padding: 0.75rem;
            border: 1px solid #e9ecef;
            border-radius: 0.5rem;
            margin-bottom: 0.5rem;
            cursor: pointer;
            transition: all 0.2s ease;
            background: white;
        }
        .rule-list-item:hover {
            border-color: #0d6efd;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            transform: translateX(4px);
        }
        .rule-list-item.active {
            border-color: #0d6efd;
            background: #f8f9ff;
        }
        .rule-list-meta {
            font-size: 0.75rem;
            color: #6c757d;
            display: flex;
            justify-content: space-between;
            margin-top: 0.5rem;
        }
        .view-toggle {
            position: fixed;
            top: 100px;
            right: 20px;
            z-index: 1000;
        }
        .main-content {
            transition: margin-left 0.3s ease;
        }
        .main-content.sidebar-open {
            margin-left: 400px;
        }
        @media (max-width: 768px) {
            .sidebar {
                width: 320px;
                left: -320px;
            }
            .main-content.sidebar-open {
                margin-left: 0;
            }
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('index') }}">
                <i class="bi bi-gear-fill me-2"></i>Rules Admin
            </a>
            <div class="navbar-nav ms-auto">
                <a class="nav-link" href="{{ url_for('index') }}">
                    <i class="bi bi-house-fill me-1"></i>Dashboard
                </a>
                <a class="nav-link" href="{{ url_for('new_rule') }}">
                    <i class="bi bi-plus-circle-fill me-1"></i>New Rule
                </a>
            </div>
        </div>
    </nav>

    <!-- Sidebar -->
    <div class="sidebar" id="rulesSidebar">
        <div class="sidebar-header">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6 class="mb-0"><i class="bi bi-list-ul me-2"></i>Rules List</h6>
                <button class="btn btn-sm btn-outline-secondary" onclick="toggleSidebar()">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
            <div class="position-relative">
                <input type="text" class="form-control form-control-sm" id="searchRules" 
                       placeholder="Search rules..." onkeyup="filterRules(this.value)">
                <i class="bi bi-search position-absolute top-50 end-0 translate-middle-y me-2 text-muted"></i>
            </div>
        </div>
        <div class="sidebar-content" id="sidebarContent">
            <!-- Rules list will be loaded here -->
        </div>
    </div>

    <!-- Sidebar Overlay -->
    <div class="sidebar-overlay" id="sidebarOverlay" onclick="closeSidebar()"></div>

    <!-- View Toggle Button -->
    <div class="view-toggle">
        <button class="btn btn-primary btn-sm" onclick="toggleSidebar()" title="Toggle Rules List">
            <i class="bi bi-list"></i>
        </button>
    </div>

    <div class="main-content" id="mainContent">
        <div class="container mt-4">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show" role="alert">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            {% block content %}{% endblock %}
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let sidebarOpen = false;
        let rulesData = [];

        function toggleSidebar() {
            if (sidebarOpen) {
                closeSidebar();
            } else {
                openSidebar();
            }
        }

        function openSidebar() {
            document.getElementById('rulesSidebar').classList.add('open');
            document.getElementById('sidebarOverlay').classList.add('show');
            document.getElementById('mainContent').classList.add('sidebar-open');
            sidebarOpen = true;
            // Clear any existing search when opening
            document.getElementById('searchRules').value = '';
            loadRulesList();
        }

        function closeSidebar() {
            document.getElementById('rulesSidebar').classList.remove('open');
            document.getElementById('sidebarOverlay').classList.remove('show');
            document.getElementById('mainContent').classList.remove('sidebar-open');
            sidebarOpen = false;
        }

        function loadRulesList() {
            fetch('/api/rules')
                .then(response => response.json())
                .then(data => {
                    rulesData = data;
                    renderRulesList(data);
                })
                .catch(error => {
                    console.error('Error loading rules:', error);
                    document.getElementById('sidebarContent').innerHTML = 
                        '<div class="text-center text-muted py-4"><i class="bi bi-exclamation-triangle"></i><br>Error loading rules</div>';
                });
        }

        function renderRulesList(rules) {
            const content = document.getElementById('sidebarContent');
            
            if (rules.length === 0) {
                const isFiltered = document.getElementById('searchRules').value.trim() !== '';
                content.innerHTML = `
                    <div class="text-center text-muted py-4">
                        <i class="bi bi-${isFiltered ? 'search' : 'inbox'} display-6"></i>
                        <p class="mt-2">${isFiltered ? 'No matching rules found' : 'No rules found'}</p>
                        ${!isFiltered ? '<a href="/rule/new" class="btn btn-sm btn-primary">Create First Rule</a>' : ''}
                        ${isFiltered ? '<button class="btn btn-sm btn-outline-primary" onclick="clearSearch()">Clear Search</button>' : ''}
                    </div>
                `;
                return;
            }

            const rulesHtml = rules.map(rule => {
                const actionBadgeClass = getActionBadgeClass(rule.action);
                const createdDate = formatDate(rule.created_date);
                const modifiedDate = formatDate(rule.modified_date);
                
                return `
                    <div class="rule-list-item" onclick="selectRule('${rule.rule_id}')" data-rule-id="${rule.rule_id}">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <strong class="text-truncate" style="max-width: 200px;" title="${rule.name}">${rule.name}</strong>
                            <span class="badge ${actionBadgeClass} ms-2">${getActionName(rule.action)}</span>
                        </div>
                        <div class="small text-muted mb-2" title="${rule.description}">
                            ${rule.description.length > 60 ? rule.description.substring(0, 60) + '...' : rule.description}
                        </div>
                        <div class="rule-list-meta">
                            <span title="Created: ${createdDate}"><i class="bi bi-plus-circle me-1"></i>${formatRelativeDate(rule.created_date)}</span>
                            <span title="Modified: ${modifiedDate}"><i class="bi bi-pencil me-1"></i>${formatRelativeDate(rule.modified_date)}</span>
                        </div>
                        <div class="rule-list-meta">
                            <span><i class="bi bi-search me-1"></i>Max: ${rule.max_results}</span>
                            <span><i class="bi bi-check-circle me-1"></i>Processed: ${rule.count_processed}</span>
                        </div>
                    </div>
                `;
            }).join('');

            content.innerHTML = rulesHtml;
            
            // Highlight current rule if on rule page
            const currentRuleId = getCurrentRuleId();
            if (currentRuleId) {
                const currentItem = content.querySelector(`[data-rule-id="${currentRuleId}"]`);
                if (currentItem) {
                    currentItem.classList.add('active');
                }
            }
        }

        function filterRules(searchTerm) {
            const term = searchTerm.toLowerCase().trim();
            
            if (term === '') {
                // Show all rules if search is empty
                renderRulesList(rulesData);
                return;
            }
            
            // Filter rules based on name, description, query, and action
            const filteredRules = rulesData.filter(rule => {
                return rule.name.toLowerCase().includes(term) ||
                       rule.description.toLowerCase().includes(term) ||
                       rule.query.toLowerCase().includes(term) ||
                       rule.action.toLowerCase().includes(term) ||
                       getActionName(rule.action).toLowerCase().includes(term);
            });
            
            renderRulesList(filteredRules);
        }

        function clearSearch() {
            document.getElementById('searchRules').value = '';
            renderRulesList(rulesData);
        }

        function selectRule(ruleId) {
            window.location.href = `/rule/${ruleId}`;
        }

        function getCurrentRuleId() {
            const path = window.location.pathname;
            const match = path.match(/\/rule\/([^\/]+)$/);
            return match ? match[1] : null;
        }

        function getActionBadgeClass(action) {
            const classes = {
                'sms': 'bg-success',
                'bank-sync': 'bg-info', 
                'archive': 'bg-warning',
                'email-forward': 'bg-primary',
                'webhook': 'bg-secondary',
                'mark-read': 'bg-dark'
            };
            return classes[action] || 'bg-dark';
        }

        function getActionName(action) {
            const names = {
                'sms': 'SMS',
                'bank-sync': 'Bank',
                'archive': 'Archive',
                'email-forward': 'Email', 
                'webhook': 'Webhook',
                'mark-read': 'Read'
            };
            return names[action] || action;
        }

        function formatDate(dateValue) {
            if (!dateValue) return 'Unknown';
            
            let date;
            if (typeof dateValue === 'object' && dateValue.$date) {
                date = new Date(dateValue.$date);
            } else if (typeof dateValue === 'string') {
                date = new Date(dateValue);
            } else {
                date = new Date(dateValue);
            }
            
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        }

        function formatRelativeDate(dateValue) {
            if (!dateValue) return 'Unknown';
            
            let date;
            if (typeof dateValue === 'object' && dateValue.$date) {
                date = new Date(dateValue.$date);
            } else {
                date = new Date(dateValue);
            }
            
            const now = new Date();
            const diffMs = now - date;
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
            const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
            const diffMins = Math.floor(diffMs / (1000 * 60));
            
            if (diffDays > 0) {
                return `${diffDays}d ago`;
            } else if (diffHours > 0) {
                return `${diffHours}h ago`;
            } else if (diffMins > 0) {
                return `${diffMins}m ago`;
            } else {
                return 'Just now';
            }
        }

        // Close sidebar on escape key or clear search if sidebar is open and search has content
        document.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                if (sidebarOpen) {
                    const searchInput = document.getElementById('searchRules');
                    if (searchInput.value.trim() !== '') {
                        // Clear search first
                        clearSearch();
                        searchInput.focus();
                    } else {
                        // Close sidebar if search is empty
                        closeSidebar();
                    }
                }
            }
            // Focus search when opening sidebar with Ctrl+/ or Cmd+/
            if ((event.ctrlKey || event.metaKey) && event.key === '/') {
                event.preventDefault();
                if (!sidebarOpen) {
                    openSidebar();
                }
                setTimeout(() => {
                    document.getElementById('searchRules').focus();
                }, 100);
            }
        });

        // Auto-open sidebar on desktop if there are rules
        document.addEventListener('DOMContentLoaded', function() {
            if (window.innerWidth >= 992) { // Bootstrap lg breakpoint
                fetch('/api/rules')
                    .then(response => response.json())
                    .then(data => {
                        if (data.length > 0 && window.location.pathname === '/') {
                            setTimeout(() => openSidebar(), 500); // Small delay for smooth experience
                        }
                    })
                    .catch(error => console.error('Error checking rules:', error));
            }
        });
    </script>
    {% block scripts %}{% endblock %}
</body>
</html>
"""

INDEX_TEMPLATE = """
{% extends "base.html" %}

{% block title %}Dashboard - Rules Admin{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1 class="h3 mb-0">
        <i class="bi bi-list-ul me-2"></i>Rules Dashboard
    </h1>
    <div class="d-flex gap-2">
        <button class="btn btn-outline-secondary" onclick="toggleSidebar()" title="Toggle Rules List">
            <i class="bi bi-list me-1"></i>List View
        </button>
        <a href="{{ url_for('new_rule') }}" class="btn btn-primary">
            <i class="bi bi-plus-circle me-1"></i>Create New Rule
        </a>
    </div>
</div>

{% if rules %}
    <div class="d-flex justify-content-between align-items-center mb-3">
        <div class="text-muted">
            <i class="bi bi-info-circle me-1"></i>{{ rules|length }} rule{{ 's' if rules|length != 1 else '' }} found
        </div>
        <div class="d-flex align-items-center gap-2">
            <small class="text-muted">Sort by:</small>
            <select class="form-select form-select-sm" style="width: auto;" onchange="sortRules(this.value)">
                <option value="modified">Last Modified</option>
                <option value="created">Created Date</option>
                <option value="name">Name</option>
                <option value="action">Action Type</option>
            </select>
        </div>
    </div>

    <div class="row" id="rulesContainer">
        {% for rule in rules %}
        <div class="col-lg-6 col-xl-4 mb-4 rule-card-container" 
             data-name="{{ rule.name|lower }}"
             data-action="{{ rule.action }}"
             data-created="{{ rule.created_date }}"
             data-modified="{{ rule.modified_date }}">
            <div class="card rule-card h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-3">
                        <h5 class="card-title mb-0">{{ rule.name }}</h5>
                        <span class="badge action-badge 
                            {% if rule.action == 'sms' %}bg-success
                            {% elif rule.action == 'bank-sync' %}bg-info
                            {% elif rule.action == 'archive' %}bg-warning
                            {% elif rule.action == 'email-forward' %}bg-primary
                            {% elif rule.action == 'webhook' %}bg-secondary
                            {% elif rule.action == 'mark-read' %}bg-dark
                            {% else %}bg-dark{% endif %}">
                            {{ action_types.get(rule.action, {}).get('name', rule.action) }}
                        </span>
                    </div>
                    
                    <p class="card-text text-muted mb-3">{{ rule.description }}</p>
                    
                    <div class="small mb-2">
                        <strong>Query:</strong> 
                        <code class="text-break">{{ rule.query }}</code>
                    </div>
                    
                    <div class="row text-center border-top pt-3 mt-3">
                        <div class="col-6">
                            <div class="small text-muted">Max Results</div>
                            <div class="fw-bold">{{ rule.max_results }}</div>
                        </div>
                        <div class="col-6">
                            <div class="small text-muted">Processed</div>
                            <div class="fw-bold">{{ rule.count_processed }}</div>
                        </div>
                    </div>
                </div>
                
                <div class="card-footer bg-transparent">
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">
                            <i class="bi bi-clock me-1"></i>
                            Updated {{ rule.modified_date | datetime }}
                        </small>
                        <div class="btn-group btn-group-sm" role="group">
                            <a href="{{ url_for('view_rule', rule_id=rule.rule_id) }}" 
                               class="btn btn-outline-primary" title="View">
                                <i class="bi bi-eye"></i>
                            </a>
                            <a href="{{ url_for('edit_rule', rule_id=rule.rule_id) }}" 
                               class="btn btn-outline-secondary" title="Edit">
                                <i class="bi bi-pencil"></i>
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
{% else %}
    <div class="text-center py-5">
        <i class="bi bi-inbox display-1 text-muted"></i>
        <h3 class="mt-3 text-muted">No Rules Found</h3>
        <p class="text-muted">Get started by creating your first rule.</p>
        <a href="{{ url_for('new_rule') }}" class="btn btn-primary">
            <i class="bi bi-plus-circle me-1"></i>Create First Rule
        </a>
    </div>
{% endif %}

<script>
function sortRules(sortBy) {
    const container = document.getElementById('rulesContainer');
    const cards = Array.from(container.children);
    
    cards.sort((a, b) => {
        let aVal, bVal;
        
        switch(sortBy) {
            case 'name':
                aVal = a.dataset.name;
                bVal = b.dataset.name;
                return aVal.localeCompare(bVal);
            case 'action':
                aVal = a.dataset.action;
                bVal = b.dataset.action;
                return aVal.localeCompare(bVal);
            case 'created':
                aVal = new Date(a.dataset.created);
                bVal = new Date(b.dataset.created);
                return bVal - aVal; // Newest first
            case 'modified':
            default:
                aVal = new Date(a.dataset.modified);
                bVal = new Date(b.dataset.modified);
                return bVal - aVal; // Newest first
        }
    });
    
    // Re-append sorted elements
    cards.forEach(card => container.appendChild(card));
}
</script>
{% endblock %}
"""

VIEW_RULE_TEMPLATE = """
{% extends "base.html" %}

{% block title %}{{ rule.name }} - Rules Admin{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <nav aria-label="breadcrumb">
        <ol class="breadcrumb mb-0">
            <li class="breadcrumb-item"><a href="{{ url_for('index') }}">Dashboard</a></li>
            <li class="breadcrumb-item active">{{ rule.name }}</li>
        </ol>
    </nav>
    <div class="btn-group" role="group">
        <a href="{{ url_for('edit_rule', rule_id=rule.rule_id) }}" class="btn btn-primary">
            <i class="bi bi-pencil me-1"></i>Edit
        </a>
        <button type="button" class="btn btn-danger" data-bs-toggle="modal" data-bs-target="#deleteModal">
            <i class="bi bi-trash me-1"></i>Delete
        </button>
    </div>
</div>

<div class="row">
    <div class="col-lg-8">
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-info-circle me-2"></i>Rule Details
                </h5>
            </div>
            <div class="card-body">
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Name:</div>
                    <div class="col-sm-9">{{ rule.name }}</div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Description:</div>
                    <div class="col-sm-9">{{ rule.description }}</div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Query:</div>
                    <div class="col-sm-9"><code>{{ rule.query }}</code></div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Action:</div>
                    <div class="col-sm-9">
                        <span class="badge 
                            {% if rule.action == 'sms' %}bg-success
                            {% elif rule.action == 'bank-sync' %}bg-info
                            {% elif rule.action == 'archive' %}bg-warning
                            {% elif rule.action == 'email-forward' %}bg-primary
                            {% elif rule.action == 'webhook' %}bg-secondary
                            {% elif rule.action == 'mark-read' %}bg-dark
                            {% else %}bg-dark{% endif %}">
                            {{ action_types.get(rule.action, {}).get('name', rule.action) }}
                        </span>
                    </div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Max Results:</div>
                    <div class="col-sm-9">{{ rule.max_results }}</div>
                </div>
                <div class="row mb-3">
                    <div class="col-sm-3 fw-bold">Processed Count:</div>
                    <div class="col-sm-9">{{ rule.count_processed }}</div>
                </div>
            </div>
        </div>

        {% if rule.data %}
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-gear me-2"></i>Action Configuration
                </h5>
            </div>
            <div class="card-body">
                {% for key, value in rule.data.items() %}
                <div class="row mb-2">
                    <div class="col-sm-4 fw-bold">{{ key.replace('_', ' ').title() }}:</div>
                    <div class="col-sm-8">
                        {% if value is mapping %}
                            <div class="json-display">{{ value | json_pretty }}</div>
                        {% elif value is boolean %}
                            <span class="badge {{ 'bg-success' if value else 'bg-secondary' }}">
                                {{ 'Yes' if value else 'No' }}
                            </span>
                        {% else %}
                            <code>{{ value }}</code>
                        {% endif %}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
    </div>

    <div class="col-lg-4">
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-clock-history me-2"></i>Timestamps
                </h5>
            </div>
            <div class="card-body">
                <div class="mb-3">
                    <small class="text-muted d-block">Created</small>
                    <strong>{{ rule.created_date | datetime }}</strong>
                </div>
                <div class="mb-3">
                    <small class="text-muted d-block">Last Modified</small>
                    <strong>{{ rule.modified_date | datetime }}</strong>
                </div>
                <div class="mb-0">
                    <small class="text-muted d-block">Rule ID</small>
                    <code class="small">{{ rule.rule_id }}</code>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-code-square me-2"></i>Raw Data
                </h5>
            </div>
            <div class="card-body">
                <div class="json-display">{{ rule | json_pretty }}</div>
            </div>
        </div>
    </div>
</div>

<!-- Delete Confirmation Modal -->
<div class="modal fade" id="deleteModal" tabindex="-1">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header">
                <h5 class="modal-title">Confirm Delete</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
            </div>
            <div class="modal-body">
                <p>Are you sure you want to delete the rule <strong>"{{ rule.name }}"</strong>?</p>
                <p class="text-muted">This action cannot be undone.</p>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <form method="POST" action="{{ url_for('delete_rule', rule_id=rule.rule_id) }}" class="d-inline">
                    <button type="submit" class="btn btn-danger">Delete Rule</button>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

EDIT_RULE_TEMPLATE = """
{% extends "base.html" %}

{% block title %}{% if rule %}Edit {{ rule.name }}{% else %}New Rule{% endif %} - Rules Admin{% endblock %}

{% block content %}
<div class="mb-4">
    <nav aria-label="breadcrumb">
        <ol class="breadcrumb mb-0">
            <li class="breadcrumb-item"><a href="{{ url_for('index') }}">Dashboard</a></li>
            {% if rule %}
                <li class="breadcrumb-item"><a href="{{ url_for('view_rule', rule_id=rule.rule_id) }}">{{ rule.name }}</a></li>
                <li class="breadcrumb-item active">Edit</li>
            {% else %}
                <li class="breadcrumb-item active">New Rule</li>
            {% endif %}
        </ol>
    </nav>
</div>

<div class="row justify-content-center">
    <div class="col-lg-8">
        <form method="POST" action="{{ url_for('save_rule') }}">
            {% if rule %}
                <input type="hidden" name="rule_id" value="{{ rule.rule_id }}">
            {% endif %}

            <div class="form-section">
                <h5><i class="bi bi-info-circle me-2"></i>Basic Information</h5>
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label for="name" class="form-label">Rule Name *</label>
                        <input type="text" class="form-control" id="name" name="name" 
                               value="{{ rule.name if rule else '' }}" required>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label for="max_results" class="form-label">Max Results *</label>
                        <input type="number" class="form-control" id="max_results" name="max_results" 
                               value="{{ rule.max_results if rule else 10 }}" min="1" required>
                    </div>
                </div>
                <div class="mb-3">
                    <label for="description" class="form-label">Description</label>
                    <textarea class="form-control" id="description" name="description" rows="2">{{ rule.description if rule else '' }}</textarea>
                </div>
                <div class="mb-3">
                    <label for="query" class="form-label">Search Query *</label>
                    <input type="text" class="form-control" id="query" name="query" 
                           value="{{ rule.query if rule else '' }}" required>
                    <div class="form-text">Gmail search query (e.g., "from:example.com OR subject:alert")</div>
                </div>
            </div>

            <div class="form-section">
                <h5><i class="bi bi-lightning me-2"></i>Action Configuration</h5>
                <div class="mb-3">
                    <label for="action" class="form-label">Action Type *</label>
                    <select class="form-select" id="action" name="action" required onchange="updateActionFields()">
                        <option value="">Select an action...</option>
                        {% for action_key, action_config in action_types.items() %}
                            <option value="{{ action_key }}" 
                                    {% if rule and rule.action == action_key %}selected{% endif %}>
                                {{ action_config.name }}
                            </option>
                        {% endfor %}
                    </select>
                </div>

                {% for action_key, action_config in action_types.items() %}
                <div id="fields-{{ action_key }}" class="action-fields" style="display: none;">
                    <h6 class="text-muted mb-3">{{ action_config.name }} Settings</h6>
                    {% for field_name, field_config in action_config.fields.items() %}
                        <div class="mb-3">
                            <label for="{{ field_name }}" class="form-label">{{ field_config.label }}</label>
                            {% if field_config.type == 'boolean' %}
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="{{ field_name }}" name="{{ field_name }}"
                                           {% if rule and rule.data.get(field_name) %}checked{% endif %}>
                                    <label class="form-check-label" for="{{ field_name }}">
                                        Enable {{ field_config.label }}
                                    </label>
                                </div>
                            {% elif field_config.type == 'select' %}
                                <select class="form-select" id="{{ field_name }}" name="{{ field_name }}">
                                    {% for option in field_config.options %}
                                        <option value="{{ option }}"
                                                {% if rule and rule.data.get(field_name) == option %}selected{% endif %}>
                                            {{ option.title() }}
                                        </option>
                                    {% endfor %}
                                </select>
                            {% elif field_config.type == 'text' %}
                                <textarea class="form-control" id="{{ field_name }}" name="{{ field_name }}" rows="3">{{ rule.data.get(field_name, '') if rule else '' }}</textarea>
                            {% elif field_config.type == 'json' %}
                                <textarea class="form-control font-monospace" id="{{ field_name }}" name="{{ field_name }}" rows="4"
                                          placeholder='{"key": "value"}'>{% if rule and rule.data.get(field_name) %}{{ rule.data.get(field_name) | json_pretty }}{% endif %}</textarea>
                                <div class="form-text">Enter valid JSON</div>
                            {% else %}
                                <input type="{{ field_config.type }}" class="form-control" id="{{ field_name }}" name="{{ field_name }}"
                                       value="{{ rule.data.get(field_name, '') if rule else '' }}">
                            {% endif %}
                        </div>
                    {% endfor %}
                </div>
                {% endfor %}
            </div>

            <div class="d-flex justify-content-between">
                <a href="{% if rule %}{{ url_for('view_rule', rule_id=rule.rule_id) }}{% else %}{{ url_for('index') }}{% endif %}" 
                   class="btn btn-secondary">
                    <i class="bi bi-arrow-left me-1"></i>Cancel
                </a>
                <button type="submit" class="btn btn-primary">
                    <i class="bi bi-check-lg me-1"></i>Save Rule
                </button>
            </div>
        </form>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
function updateActionFields() {
    const actionSelect = document.getElementById('action');
    const actionFields = document.querySelectorAll('.action-fields');
    
    // Hide all action fields
    actionFields.forEach(field => {
        field.style.display = 'none';
    });
    
    // Show fields for selected action
    if (actionSelect.value) {
        const selectedFields = document.getElementById('fields-' + actionSelect.value);
        if (selectedFields) {
            selectedFields.style.display = 'block';
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    updateActionFields();
});
</script>
{% endblock %}
"""

# Custom template rendering function that handles template inheritance


def render_with_base(template_string, **kwargs):
    """Render template with base template inheritance simulation"""
    if "{% extends" in template_string:
        # Extract content blocks
        content_start = template_string.find("{% block content %}") + len("{% block content %}")
        content_end = template_string.find("{% endblock %}", content_start)
        content = template_string[content_start:content_end] if content_start > len("{% block content %}") - 1 else ""

        scripts_start = template_string.find("{% block scripts %}") + len("{% block scripts %}")
        scripts_end = template_string.find("{% endblock %}", scripts_start)
        scripts = template_string[scripts_start:scripts_end] if scripts_start > len("{% block scripts %}") - 1 else ""

        title_start = template_string.find("{% block title %}") + len("{% block title %}")
        title_end = template_string.find("{% endblock %}", title_start)
        title = template_string[title_start:title_end] if title_start > len("{% block title %}") - 1 else "Rules Admin"

        # Inject into base template
        final_template = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", content)
        final_template = final_template.replace("{% block scripts %}{% endblock %}", scripts)
        final_template = final_template.replace("{% block title %}Rules Admin{% endblock %}", title)

        return render_template_string(final_template, **kwargs)
    else:
        return render_template_string(template_string, **kwargs)


@app.route('/')
def index():
    """Main dashboard showing all rules"""
    rules = RuleManager.get_all_rules()
    return render_with_base(INDEX_TEMPLATE, rules=rules, action_types=ACTION_TYPES)


@app.route('/rule/new')
def new_rule():
    """Show form for creating a new rule"""
    return render_with_base(EDIT_RULE_TEMPLATE, rule=None, action_types=ACTION_TYPES)


@app.route('/rule/<rule_id>')
def view_rule(rule_id):
    """View a specific rule"""
    rule = RuleManager.get_rule_by_id(rule_id)
    if not rule:
        flash('Rule not found', 'error')
        return redirect(url_for('index'))
    return render_with_base(VIEW_RULE_TEMPLATE, rule=rule, action_types=ACTION_TYPES)


@app.route('/rule/<rule_id>/edit')
def edit_rule(rule_id):
    """Show form for editing a rule"""
    rule = RuleManager.get_rule_by_id(rule_id)
    if not rule:
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

    return render_with_base(EDIT_RULE_TEMPLATE, rule=rule, action_types=ACTION_TYPES)


@app.route('/rule/save', methods=['POST'])
def save_rule():
    """Save a new or updated rule"""
    try:
        rule_data = {
            'name': request.form['name'].strip(),
            'description': request.form['description'].strip(),
            'max_results': int(request.form['max_results']),
            'query': request.form['query'].strip(),
            'action': request.form['action'],
            'data': {}
        }        # Process action-specific data
        action_config = ACTION_TYPES.get(rule_data['action'], {})
        for field_name, field_config in action_config.get('fields', {}).items():
            if field_config['type'] == 'boolean':
                # For checkboxes, only set to true if checked, otherwise don't include the field
                if field_name in request.form:
                    rule_data['data'][field_name] = True
                # Don't include false values - let them be omitted
            elif field_name in request.form:
                value = request.form[field_name].strip()
                if value:  # Only include non-empty values
                    if field_config['type'] == 'json':
                        try:
                            rule_data['data'][field_name] = json.loads(value)
                        except json.JSONDecodeError:
                            flash(f'Invalid JSON for {field_config["label"]}', 'error')
                            return redirect(request.referrer)
                    elif field_name == 'sms_additional_recipients':
                        # Convert comma-separated string to list of strings
                        recipients = [phone.strip() for phone in value.split(',') if phone.strip()]
                        rule_data['data'][field_name] = recipients
                    else:
                        rule_data['data'][field_name] = value

        rule_id = request.form.get('rule_id')
        if rule_id:
            # Update existing rule
            if RuleManager.update_rule(rule_id, rule_data):
                flash('Rule updated successfully', 'success')
            else:
                flash('Failed to update rule', 'error')
        else:
            # Create new rule
            rule_id = RuleManager.create_rule(rule_data)
            flash('Rule created successfully', 'success')

        return redirect(url_for('view_rule', rule_id=rule_id))

    except Exception as e:
        flash(f'Error saving rule: {str(e)}', 'error')
        return redirect(request.referrer)


@app.route('/rule/<rule_id>/delete', methods=['POST'])
def delete_rule(rule_id):
    """Delete a rule"""
    if RuleManager.delete_rule(rule_id):
        flash('Rule deleted successfully', 'success')
    else:
        flash('Failed to delete rule', 'error')
    return redirect(url_for('index'))


@app.route('/api/rules')
def api_rules():
    """API endpoint to get all rules as JSON"""
    rules = RuleManager.get_all_rules()
    # Convert ObjectId to string for JSON serialization
    for rule in rules:
        rule['_id'] = str(rule['_id'])
    return jsonify(rules)


@app.route('/api/rule/<rule_id>')
def api_rule(rule_id):
    """API endpoint to get a specific rule as JSON"""
    rule = RuleManager.get_rule_by_id(rule_id)
    if rule:
        rule['_id'] = str(rule['_id'])
        return jsonify(rule)
    return jsonify({'error': 'Rule not found'}), 404

# Template filters


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


if __name__ == '__main__':
    print("🚀 Starting Flask MongoDB Rules Admin...")
    print("📋 Dashboard: http://localhost:5000")
    print("🔌 API: http://localhost:5000/api/rules")
    print("💡 Create your first rule to get started!")
    app.run(debug=True, host='0.0.0.0', port=5000)
