/**
 * Email Management JavaScript
 * Handles email list display, date formatting, and email detail panel
 */

// Email functionality initialization
document.addEventListener('DOMContentLoaded', function () {
  if (document.querySelector('.email-row')) {
    formatEmailDates();
    updateLastUpdatedTime();
  }
});

/**
 * Format email dates to relative time format
 */
function formatEmailDates() {
  const dateElements = document.querySelectorAll('.email-date-text');
  dateElements.forEach(function (element) {
    const dateString = element.textContent.trim();
    if (dateString && dateString !== 'Unknown') {
      try {
        const date = new Date(dateString);
        element.textContent = formatRelativeDate(date);
      } catch (e) {
        // Keep original text if parsing fails
      }
    }
  });
}

/**
 * Convert date to relative format (e.g., "2h ago", "Yesterday")
 */
function formatRelativeDate(date) {
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

  if (diffDays < 1) {
    return date.toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  } else if (diffDays === 1) {
    return 'Yesterday';
  } else if (diffDays < 7) {
    return diffDays + 'd ago';
  } else {
    return date.toLocaleDateString();
  }
}

/**
 * Update the last updated timestamp
 */
function updateLastUpdatedTime() {
  const lastUpdatedElement = document.getElementById('lastUpdated');
  if (lastUpdatedElement) {
    lastUpdatedElement.textContent = new Date().toLocaleTimeString();
  }
}

/**
 * View email - wrapper for openEmailPanel
 */
function viewEmail(emailId) {
  openEmailPanel(emailId);
}

/**
 * Open the email detail modal
 */
function openEmailPanel(emailId, rowElement) {
  // Highlight the selected row
  document.querySelectorAll('.email-row').forEach((row) => {
    row.classList.remove('email-selected');
  });
  if (rowElement) {
    rowElement.classList.add('email-selected');
  }

  // Show modal with loading state
  const panel = document.getElementById('emailPanel');
  if (panel) {
    panel.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Prevent modal content from closing when clicked
    const modalContent = panel.querySelector('.email-panel-content');
    if (modalContent) {
      modalContent.addEventListener('click', function (e) {
        e.stopPropagation();
      });
    }

    // Load email details
    setTimeout(() => {
      loadEmailDetails(emailId);
    }, 300);
  }
}

/**
 * Close the email detail modal
 */
function closeEmailPanel() {
  const panel = document.getElementById('emailPanel');
  if (panel) {
    panel.classList.remove('open');
    document.body.style.overflow = '';

    // Remove selection highlight
    document.querySelectorAll('.email-row').forEach((row) => {
      row.classList.remove('email-selected');
    });

    // Reset modal content after animation
    setTimeout(() => {
      const panelBody = document.getElementById('emailPanelBody');
      if (panelBody) {
        panelBody.innerHTML = `
          <div class="text-center py-5">
            <div class="spinner-border text-primary" role="status">
              <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-3 text-muted">Loading email details...</p>
          </div>
        `;
      }
    }, 300);
  }
}

/**
 * Load email details from the backend API
 */
function loadEmailDetails(emailId) {
  // Fetch email details from the backend
  fetch(`/google/email/${emailId}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then((emailData) => {
      renderEmailDetails(emailData);
    })
    .catch((error) => {
      console.error('Error loading email details:', error);
      renderEmailError(error.message);
    });
}

/**
 * Render error message in email panel
 */
function renderEmailError(errorMessage) {
  const panelBody = document.getElementById('emailPanelBody');
  if (!panelBody) return;

  panelBody.innerHTML = `
    <div class="text-center py-5">
      <i class="bi bi-exclamation-triangle text-warning mb-3" style="font-size: 3rem;"></i>
      <h5 class="text-muted">Failed to Load Email</h5>
      <p class="text-muted">${errorMessage}</p>
      <button class="btn btn-outline-primary" onclick="closeEmailPanel()">
        <i class="bi bi-arrow-left me-1"></i>Back to Inbox
      </button>
    </div>
  `;
}

/**
 * Render email details in the panel
 */
function renderEmailDetails(emailData) {
  const panelBody = document.getElementById('emailPanelBody');
  if (!panelBody) return;

  const formattedDate = new Date(emailData.date).toLocaleString();

  // Use HTML body if available, otherwise fall back to text body
  const emailContent =
    emailData.body_html ||
    (emailData.body_text
      ? `<pre style="white-space: pre-wrap; font-family: inherit;">${emailData.body_text}</pre>`
      : '<p class="text-muted">No content available</p>');

  // Format file size
  function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (
      parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
    );
  }

  panelBody.innerHTML = `
    <div class="email-detail-header mb-4">
      <h6 class="email-detail-subject">${emailData.subject}</h6>
      <div class="email-detail-meta">
        <div class="d-flex align-items-center mb-2">
          <i class="bi bi-person-circle me-2 text-muted"></i>
          <div>
            <strong>From:</strong> ${emailData.from}
          </div>
        </div>
        <div class="d-flex align-items-center mb-2">
          <i class="bi bi-envelope me-2 text-muted"></i>
          <div>
            <strong>To:</strong> ${emailData.to}
          </div>
        </div>
        <div class="d-flex align-items-center mb-2">
          <i class="bi bi-calendar me-2 text-muted"></i>
          <div>
            <strong>Date:</strong> ${formattedDate}
          </div>
        </div>
        ${
          emailData.labels && emailData.labels.length > 0
            ? `
          <div class="d-flex align-items-center mb-2">
            <i class="bi bi-tags me-2 text-muted"></i>
            <div>
              ${emailData.labels
                .map(
                  (label) =>
                    `<span class="badge bg-secondary me-1">${label}</span>`
                )
                .join('')}
            </div>
          </div>
        `
            : ''
        }
        ${
          emailData.snippet
            ? `
          <div class="d-flex align-items-start mb-2">
            <i class="bi bi-chat-quote me-2 text-muted"></i>
            <div>
              <strong>Snippet:</strong> <em>${emailData.snippet}</em>
            </div>
          </div>
        `
            : ''
        }
      </div>
    </div>

    <div class="email-detail-content mb-4">
      <h6 class="border-bottom pb-2 mb-3">
        <i class="bi bi-file-text me-2"></i>Content
      </h6>
      <div class="email-content-body">
        ${emailContent}
      </div>
    </div>

    ${
      emailData.attachments && emailData.attachments.length > 0
        ? `
        <div class="email-detail-attachments mb-4">
          <h6 class="border-bottom pb-2 mb-3">
            <i class="bi bi-paperclip me-2"></i>Attachments (${
              emailData.attachments.length
            })
          </h6>
          <div class="attachment-list">
            ${emailData.attachments
              .map(
                (attachment) => `
              <div class="attachment-item d-flex align-items-center p-3 border rounded mb-2">
                <i class="bi bi-file-earmark text-primary me-3" style="font-size: 1.5rem;"></i>
                <div class="flex-grow-1">
                  <div class="attachment-name fw-medium">${
                    attachment.filename
                  }</div>
                  <div class="attachment-info text-muted small">${formatFileSize(
                    attachment.size
                  )} • ${attachment.mimeType}</div>
                </div>
                <button class="btn btn-sm btn-outline-primary" onclick="downloadAttachment('${
                  emailData.id
                }', '${attachment.attachmentId}', '${
                  attachment.filename
                }')">
                  <i class="bi bi-download"></i>
                </button>
              </div>
            `
              )
              .join('')}
          </div>
        </div>
      `
        : ''
    }

    <div class="email-detail-actions">
      <h6 class="border-bottom pb-2 mb-3">
        <i class="bi bi-gear me-2"></i>Actions
      </h6>
      <div class="d-flex gap-2 flex-wrap">
        <button class="btn btn-primary btn-sm">
          <i class="bi bi-reply me-1"></i>Reply
        </button>
        <button class="btn btn-outline-primary btn-sm">
          <i class="bi bi-reply-all me-1"></i>Reply All
        </button>
        <button class="btn btn-outline-secondary btn-sm">
          <i class="bi bi-arrow-right me-1"></i>Forward
        </button>
        <button class="btn btn-outline-warning btn-sm">
          <i class="bi bi-archive me-1"></i>Archive
        </button>
        <button class="btn btn-outline-danger btn-sm">
          <i class="bi bi-trash me-1"></i>Delete
        </button>
      </div>
    </div>
  `;
}

/**
 * Download email attachment (placeholder for now)
 */
function downloadAttachment(emailId, attachmentId, filename) {
  // TODO: Implement attachment download
  alert(
    `Download functionality for "${filename}" will be implemented next.`
  );
}

// Event listeners
document.addEventListener('keydown', function (e) {
  if (
    e.key === 'Escape' &&
    document.getElementById('emailPanel') &&
    document.getElementById('emailPanel').classList.contains('open')
  ) {
    closeEmailPanel();
  }
});
