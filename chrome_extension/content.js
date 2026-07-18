// JobSpike AI Auto-Apply Content Script v1.0.1 (LinkedIn Easy Apply Optimized)
console.log("⚡ JobSpike Extension Content Script Ready.");

let candidateProfile = {
  fullName: "Alex Morgan",
  firstName: "Alex",
  lastName: "Morgan",
  email: "alex.morgan@cloudtech-corp.com",
  phone: "5550198472",
  location: "Charlotte, NC",
  linkedin: "https://linkedin.com/in/alexmorgan-devops",
  github: "https://github.com/alexmorgan-devops",
  website: "https://alexmorgan-devops.io",
  summary: "Senior DevOps & Cloud Infrastructure Specialist with 6+ years of experience managing production Kubernetes (EKS), AWS cloud architectures, Terraform IaC, and CI/CD automation."
};

// Listen for popup trigger
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "AUTO_FILL") {
    const filled = runAutoFillPipeline();
    sendResponse({ success: true, count: filled });
  }
});

function runAutoFillPipeline() {
  let filledCount = 0;
  console.log("🚀 Running JobSpike Auto-Fill Pipeline...");

  // Select all input elements across the page and frames
  const allInputs = document.querySelectorAll('input, textarea, select');
  
  allInputs.forEach(el => {
    // Find associated label text or attributes
    const id = (el.id || '').toLowerCase();
    const name = (el.name || '').toLowerCase();
    const placeholder = (el.placeholder || '').toLowerCase();
    const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
    
    // Find parent label text
    let labelText = '';
    const labelEl = document.querySelector(`label[for="${el.id}"]`) || el.closest('label') || el.parentElement.querySelector('label');
    if (labelEl) labelText = labelEl.textContent.toLowerCase();

    const combinedStr = `${id} ${name} ${placeholder} ${ariaLabel} ${labelText}`;

    // Fill field based on match
    if (combinedStr.includes('first name') || combinedStr.includes('given name')) {
      fillNativeInput(el, candidateProfile.firstName);
      filledCount++;
    } else if (combinedStr.includes('last name') || combinedStr.includes('family name') || combinedStr.includes('surname')) {
      fillNativeInput(el, candidateProfile.lastName);
      filledCount++;
    } else if (combinedStr.includes('full name') || combinedStr.includes('complete name')) {
      fillNativeInput(el, candidateProfile.fullName);
      filledCount++;
    } else if (combinedStr.includes('email')) {
      fillNativeInput(el, candidateProfile.email);
      filledCount++;
    } else if (combinedStr.includes('phone') || combinedStr.includes('mobile') || combinedStr.includes('contact number')) {
      fillNativeInput(el, candidateProfile.phone);
      filledCount++;
    } else if (combinedStr.includes('city') || combinedStr.includes('location')) {
      fillNativeInput(el, candidateProfile.location);
      filledCount++;
    } else if (combinedStr.includes('linkedin')) {
      fillNativeInput(el, candidateProfile.linkedin);
      filledCount++;
    } else if (combinedStr.includes('website') || combinedStr.includes('portfolio') || combinedStr.includes('github')) {
      fillNativeInput(el, candidateProfile.website);
      filledCount++;
    } else if (el.tagName.toLowerCase() === 'textarea' && (!el.value || el.value.trim() === '')) {
      fillNativeInput(el, `Dear Hiring Manager,\n\nI am thrilled to apply for this position. ${candidateProfile.summary}\n\nSincerely,\n${candidateProfile.fullName}`);
      filledCount++;
    } else if (combinedStr.includes('years') || combinedStr.includes('experience')) {
      fillNativeInput(el, "5");
      filledCount++;
    }
  });

  showFloatingBanner(`⚡ JobSpike Auto-Filled ${filledCount} LinkedIn & ATS Fields!`);
  return filledCount;
}

// React / Angular / LinkedIn Native Event Trigger
function fillNativeInput(element, value) {
  if (!element) return;
  element.focus();
  
  // Set value prototype setter for React inputs
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;

  if (element.tagName.toLowerCase() === 'textarea' && nativeTextAreaValueSetter) {
    nativeTextAreaValueSetter.call(element, value);
  } else if (nativeInputValueSetter) {
    nativeInputValueSetter.call(element, value);
  } else {
    element.value = value;
  }

  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('blur', { bubbles: true }));
  element.style.border = "2px solid #38bdf8";
  element.style.background = "#f0f9ff";
}

function showFloatingBanner(msg) {
  let banner = document.getElementById('jobspike-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'jobspike-banner';
    banner.style.cssText = 'position:fixed; top:15px; right:15px; background:#0f172a; color:#38bdf8; border:2px solid #38bdf8; padding:12px 18px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.5); font-family:sans-serif; font-weight:700; font-size:13px; z-index:9999999;';
    document.body.appendChild(banner);
  }
  banner.textContent = msg;
  setTimeout(() => { if (banner) banner.remove(); }, 3500);
}

// Auto-run when LinkedIn Easy Apply modal appears
setInterval(() => {
  const modal = document.querySelector('.jobs-easy-apply-content, .jobs-easy-apply-modal, [role="dialog"]');
  if (modal && !modal.getAttribute('data-jspike-done')) {
    modal.setAttribute('data-jspike-done', 'true');
    runAutoFillPipeline();
  }
}, 800);
