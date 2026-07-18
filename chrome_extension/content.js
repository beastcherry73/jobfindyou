// JobSpike AI Auto-Apply Content Script
console.log("⚡ JobSpike AI Auto-Apply Extension Loaded.");

// Candidate Profile Storage Defaults
let candidateProfile = {
  fullName: "Alex Morgan",
  firstName: "Alex",
  lastName: "Morgan",
  email: "alex.morgan@cloudtech-corp.com",
  phone: "(555) 019-8472",
  location: "Charlotte, NC",
  linkedin: "https://linkedin.com/in/alexmorgan-devops",
  github: "https://github.com/alexmorgan-devops",
  website: "https://alexmorgan-devops.io",
  summary: "Senior DevOps & Cloud Infrastructure Specialist with 6+ years of experience automating production CI/CD pipelines, managing enterprise Kubernetes (EKS/GKE) clusters, and designing Terraform IaC."
};

// Load profile from Chrome Storage if configured
if (chrome.storage && chrome.storage.sync) {
  chrome.storage.sync.get(["candidateProfile"], (res) => {
    if (res.candidateProfile) {
      candidateProfile = { ...candidateProfile, ...res.candidateProfile };
    }
  });
}

// Listen for messages from popup or background
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "AUTO_FILL") {
    const result = runAutoFillPipeline();
    sendResponse({ success: true, count: result });
  }
});

function runAutoFillPipeline() {
  let filledCount = 0;
  console.log("🚀 Initializing JobSpike Auto-Fill Script...");

  // 1. Text Inputs & Email/Phone Detection
  const inputs = document.querySelectorAll('input[type="text"], input[type="email"], input[type="tel"], input:not([type])');
  inputs.forEach(input => {
    const nameAttr = (input.name || input.id || input.placeholder || input.getAttribute('aria-label') || '').toLowerCase();
    
    if (nameAttr.includes('first') || nameAttr.includes('fname')) {
      input.value = candidateProfile.firstName;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('last') || nameAttr.includes('lname')) {
      input.value = candidateProfile.lastName;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('full') || nameAttr.includes('name') || nameAttr.includes('candidate')) {
      input.value = candidateProfile.fullName;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('email') || nameAttr.includes('mail')) {
      input.value = candidateProfile.email;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('phone') || nameAttr.includes('mobile') || nameAttr.includes('cell') || nameAttr.includes('tel')) {
      input.value = candidateProfile.phone;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('city') || nameAttr.includes('location') || nameAttr.includes('address')) {
      input.value = candidateProfile.location;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('linkedin')) {
      input.value = candidateProfile.linkedin;
      triggerInputEvents(input);
      filledCount++;
    } else if (nameAttr.includes('github') || nameAttr.includes('website') || nameAttr.includes('portfolio') || nameAttr.includes('url')) {
      input.value = candidateProfile.website || candidateProfile.github;
      triggerInputEvents(input);
      filledCount++;
    }
  });

  // 2. Cover Letter / Pitch Textarea Auto-Fill
  const textareas = document.querySelectorAll('textarea');
  textareas.forEach(textarea => {
    if (!textarea.value || textarea.value.trim() === '') {
      textarea.value = `Dear Hiring Manager,\n\nI am excited to submit my application for this role. ${candidateProfile.summary}\n\nThank you for your time and consideration.\n\nBest regards,\n${candidateProfile.fullName}`;
      triggerInputEvents(textarea);
      filledCount++;
    }
  });

  // 3. Highlight Auto-Filled Form Elements visually
  showFloatingNotification(`⚡ JobSpike Auto-Filled ${filledCount} Form Fields!`);
  return filledCount;
}

function triggerInputEvents(element) {
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('blur', { bubbles: true }));
}

function showFloatingNotification(msg) {
  let banner = document.getElementById('jobspike-extension-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'jobspike-extension-banner';
    banner.style.cssText = 'position:fixed; top:20px; right:20px; background:linear-gradient(135deg, #0f172a, #1e293b); color:#38bdf8; border:1px solid #38bdf8; padding:12px 20px; border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,0.5); font-family:sans-serif; font-weight:700; font-size:14px; z-index:999999; transition:all 0.3s ease;';
    document.body.appendChild(banner);
  }
  banner.textContent = msg;
  setTimeout(() => {
    if (banner) banner.style.opacity = '0';
  }, 4000);
}

// Auto-detect LinkedIn Easy Apply Modal open events
const observer = new MutationObserver(() => {
  const easyApplyModal = document.querySelector('.jobs-easy-apply-content, .jobs-easy-apply-modal, [data-test-modal]');
  if (easyApplyModal && !easyApplyModal.getAttribute('data-jspike-filled')) {
    easyApplyModal.setAttribute('data-jspike-filled', 'true');
    setTimeout(() => {
      runAutoFillPipeline();
    }, 400);
  }
});
observer.observe(document.body, { childList: true, subtree: true });
