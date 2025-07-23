// Sidebar and rules logic
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
  document
    .getElementById('mainContent')
    .classList.add('sidebar-open');
  sidebarOpen = true;
  document.getElementById('searchRules').value = '';
  loadRulesList();
}

function closeSidebar() {
  document.getElementById('rulesSidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('show');
  document
    .getElementById('mainContent')
    .classList.remove('sidebar-open');
  sidebarOpen = false;
}

function loadRulesList() {
  fetch('/api/rules')
    .then((response) => response.json())
    .then((data) => {
      rulesData = data;
      renderRulesList(data);
    })
    .catch((error) => {
      console.error('Error loading rules:', error);
      document.getElementById('sidebarContent').innerHTML =
        '<div class="text-center text-muted py-4"><i class="bi bi-exclamation-triangle"></i><br>Error loading rules</div>';
    });
}

function renderRulesList(rules) {
  const content = document.getElementById('sidebarContent');
  if (rules.length === 0) {
    const isFiltered =
      document.getElementById('searchRules').value.trim() !== '';
    content.innerHTML = `
      <div class="text-center text-muted py-4">
        <i class="bi bi-${
          isFiltered ? 'search' : 'inbox'
        } display-6"></i>
        <p class="mt-2">${
          isFiltered ? 'No matching rules found' : 'No rules found'
        }</p>
        ${
          !isFiltered
            ? '<a href="/rule/new" class="btn btn-sm btn-primary">Create First Rule</a>'
            : ''
        }
        ${
          isFiltered
            ? '<button class="btn btn-sm btn-outline-primary" onclick="clearSearch()">Clear Search</button>'
            : ''
        }
      </div>
    `;
    return;
  }
  const rulesHtml = rules
    .map((rule) => {
      const actionBadgeClass = getActionBadgeClass(rule.action);
      const createdDate = formatDate(rule.created_date);
      const modifiedDate = formatDate(rule.modified_date);
      return `
        <div class="rule-list-item" onclick="selectRule('${
          rule.rule_id
        }')" data-rule-id="${rule.rule_id}">
          <div class="d-flex justify-content-between align-items-start mb-2">
            <strong class="text-truncate" style="max-width: 200px;" title="${
              rule.name
            }">${rule.name}</strong>
            <span class="badge ${actionBadgeClass} ms-2">${getActionName(
        rule.action
      )}</span>
          </div>
          <div class="small text-muted mb-2" title="${
            rule.description
          }">
            ${
              rule.description.length > 60
                ? rule.description.substring(0, 60) + '...'
                : rule.description
            }
          </div>
          <div class="rule-list-meta">
            <span title="Created: ${createdDate}"><i class="bi bi-plus-circle me-1"></i>${formatRelativeDate(
        rule.created_date
      )}</span>
            <span title="Modified: ${modifiedDate}"><i class="bi bi-pencil me-1"></i>${formatRelativeDate(
        rule.modified_date
      )}</span>
          </div>
          <div class="rule-list-meta">
            <span><i class="bi bi-search me-1"></i>Max: ${
              rule.max_results
            }</span>
            <span><i class="bi bi-check-circle me-1"></i>Processed: ${
              rule.count_processed
            }</span>
          </div>
        </div>
      `;
    })
    .join('');
  content.innerHTML = rulesHtml;
  const currentRuleId = getCurrentRuleId();
  if (currentRuleId) {
    const currentItem = content.querySelector(
      `[data-rule-id="${currentRuleId}"]`
    );
    if (currentItem) {
      currentItem.classList.add('active');
    }
  }
}

function filterRules(searchTerm) {
  const term = searchTerm.toLowerCase().trim();
  if (term === '') {
    renderRulesList(rulesData);
    return;
  }
  const filteredRules = rulesData.filter((rule) => {
    return (
      rule.name.toLowerCase().includes(term) ||
      rule.description.toLowerCase().includes(term) ||
      rule.query.toLowerCase().includes(term) ||
      rule.action.toLowerCase().includes(term) ||
      getActionName(rule.action).toLowerCase().includes(term)
    );
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
    sms: 'bg-success',
    'bank-sync': 'bg-info',
    archive: 'bg-warning',
    'email-forward': 'bg-primary',
    webhook: 'bg-secondary',
    'mark-read': 'bg-dark',
  };
  return classes[action] || 'bg-dark';
}

function getActionName(action) {
  const names = {
    sms: 'SMS',
    'bank-sync': 'Bank',
    archive: 'Archive',
    'email-forward': 'Email',
    webhook: 'Webhook',
    'mark-read': 'Read',
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

// Keyboard shortcuts and sidebar auto-open
// ...existing code for keydown and DOMContentLoaded events...

// Dark mode toggle logic
function setupDarkModeToggle() {
  const themeToggle = document.getElementById('themeToggle');
  const prefersDark = window.matchMedia(
    '(prefers-color-scheme: dark)'
  ).matches;
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
    document.body.classList.add('dark-mode');
  }
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      document.body.classList.toggle('dark-mode');
      localStorage.setItem(
        'theme',
        document.body.classList.contains('dark-mode')
          ? 'dark'
          : 'light'
      );
    });
  }
}

document.addEventListener('DOMContentLoaded', function () {
  // Keyboard shortcuts for sidebar
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      if (sidebarOpen) {
        const searchInput = document.getElementById('searchRules');
        if (searchInput.value.trim() !== '') {
          clearSearch();
          searchInput.focus();
        } else {
          closeSidebar();
        }
      }
    }
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
  // Remove auto-open sidebar on desktop
  setupDarkModeToggle();
});
