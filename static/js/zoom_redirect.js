(function () {
  const PREF_KEY = "zoom_redirect_pref";
  const TOKEN_COOKIE = "zoom_redirect_token";
  const AUTO_REDIRECT_SECONDS = 3;

  const targetsElement = document.getElementById("zoom-targets");
  const configElement = document.getElementById("zoom-config");
  const titleElement = document.getElementById("zoom-room-title");
  const metaElement = document.getElementById("zoom-room-meta");
  const statusElement = document.getElementById("zoom-status");
  const countdownRowElement = document.getElementById("zoom-countdown-row");
  const countdownElement = document.getElementById("zoom-countdown");
  const pauseCountdownButton = document.getElementById("zoom-pause-countdown");
  const checkboxElement = document.getElementById("zoom-save-checkbox");
  const joinButton = document.getElementById("zoom-join-button");
  const slackHelpElement = document.getElementById("zoom-slack-help");
  const slackHelpTextElement = document.getElementById("zoom-slack-help-text");
  const slackHelpLinkElement = document.getElementById("zoom-slack-help-link");
  const registrantsNoticeElement = document.getElementById("zoom-registrants-notice");
  const checkboxContainer = checkboxElement?.closest(".form-check");

  if (!targetsElement || !configElement || !titleElement || !metaElement || !statusElement || !countdownRowElement || !countdownElement || !pauseCountdownButton || !checkboxElement || !joinButton || !slackHelpElement || !slackHelpTextElement || !slackHelpLinkElement || !registrantsNoticeElement) {
    throw new Error("Required Zoom redirect elements are missing");
  }

  let countdownIntervalId = null;
  let countdownRemaining = AUTO_REDIRECT_SECONDS;
  let activeCountdownRoom = null;
  let activeCountdownPasscode = false;

  const eventUid = new URLSearchParams(window.location.search).get("event_uid") || "";
  const urlToken = new URLSearchParams(window.location.search).get("token") || "";
  // Debug: ?debug_no_token=1 treats every token as invalid
  const forceNoToken = new URLSearchParams(window.location.search).has("debug_no_token");
  // Debug: ?debug_yes_token=1 treats access as valid, but never sends the passcode
  const forceYesToken = new URLSearchParams(window.location.search).has("debug_yes_token");

  const parsedTargets = JSON.parse(targetsElement.textContent || "{}");
  const zoomConfig = JSON.parse(configElement.textContent || "{}");
  const accessToken = String(zoomConfig.access_token || "");
  const room = parsedTargets[eventUid];

  function showSlackPrompt(targetRoom) {
    const hasChannelLink = Boolean(targetRoom.channel_url);
    const channelLabel = targetRoom.slack_channel ? ` (${targetRoom.slack_channel})` : "";
    slackHelpTextElement.textContent = "To skip passcodes, join Zoom from channel descriptions on Slack, one-time:";
    if (hasChannelLink) {
      slackHelpLinkElement.href = targetRoom.channel_url;
      slackHelpLinkElement.classList.remove("d-none");
    } else {
      slackHelpLinkElement.classList.add("d-none");
    }
    slackHelpElement.classList.remove("d-none");
  }

  function validToken(token) {
    return !forceNoToken && Boolean(token) && token === accessToken;
  }

  function getCookie(name) {
    const prefix = `${name}=`;
    const parts = document.cookie ? document.cookie.split("; ") : [];
    for (const part of parts) {
      if (part.startsWith(prefix)) {
        return decodeURIComponent(part.slice(prefix.length));
      }
    }
    return "";
  }

  function setCookie(name, value) {
    const encodedValue = encodeURIComponent(value);
    document.cookie = `${name}=${encodedValue}; path=/; max-age=31536000; samesite=lax`;
  }

  function removeCookie(name) {
    document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
  }

  function getSavedPreference() {
    return window.localStorage.getItem(PREF_KEY) || "INITIAL";
  }

  function setSavedPreference(value) {
    window.localStorage.setItem(PREF_KEY, value);
  }

  function stripPasscode(joinUrl) {
    const parsed = new URL(joinUrl, window.location.href);
    parsed.searchParams.delete("pwd");
    return parsed.toString();
  }

  function resolveRoom() {
    if (!room || !room.join_url) {
      titleElement.textContent = "Room not found";
      metaElement.textContent = `Unknown event UID: ${eventUid || "(missing)"}`;
      statusElement.textContent = "The utility link did not contain a valid room reference.";
      checkboxElement.disabled = true;
      joinButton.disabled = true;
      throw new Error(`Unknown Zoom event UID: ${eventUid || "(missing)"}`);
    }

    titleElement.textContent = room.title || "Zoom room";
    return room;
  }

  function immediateToken() {
    if (forceYesToken) {
      return "debug_yes_token";
    }
    const savedToken = getCookie(TOKEN_COOKIE);
    if (validToken(urlToken)) {
      return urlToken;
    }
    if (validToken(savedToken)) {
      return savedToken;
    }
    return "";
  }

  function hasValidAccess() {
    return Boolean(immediateToken());
  }

  function autoToken(state) {
    if (state === "NO") {
      return "";
    }
    if (forceYesToken) {
      return "debug_yes_token";
    }
    const savedToken = getCookie(TOKEN_COOKIE);
    if (validToken(urlToken)) {
      return urlToken;
    }
    if (validToken(savedToken)) {
      return savedToken;
    }
    return "";
  }

  function redirectTo(targetRoom, includePasscode) {
    const destination = includePasscode ? targetRoom.join_url : stripPasscode(targetRoom.join_url);
    window.location.replace(destination);
  }

  function renderCountdownText() {
    const includePasscode = activeCountdownPasscode;
    countdownElement.textContent = includePasscode
      ? `Redirecting to Zoom with saved credentials in ${countdownRemaining} seconds...`
      : `Redirecting to Zoom in ${countdownRemaining} seconds...`;
  }

  function stopCountdown() {
    if (countdownIntervalId !== null) {
      window.clearInterval(countdownIntervalId);
      countdownIntervalId = null;
    }
  }

  function showCountdown(state, targetRoom) {
    countdownRowElement.classList.remove("d-none");
    pauseCountdownButton.classList.remove("d-none");
    activeCountdownRoom = targetRoom;
    activeCountdownPasscode = !forceYesToken && state === "YES" && Boolean(autoToken(state));
    countdownRemaining = AUTO_REDIRECT_SECONDS;
    renderCountdownText();

    stopCountdown();
    countdownIntervalId = window.setInterval(() => {
      countdownRemaining -= 1;
      if (countdownRemaining <= 0) {
        stopCountdown();
        redirectTo(activeCountdownRoom, activeCountdownPasscode);
        return;
      }
      renderCountdownText();
    }, 1000);
  }

  pauseCountdownButton.addEventListener("click", () => {
    stopCountdown();
    countdownRowElement.classList.add("d-none");
    pauseCountdownButton.classList.add("d-none");
  });

  const targetRoom = resolveRoom();

  if (!hasValidAccess()) {
    showSlackPrompt(targetRoom);
    if (checkboxContainer) {
      checkboxContainer.classList.add("d-none");
    }
  }

  const savedPreference = getSavedPreference();
  const initialCheckboxState = savedPreference === "NO" ? false : true;
  checkboxElement.checked = initialCheckboxState;

  if (!hasValidAccess()) {
    statusElement.classList.add("d-none");
    joinButton.textContent = "Join Zoom (Passcode required)";
    registrantsNoticeElement.classList.remove("d-none");
  } else if (savedPreference === "YES") {
    statusElement.textContent = "Saved credentials detected. Redirecting automatically.";
    showCountdown("YES", targetRoom);
  } else if (savedPreference === "NO") {
    statusElement.textContent = "This browser is set to avoid saving credentials. Redirecting automatically.";
    showCountdown("NO", targetRoom);
  } else {
    statusElement.textContent = "No saved preference yet. Press the button to join or save credentials.";
  }

  joinButton.addEventListener("click", () => {
    const state = checkboxElement.checked ? "YES" : "NO";
    const token = immediateToken();
    setSavedPreference(state);

    if (forceYesToken) {
      // leave the real cookie alone
    } else if (state === "YES") {
      if (token) {
        setCookie(TOKEN_COOKIE, token);
      } else {
        removeCookie(TOKEN_COOKIE);
      }
    } else {
      removeCookie(TOKEN_COOKIE);
    }

    redirectTo(targetRoom, !forceYesToken && Boolean(token));
  });
})();