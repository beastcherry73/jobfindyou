document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('autofillBtn');

  btn.addEventListener('click', () => {
    btn.disabled = true;
    btn.textContent = '⚡ Auto-Filling Fields...';

    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0] && tabs[0].id) {
        chrome.tabs.sendMessage(tabs[0].id, { action: 'AUTO_FILL' }, (res) => {
          if (chrome.runtime.lastError) {
            console.warn('Script execution error:', chrome.runtime.lastError.message);
            // Fallback scripting injection
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
            btn.disabled = false;
            btn.textContent = '✓ Form Auto-Filled!';
            btn.style.background = '#059669';
          }, 600);
        });
      }
    });
  });
});
