// JobSpike AI Auto-Apply Content Script v1.0.3 (Full Multi-Step Auto-Advancer & Screening Question Engine)
console.log("⚡ JobSpike Extension Content Script V1.0.3 Active.");

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

let storedResumePdf = null;

// Load profile & stored PDF file from storage
function refreshStorageData() {
  if (chrome.storage && chrome.storage.local) {
    chrome.storage.local.get(["candidateProfile", "resumePdf"], (res) => {
      if (res.candidateProfile) {
        candidateProfile = { ...candidateProfile, ...res.candidateProfile };
      }
      if (res.resumePdf) {
        storedResumePdf = res.resumePdf;
      }
    });
  }
}
refreshStorageData();

// Listen for popup auto-fill requests
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "AUTO_FILL") {
    refreshStorageData();
    const filled = runAutoFillPipeline();
    sendResponse({ success: true, count: filled });
  }
});

function isLinkedInLoggedIn() {
  if (window.location.hostname.includes('linkedin.com')) {
    const loginForm = document.querySelector('form.login__form, form[action*="login"], .nav__button-secondary');
    const userChip = document.querySelector('.global-nav__me, #global-nav, .feed-identity-module');
    if (loginForm && !userChip) return false;
  }
  return true;
}

function runAutoFillPipeline() {
  if (!isLinkedInLoggedIn()) {
    showFloatingBanner("⚠️ Please log in to your LinkedIn account first!", "#ef4444");
    return 0;
  }

  let filledCount = 0;
  console.log("🚀 Executing JobSpike Multi-Step Auto-Fill Pipeline...");

  // 1. Text Inputs, Email, Phone, Location
  const allInputs = document.querySelectorAll('input, textarea, select');
  
  allInputs.forEach(el => {
    const id = (el.id || '').toLowerCase();
    const name = (el.name || '').toLowerCase();
    const placeholder = (el.placeholder || '').toLowerCase();
    const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
    
    let labelText = '';
    const labelEl = document.querySelector(`label[for="${el.id}"]`) || el.closest('label') || (el.parentElement ? el.parentElement.querySelector('label') : null);
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
      fillNativeInput(el, candidateProfile.website || candidateProfile.github);
      filledCount++;
    } else if (el.tagName.toLowerCase() === 'textarea' && (!el.value || el.value.trim() === '')) {
      fillNativeInput(el, `Dear Hiring Team,\n\nI am thrilled to submit my candidate package. ${candidateProfile.summary}\n\nSincerely,\n${candidateProfile.fullName}`);
      filledCount++;
    } else if (combinedStr.includes('years') || combinedStr.includes('experience')) {
      fillNativeInput(el, "5");
      filledCount++;
    }

    // Handle Radio Buttons (Yes / No screening questions)
    if (el.type === 'radio') {
      const radioVal = (el.value || '').toLowerCase();
      const radioLabel = labelText || combinedStr;
      if (radioVal === 'yes' || radioLabel.includes('yes') || radioLabel.includes('authorized') || radioLabel.includes('sponsorship')) {
        if (!el.checked) {
          el.checked = true;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          filledCount++;
        }
      }
    }
  });

  // 2. Attach PDF Resume File to <input type="file">
  const fileInputs = document.querySelectorAll('input[type="file"]');
  if (fileInputs.length > 0 && storedResumePdf && storedResumePdf.dataUrl) {
    fileInputs.forEach(fileInput => {
      try {
        const file = dataURLtoFile(storedResumePdf.dataUrl, storedResumePdf.name || "Candidate_Resume.pdf");
        const container = new DataTransfer();
        container.items.add(file);
        fileInput.files = container.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        fileInput.style.border = "2px solid #10b981";
        filledCount++;
        console.log("✓ Successfully attached PDF resume to form field.");
      } catch (e) {
        console.warn("Could not attach file to input:", e);
      }
    });
  }

  showFloatingBanner(`⚡ JobSpike Auto-Filled ${filledCount} Fields & Resume Attached!`, "#059669");

  // 3. Auto-Advance Multi-Step Modal (Click "Next" / "Continue" / "Review")
  setTimeout(() => {
    autoAdvanceStep();
  }, 1200);

  return filledCount;
}

function autoAdvanceStep() {
  const buttons = document.querySelectorAll('button');
  for (let btn of buttons) {
    const text = (btn.textContent || '').trim().toLowerCase();
    const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
    const combined = `${text} ${aria}`;

    if (combined.includes('next') || combined.includes('continue') || combined.includes('review your application')) {
      console.log("⚡ Auto-Advancing to Next Step:", combined);
      btn.click();
      break;
    }
  }
}

// Convert Base64 DataURL back to File object
function dataURLtoFile(dataurl, filename) {
  let arr = dataurl.split(','), mime = arr[0].match(/:(.*?);/)[1],
      bstr = atob(arr[1]), n = bstr.length, u8arr = new Uint8Array(n);
  while(n--){
      u8arr[n] = bstr.charCodeAt(n);
  }
  return new File([u8arr], filename, {type:mime});
}

function fillNativeInput(element, value) {
  if (!element) return;
  element.focus();
  
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

function showFloatingBanner(msg, color = "#0f172a") {
  let banner = document.getElementById('jobspike-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'jobspike-banner';
    banner.style.cssText = `position:fixed; top:15px; right:15px; background:${color}; color:#ffffff; border:2px solid #38bdf8; padding:12px 18px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.5); font-family:sans-serif; font-weight:700; font-size:13px; z-index:9999999;`;
    document.body.appendChild(banner);
  }
  banner.textContent = msg;
  setTimeout(() => { if (banner) banner.remove(); }, 3500);
}

// Auto-detect LinkedIn Easy Apply Modal open events
setInterval(() => {
  const modal = document.querySelector('.jobs-easy-apply-content, .jobs-easy-apply-modal, [role="dialog"]');
  if (modal) {
    runAutoFillPipeline();
  }
}, 1200);
