document.addEventListener('DOMContentLoaded', () => {
  const fullNameInput = document.getElementById('fullName');
  const emailInput = document.getElementById('email');
  const phoneInput = document.getElementById('phone');
  const locationInput = document.getElementById('location');
  const linkedinInput = document.getElementById('linkedin');
  const pdfInput = document.getElementById('pdfInput');
  const fileNameDisplay = document.getElementById('fileNameDisplay');
  const saveBtn = document.getElementById('saveProfileBtn');
  const autofillBtn = document.getElementById('autofillBtn');

  // Load saved configuration from chrome.storage.local
  chrome.storage.local.get(["candidateProfile", "resumePdf"], (res) => {
    if (res.candidateProfile) {
      const p = res.candidateProfile;
      fullNameInput.value = p.fullName || "";
      emailInput.value = p.email || "";
      phoneInput.value = p.phone || "";
      locationInput.value = p.location || "";
      linkedinInput.value = p.linkedin || "";
    } else {
      // Set defaults
      fullNameInput.value = "Alex Morgan";
      emailInput.value = "alex.morgan@cloudtech-corp.com";
      phoneInput.value = "(555) 019-8472";
      locationInput.value = "Charlotte, NC";
      linkedinInput.value = "https://linkedin.com/in/alexmorgan-devops";
    }

    if (res.resumePdf) {
      fileNameDisplay.textContent = `📄 Attached: ${res.resumePdf.name}`;
    }
  });

  // Handle PDF Upload
  pdfInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;

    fileNameDisplay.textContent = `⏳ Reading ${file.name}...`;

    const reader = new FileReader();
    reader.onload = (event) => {
      const resumeData = {
        name: file.name,
        type: file.type,
        dataUrl: event.target.result
      };
      chrome.storage.local.set({ resumePdf: resumeData }, () => {
        fileNameDisplay.textContent = `✓ Attached: ${file.name}`;
      });
    };
    reader.readAsDataURL(file);
  });

  // Save Profile Details
  saveBtn.addEventListener('click', () => {
    const parts = fullNameInput.value.trim().split(' ');
    const firstName = parts[0] || "";
    const lastName = parts.slice(1).join(' ') || "";

    const candidateProfile = {
      fullName: fullNameInput.value.trim(),
      firstName: firstName,
      lastName: lastName,
      email: emailInput.value.trim(),
      phone: phoneInput.value.trim(),
      location: locationInput.value.trim(),
      linkedin: linkedinInput.value.trim(),
      github: "https://github.com/alexmorgan-devops",
      website: "https://alexmorgan-devops.io",
      summary: "Senior DevOps & Cloud Infrastructure Specialist with 6+ years of experience automating production CI/CD pipelines, managing Kubernetes (EKS), AWS cloud architectures, and Terraform IaC."
    };

    chrome.storage.local.set({ candidateProfile }, () => {
      saveBtn.textContent = "✓ Profile Saved!";
      saveBtn.style.background = "#059669";
      setTimeout(() => {
        saveBtn.textContent = "💾 Save Profile & Resume";
        saveBtn.style.background = "linear-gradient(135deg, #2563eb, #3b82f6)";
      }, 1500);
    });
  });

  // Trigger Auto-Fill
  autofillBtn.addEventListener('click', () => {
    chrome.storage.local.get(["resumePdf"], (res) => {
      if (!res.resumePdf || !res.resumePdf.dataUrl) {
        alert("📄 Candidate Resume PDF Required!\n\nPlease click 'Select Candidate Resume PDF' above and attach your resume PDF file before running Auto-Fill.");
        const dropzone = document.getElementById('uploadDropzone');
        if (dropzone) {
          dropzone.style.border = '2px solid #ef4444';
          dropzone.style.background = 'rgba(239, 68, 68, 0.1)';
        }
        return;
      }

      autofillBtn.disabled = true;
      autofillBtn.textContent = '⚡ Auto-Filling Fields...';

      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0] && tabs[0].id) {
        chrome.tabs.sendMessage(tabs[0].id, { action: 'AUTO_FILL' }, (res) => {
          if (chrome.runtime.lastError) {
            console.warn('Script execution error:', chrome.runtime.lastError.message);
            chrome.scripting.executeScript({
              target: { tabId: tabs[0].id },
              files: ['content.js']
            }, () => {
              setTimeout(() => {
                chrome.tabs.sendMessage(tabs[0].id, { action: 'AUTO_FILL' });
              }, 300);
            });
          }
          setTimeout(() => {
            autofillBtn.disabled = false;
            autofillBtn.textContent = '✓ Form Auto-Filled!';
            autofillBtn.style.background = '#059669';
          }, 600);
        });
      }
    });
    });
  });
});
