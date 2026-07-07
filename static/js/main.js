document.addEventListener('DOMContentLoaded', function () {
  // Sidebar Toggle
  const toggleSidebar = document.querySelector('#sidebarCollapse');
  const sidebar = document.querySelector('.sidebar');
  if (toggleSidebar && sidebar) {
    toggleSidebar.addEventListener('click', function () {
      sidebar.classList.toggle('show');
    });
  }

  // --- Real-time Sync Hub ---
  let eventSource = null;

  function initSSE() {
    if (!!window.EventSource) {
      eventSource = new EventSource('/api/events');

      eventSource.onmessage = function (e) {
        try {
          const data = JSON.parse(e.data);
          
          if (data.type === 'connected') {
            console.log('SSE Real-Time Sync Connected');
            return;
          }

          if (data.type === 'SYNC') {
            console.log('Sync event received:', data.event_type);
            triggerDashboardUpdate();
          }

          if (data.type === 'NOTIFICATION') {
            showToastNotification(data.title, data.message);
            triggerDashboardUpdate();
          }

          if (data.type === 'ACTIVITY_LOG') {
            appendActivityLog(data);
          }
        } catch (err) {
          console.error('Error parsing SSE event data:', err);
        }
      };

      eventSource.onerror = function (err) {
        console.warn('SSE Error occurred, attempting fallback to short polling...', err);
        if (eventSource) {
          eventSource.close();
        }
        // Fallback: Start Polling
        startPolling();
      };
    } else {
      // EventSource not supported: Start Polling immediately
      startPolling();
    }
  }

  let pollInterval = null;
  function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    // Poll every 3 seconds
    pollInterval = setInterval(triggerDashboardUpdate, 3000);
  }

  // Fetch updated dashboard numbers & notification badges
  async function triggerDashboardUpdate() {
    try {
      const res = await fetch('/api/sync');
      const data = await res.json();
      if (data.success) {
        updateDOMStats(data);
      }
    } catch (err) {
      console.warn('Sync update failed', err);
    }
  }

  // Dynamically update stats values in HTML page without reloading
  function updateDOMStats(data) {
    // Admin Dashboard Elements
    const adminTotalBooks = document.getElementById('stat-total-books');
    const adminAvailableBooks = document.getElementById('stat-available-books');
    const adminTotalIssued = document.getElementById('stat-total-issued');
    const adminTotalReturned = document.getElementById('stat-total-returned');
    const adminTotalStudents = document.getElementById('stat-total-students');
    const adminOverdueBooks = document.getElementById('stat-overdue-books');
    const adminTotalFine = document.getElementById('stat-total-fine');
    const adminPendingRequests = document.getElementById('stat-pending-requests');

    if (adminTotalBooks && data.total_books !== undefined) adminTotalBooks.innerText = data.total_books;
    if (adminAvailableBooks && data.available_books !== undefined) adminAvailableBooks.innerText = data.available_books;
    if (adminTotalIssued && data.total_issued !== undefined) adminTotalIssued.innerText = data.total_issued;
    if (adminTotalReturned && data.total_returned !== undefined) adminTotalReturned.innerText = data.total_returned;
    if (adminTotalStudents && data.total_students !== undefined) adminTotalStudents.innerText = data.total_students;
    if (adminOverdueBooks && data.overdue_books !== undefined) adminOverdueBooks.innerText = data.overdue_books;
    if (adminTotalFine && data.total_fine !== undefined) adminTotalFine.innerText = `₹${parseFloat(data.total_fine).toFixed(2)}`;
    if (adminPendingRequests && data.pending_requests !== undefined) {
      adminPendingRequests.innerText = data.pending_requests;
      const requestBadge = document.getElementById('sidebar-badge-requests');
      if (requestBadge) {
        requestBadge.innerText = data.pending_requests;
        requestBadge.style.display = data.pending_requests > 0 ? 'inline-block' : 'none';
      }
    }

    // Student Dashboard Elements
    const studentFineDue = document.getElementById('stat-student-fine');
    const studentPendingReqs = document.getElementById('stat-student-pending');
    
    if (studentFineDue && data.fine_due !== undefined) {
      studentFineDue.innerText = `₹${parseFloat(data.fine_due).toFixed(2)}`;
    }
    if (studentPendingReqs && data.pending_requests !== undefined) {
      studentPendingReqs.innerText = data.pending_requests;
    }

    // Notification Badge Indicator
    const notifBadge = document.getElementById('notif-badge-indicator');
    if (notifBadge && data.unread_notifications !== undefined) {
      notifBadge.style.display = data.unread_notifications > 0 ? 'block' : 'none';
    }
  }

  // Appends new activity log entry to live list (if admin is on Dashboard page)
  function appendActivityLog(data) {
    const listContainer = document.getElementById('live-activity-list');
    if (listContainer) {
      const li = document.createElement('li');
      li.className = 'list-group-item d-flex justify-content-between align-items-start border-0 ps-0 mb-3';
      
      const badgeClass = data.user_type === 'Admin' ? 'bg-danger-grad' : 'bg-primary-grad';
      
      li.innerHTML = `
        <div class="ms-2 me-auto">
          <div class="fw-bold">${escapeHtml(data.user_name)} <span class="badge ${badgeClass} ms-1" style="font-size:0.65rem;">${data.user_type}</span></div>
          <span style="font-size:0.9rem; color:#475569;">${escapeHtml(data.action)}: ${escapeHtml(data.details)}</span>
        </div>
        <span class="text-muted" style="font-size:0.8rem;">${data.timestamp}</span>
      `;
      
      listContainer.insertBefore(li, listContainer.firstChild);
      
      // Keep last 10 logs
      if (listContainer.children.length > 10) {
        listContainer.removeChild(listContainer.lastChild);
      }
    }
  }

  // Show visual toast notification popup on screen
  function showToastNotification(title, message) {
    const container = document.getElementById('toast-container');
    if (!container) {
      // Create toast container dynamically if not present
      const tc = document.createElement('div');
      tc.id = 'toast-container';
      tc.className = 'toast-container position-fixed bottom-0 end-0 p-3';
      tc.style.zIndex = '9999';
      document.body.appendChild(tc);
    }
    
    const toastId = 'toast-' + Date.now();
    const html = `
      <div id="${toastId}" class="toast align-items-center text-white bg-dark border-0 shadow-lg" role="alert" aria-live="assertive" aria-atomic="true" style="border-radius:12px; background: rgba(15, 23, 42, 0.9) !important; backdrop-filter:blur(8px);">
        <div class="d-flex">
          <div class="toast-body">
            <strong class="d-block text-info mb-1"><i class="fas fa-bell me-2"></i>${escapeHtml(title)}</strong>
            <span>${escapeHtml(message)}</span>
          </div>
          <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
      </div>
    `;
    
    document.getElementById('toast-container').insertAdjacentHTML('beforeend', html);
    const toastEl = document.getElementById(toastId);
    const bsToast = new bootstrap.Toast(toastEl, { delay: 6000 });
    bsToast.show();
    
    // Play alert sound quietly
    try {
      const snd = new Audio('https://assets.codepen.io/605876/click.mp3');
      snd.volume = 0.2;
      snd.play();
    } catch (e) {}
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  // Notification Clear Action
  const clearNotifBtn = document.getElementById('mark-all-read-btn');
  if (clearNotifBtn) {
    clearNotifBtn.addEventListener('click', async function (e) {
      e.preventDefault();
      try {
        const res = await fetch('/notifications/read-all', {
          method: 'POST',
          headers: { 'X-CSRFToken': getCookie('csrf_token') }
        });
        const data = await res.json();
        if (data.success) {
          window.location.reload();
        }
      } catch (err) {
        console.error(err);
      }
    });
  }

  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // Init SSE Hub
  initSSE();
  // Fetch initial stats
  triggerDashboardUpdate();
});

// Custom AI-themed Toast Notification function
window.showAIToast = function(message, type = 'success') {
  let container = document.querySelector('.toast-container-custom');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container-custom';
    document.body.appendChild(container);
  }
  
  const toast = document.createElement('div');
  const isError = type === 'error' || type === 'danger';
  const isWarning = type === 'warning';
  
  toast.className = `toast-custom ${isError ? 'error-toast' : isWarning ? 'warning-toast' : 'success-toast'}`;
  
  let titleText = 'Success';
  if (isError) {
    titleText = 'Error';
  } else if (isWarning) {
    titleText = 'Warning';
  }
  
  toast.innerHTML = `
    <div class="toast-content-wrapper">
      <div class="toast-title" style="font-weight:700; font-size:0.85rem; letter-spacing:0.05em; text-transform:uppercase;">${titleText}</div>
      <div class="toast-msg" style="font-size:0.9rem; margin-top:2px;">${message}</div>
    </div>
    <button type="button" class="btn-close btn-close-white ms-auto" aria-label="Close" onclick="this.parentElement.remove()"></button>
  `;
  
  container.appendChild(toast);
  
  // Auto remove after 5 seconds
  setTimeout(() => {
    toast.style.animation = 'fadeOut 0.5s ease forwards';
    setTimeout(() => {
      toast.remove();
    }, 500);
  }, 4500);
};
