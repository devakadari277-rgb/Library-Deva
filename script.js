// Custom AI-themed Toast Notification function
function showAIToast(message, type = 'success') {
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
}

gsap.registerPlugin(Draggable);

const root = document.documentElement;
const body = document.body;
const loginForm = document.querySelector(".login-form");

const cordBead = document.querySelector(".cord-bead");
const cordLine = document.querySelector(".cord-line");
const hitArea = document.querySelector(".cord-hit");

let isOn = false;

const clickSound = new Audio(
  "https://assets.codepen.io/605876/click.mp3"
);

Draggable.create(hitArea, {
  type: "y",
  bounds: {
    minY: 0,
    maxY: 60,
  },

  onDrag() {
    gsap.set(cordBead, {
      y: this.y,
    });

    gsap.set(cordLine, {
      attr: {
        y2: 180 + this.y,
      },
    });
  },

  onRelease() {
    if (this.y > 30) {
      toggleLamp();
    }

    gsap.to([cordBead, hitArea], {
      y: 0,
      duration: 0.5,
      ease: "back.out(2.5)",
    });

    gsap.to(cordLine, {
      attr: {
        y2: 180,
      },
      duration: 0.5,
      ease: "back.out(2.5)",
    });
  },
});

function toggleLamp() {
  isOn = !isOn;

  clickSound.play();

  body.setAttribute("data-on", isOn);
  root.style.setProperty("--on", isOn ? 1 : 0);

  if (isOn) {
    loginForm.classList.add("active");

    gsap.to(body, {
      backgroundColor: "#1c1f24",
      duration: 0.6,
    });
  } else {
    loginForm.classList.remove("active");

    gsap.to(body, {
      backgroundColor: "#121417",
      duration: 0.6,
    });
  }
}

// --- Authentication UI handlers ---
const loginBtn = document.getElementById('login-btn');
const registerBtn = document.getElementById('register-btn');

// Prefill last username
try {
  const stored = JSON.parse(localStorage.getItem('registeredUser') || 'null');
  if (stored && document.getElementById('login-fullname')) {
    document.getElementById('login-fullname').value = stored.full_name || '';
  }
} catch (e) {}

async function postJSON(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(data),
  });
  return res.json();
}

if (loginBtn) loginBtn.addEventListener('click', async () => {
  const full_name = (document.getElementById('login-fullname') || {}).value?.trim();
  const password = (document.getElementById('login-password') || {}).value;
  const user_type = document.getElementById('user-type')?.value || 'Student';
  if (!full_name || !password) { showAIToast('Enter credentials', 'error'); return; }
  try {
    const resp = await postJSON('/api/login', { full_name, password, user_type });
    if (resp.success) {
      showAIToast('Login successful! Redirecting to Dashboard...', 'success');
      setTimeout(() => {
        window.location = '/dashboard';
      }, 1200);
    } else {
      showAIToast(resp.message || 'Login failed', 'error');
    }
  } catch (e) {
    showAIToast('Network error', 'error');
  }
});

if (registerBtn) registerBtn.addEventListener('click', async () => {
  const full_name = document.getElementById('reg-fullname').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const password = document.getElementById('reg-password').value;
  const user_type = document.getElementById('reg-user-type')?.value || 'Student';
  
  // Extra Fields
  const roll_number = document.getElementById('reg-roll')?.value?.trim();
  const department = document.getElementById('reg-dept')?.value?.trim();
  const phone = document.getElementById('reg-phone')?.value?.trim();
  const address = document.getElementById('reg-address')?.value?.trim();

  if (!full_name || !email || !password) { showAIToast('Fill all fields', 'error'); return; }
  if (user_type === 'Student' && (!roll_number || !department || !phone)) {
    showAIToast('Please fill out Roll Number, Department, and Phone Number.', 'warning');
    return;
  }

  try {
    const resp = await postJSON('/api/register', { 
      full_name, email, password, user_type,
      roll_number, department, phone, address
    });
    if (resp.success) {
      try {
        localStorage.setItem('registeredUser', JSON.stringify({ full_name, email, user_type }));
      } catch (e) {}
      showAIToast('Registration successful! Please sign in.', 'success');
      setTimeout(() => {
        window.location = '/login';
      }, 1500);
    } else {
      showAIToast(resp.message || 'Registration failed', 'error');
    }
  } catch (e) { 
    showAIToast('Network error', 'error'); 
  }
});