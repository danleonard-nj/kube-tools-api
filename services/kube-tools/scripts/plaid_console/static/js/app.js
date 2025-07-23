// Plaid Admin Console JavaScript

// Dark mode functionality
function initializeDarkMode() {
  // Check for saved theme preference or default to system preference
  const savedTheme = localStorage.getItem('theme');
  const systemPrefersDark = window.matchMedia(
    '(prefers-color-scheme: dark)'
  ).matches;

  if (savedTheme === 'dark' || (!savedTheme && systemPrefersDark)) {
    document.documentElement.classList.add('dark');
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) themeIcon.className = 'fas fa-sun';
  } else {
    document.documentElement.classList.remove('dark');
    const themeIcon = document.getElementById('theme-icon');
    if (themeIcon) themeIcon.className = 'fas fa-moon';
  }
}

function toggleDarkMode() {
  const isDark = document.documentElement.classList.contains('dark');
  const themeIcon = document.getElementById('theme-icon');

  if (isDark) {
    document.documentElement.classList.remove('dark');
    if (themeIcon) themeIcon.className = 'fas fa-moon';
    localStorage.setItem('theme', 'light');
  } else {
    document.documentElement.classList.add('dark');
    if (themeIcon) themeIcon.className = 'fas fa-sun';
    localStorage.setItem('theme', 'dark');
  }
}

// Initialize dark mode on page load
document.addEventListener('DOMContentLoaded', initializeDarkMode);

// Global notification system
window.showNotification = function (
  title,
  message,
  type = 'success'
) {
  const notifications = document.getElementById('notifications');
  if (!notifications) {
    console.warn('Notifications container not found');
    return;
  }

  const id = Date.now();

  const iconClass =
    type === 'success'
      ? 'fas fa-check-circle text-green-400'
      : type === 'error'
      ? 'fas fa-exclamation-circle text-red-400'
      : 'fas fa-info-circle text-blue-400';

  const notification = document.createElement('div');
  notification.className = 'notification';
  notification.innerHTML = `
        <div class="p-4">
            <div class="flex items-start space-x-3">
                <div class="flex-shrink-0">
                    <i class="${iconClass} text-xl"></i>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-gray-900 mb-1">${title}</p>
                    <p class="text-sm text-gray-500 break-words leading-relaxed">${message}</p>
                </div>
                <div class="flex-shrink-0">
                    <button onclick="removeNotification(${id})" 
                            class="bg-white rounded-md inline-flex text-gray-400 hover:text-gray-500 focus:outline-none p-1">
                        <i class="fas fa-times text-sm"></i>
                    </button>
                </div>
            </div>
        </div>
    `;

  notification.id = 'notification-' + id;
  notifications.appendChild(notification);

  // Animate in
  setTimeout(() => {
    notification.classList.add('show');
  }, 100);

  // Auto-remove after 5 seconds
  setTimeout(() => {
    removeNotification(id);
  }, 5000);
};

window.removeNotification = function (id) {
  const notification = document.getElementById('notification-' + id);
  if (notification) {
    notification.classList.remove('show');
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 300);
  }
};

// Plaid Link Integration
window.initializePlaidLink = async function (onSuccess) {
  try {
    // Get a real link token from our backend
    const tokenResponse = await fetch('/create-link-token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    const tokenData = await tokenResponse.json();

    if (!tokenData.success) {
      window.showNotification(
        'Error',
        tokenData.error || 'Failed to create link token',
        'error'
      );
      return null;
    }

    // Get environment from config endpoint
    const configResponse = await fetch('/get-plaid-config');
    const configData = await configResponse.json();
    const environment = configData.environment || 'production';

    console.log('Using Plaid environment:', environment);
    console.log(
      'Link token received:',
      tokenData.link_token ? 'Yes' : 'No'
    );

    const handler = Plaid.create({
      token: tokenData.link_token,
      onSuccess: function (public_token, metadata) {
        console.log('Plaid Link Success:', public_token, metadata);

        fetch('/link-account', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            public_token: public_token,
            item_id: metadata.link_session_id,
            institution_name: metadata.institution.name,
            institution_id: metadata.institution.institution_id,
            accounts: metadata.accounts,
          }),
        })
          .then((response) => response.json())
          .then((data) => {
            if (data.success) {
              window.showNotification(
                'Success',
                'Account linked successfully!'
              );
              if (onSuccess) onSuccess();
            } else {
              window.showNotification(
                'Error',
                data.error || 'Failed to link account',
                'error'
              );
            }
          })
          .catch((error) => {
            console.error('Error:', error);
            window.showNotification(
              'Error',
              'Network error occurred',
              'error'
            );
          });
      },
      onLoad: function () {
        console.log('Plaid Link loaded');
      },
      onExit: function (err, metadata) {
        if (err != null) {
          console.error('Plaid Link error:', err);
          window.showNotification(
            'Error',
            'Failed to connect account: ' +
              (err.error_message || 'Unknown error'),
            'error'
          );
        }
      },
      onEvent: function (eventName, metadata) {
        console.log('Plaid Link event:', eventName, metadata);
      },
      env: environment, // Use dynamic environment
      product: ['transactions'],
    });

    return handler;
  } catch (error) {
    console.error('Failed to initialize Plaid Link:', error);
    window.showNotification(
      'Error',
      'Failed to initialize Plaid Link',
      'error'
    );
    return null;
  }
};

// Global functions
window.linkNewAccount = async function () {
  const handler = await window.initializePlaidLink(() => {
    window.location.reload();
  });

  if (handler) {
    handler.open();
  }
};

window.refreshToken = async function (itemId) {
  try {
    const response = await fetch('/refresh-token/' + itemId, {
      method: 'POST',
    });

    const data = await response.json();

    if (data.success) {
      window.showNotification(
        'Success',
        'Token refreshed successfully'
      );
      window.location.reload();
    } else {
      window.showNotification(
        'Error',
        data.error || 'Failed to refresh token',
        'error'
      );
    }
  } catch (error) {
    window.showNotification(
      'Error',
      'Network error occurred',
      'error'
    );
  }
};

window.unlinkAccount = async function (itemId) {
  if (!confirm('Are you sure you want to unlink this account?')) {
    return;
  }

  try {
    const response = await fetch('/unlink-account/' + itemId, {
      method: 'POST',
    });

    const data = await response.json();

    if (data.success) {
      window.showNotification(
        'Success',
        'Account unlinked successfully'
      );
      window.location.reload();
    } else {
      window.showNotification(
        'Error',
        data.error || 'Failed to unlink account',
        'error'
      );
    }
  } catch (error) {
    window.showNotification(
      'Error',
      'Network error occurred',
      'error'
    );
  }
};

// Explorer functions
window.refreshAccountData = async function (itemId) {
  try {
    window.showNotification(
      'Info',
      'Refreshing account data...',
      'info'
    );

    const response = await fetch('/api/accounts/' + itemId + '/data');
    const data = await response.json();

    if (data.success) {
      window.showNotification(
        'Success',
        `Retrieved ${data.total_accounts} accounts`
      );
      setTimeout(() => window.location.reload(), 1000);
    } else {
      window.showNotification(
        'Error',
        data.error || 'Failed to refresh account data',
        'error'
      );
    }
  } catch (error) {
    window.showNotification(
      'Error',
      'Network error occurred',
      'error'
    );
  }
};

window.loadTransactions = async function (
  itemId,
  startDate,
  endDate
) {
  try {
    window.showNotification(
      'Info',
      'Loading transactions...',
      'info'
    );

    // Build query string if dates are provided
    let url = '/api/accounts/' + itemId + '/transactions';
    const params = [];
    if (startDate)
      params.push('start_date=' + encodeURIComponent(startDate));
    if (endDate)
      params.push('end_date=' + encodeURIComponent(endDate));
    if (params.length > 0) url += '?' + params.join('&');

    const response = await fetch(url);
    const data = await response.json();

    if (data.success) {
      window.showNotification(
        'Success',
        `Found ${data.total_transactions} transactions`
      );
      // You could display transactions in a modal or new section
      console.log('Transactions:', data.transactions);
    } else {
      window.showNotification(
        'Error',
        data.error || 'Failed to load transactions',
        'error'
      );
    }
  } catch (error) {
    window.showNotification(
      'Error',
      'Network error occurred',
      'error'
    );
  }
};

// Utility functions
window.copyToClipboard = async function (text, label = 'Text') {
  try {
    await navigator.clipboard.writeText(text);
    window.showNotification(
      'Success',
      `${label} copied to clipboard`
    );
  } catch (error) {
    window.showNotification(
      'Error',
      'Failed to copy to clipboard',
      'error'
    );
  }
};

window.formatCurrency = function (amount, currency = 'USD') {
  if (amount === null || amount === undefined) return 'N/A';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
  }).format(amount);
};

// Loading state helpers
window.setLoadingState = function (
  element,
  isLoading,
  originalText = null
) {
  if (isLoading) {
    element.disabled = true;
    element.classList.add('loading');
    if (originalText) {
      element.setAttribute('data-original-text', element.innerHTML);
      element.innerHTML =
        '<i class="fas fa-spinner fa-spin mr-2"></i>' + originalText;
    }
  } else {
    element.disabled = false;
    element.classList.remove('loading');
    if (element.hasAttribute('data-original-text')) {
      element.innerHTML = element.getAttribute('data-original-text');
      element.removeAttribute('data-original-text');
    }
  }
};

// Form validation helpers
window.validateForm = function (formElement) {
  const requiredFields = formElement.querySelectorAll('[required]');
  let isValid = true;

  requiredFields.forEach((field) => {
    if (!field.value.trim()) {
      field.classList.add('border-red-500');
      isValid = false;
    } else {
      field.classList.remove('border-red-500');
    }
  });

  return isValid;
};

// Keyboard shortcuts
document.addEventListener('keydown', function (event) {
  // Ctrl/Cmd + K for quick actions
  if ((event.ctrlKey || event.metaKey) && event.key === 'k') {
    event.preventDefault();
    // Could implement a command palette here
    console.log('Quick actions triggered');
  }

  // Escape to close modals/notifications
  if (event.key === 'Escape') {
    // Close all notifications
    const notifications = document.querySelectorAll(
      '[id^="notification-"]'
    );
    notifications.forEach((notification) => {
      const id = notification.id.replace('notification-', '');
      removeNotification(id);
    });
  }
});

// Enhanced error handling
window.handleApiError = function (error, context = '') {
  console.error(`API Error ${context}:`, error);

  if (error.name === 'TypeError' && error.message.includes('fetch')) {
    window.showNotification(
      'Network Error',
      'Unable to connect to server. Please check your connection.',
      'error'
    );
  } else if (error.status === 401) {
    window.showNotification(
      'Authorization Error',
      'Your session has expired. Please refresh the page.',
      'error'
    );
  } else if (error.status === 429) {
    window.showNotification(
      'Rate Limited',
      'Too many requests. Please wait a moment and try again.',
      'error'
    );
  } else {
    window.showNotification(
      'Error',
      error.message || 'An unexpected error occurred',
      'error'
    );
  }
};

// Auto-refresh functionality for live data
window.startAutoRefresh = function (callback, interval = 30000) {
  return setInterval(callback, interval);
};

window.stopAutoRefresh = function (intervalId) {
  if (intervalId) {
    clearInterval(intervalId);
  }
};

// Export functionality
window.exportData = function (data, filename, type = 'json') {
  let content, mimeType;

  switch (type) {
    case 'csv':
      content = convertToCSV(data);
      mimeType = 'text/csv';
      break;
    case 'json':
    default:
      content = JSON.stringify(data, null, 2);
      mimeType = 'application/json';
      break;
  }

  const blob = new Blob([content], { type: mimeType });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);

  window.showNotification(
    'Success',
    `${filename} downloaded successfully`
  );
};

function convertToCSV(data) {
  if (!Array.isArray(data) || data.length === 0) {
    return '';
  }

  const headers = Object.keys(data[0]);
  const csvContent = [
    headers.join(','),
    ...data.map((row) =>
      headers
        .map((header) => {
          const value = row[header];
          // Escape quotes and wrap in quotes if contains comma or quote
          if (
            typeof value === 'string' &&
            (value.includes(',') || value.includes('"'))
          ) {
            return `"${value.replace(/"/g, '""')}"`;
          }
          return value;
        })
        .join(',')
    ),
  ].join('\n');

  return csvContent;
}
