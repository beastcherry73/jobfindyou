// JobSpike Background Service Worker
console.log("⚡ JobSpike Extension Background Worker Running.");

chrome.runtime.onInstalled.addListener(() => {
  console.log("⚡ JobSpike Extension Installed Successfully.");
});
