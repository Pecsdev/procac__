(() => {
  const apiOrigin = 'http://127.0.0.1:8000';
  const apiBase = `${apiOrigin}/api/extension`;
  const statusElement = document.getElementById('account-status');
  const tierElement = document.getElementById('subscription-tier');
  const clientList = document.getElementById('client-list');
  const fillButton = document.getElementById('fill-button');
  const loginButton = document.getElementById('login-button');
  const messageElement = document.getElementById('message');
  const extensionKeyInput = document.getElementById('extension-key');
  const saveKeyButton = document.getElementById('save-key');
  let clients = [];
  let extensionKey = '';
  let presenterDefaults = {};
  let csrfToken = '';

  const setMessage = (message) => {
    messageElement.textContent = message;
  };

  const loadData = async () => {
    try {
      const requestOptions = extensionKey
        ? {
            credentials: 'omit',
            cache: 'no-store',
            headers: { Accept: 'application/json', Authorization: `Bearer ${extensionKey}` },
          }
        : {
            credentials: 'include',
            cache: 'no-store',
            headers: { Accept: 'application/json' },
          };
      const [statusResponse, clientsResponse] = await Promise.all([
        fetch(`${apiBase}/status/`, requestOptions),
        fetch(`${apiBase}/clients/`, requestOptions),
      ]);

      if (statusResponse.status === 401 || clientsResponse.status === 401) {
        statusElement.textContent = extensionKey
          ? 'Extension key is invalid or revoked.'
          : 'Not signed in to ProCAC.';
        clientList.replaceChildren(new Option(
          extensionKey ? 'Check your extension key' : 'Sign in to load profiles',
          '',
        ));
        loginButton.hidden = Boolean(extensionKey);
        return;
      }
      if (!statusResponse.ok || !clientsResponse.ok) {
        throw new Error('ProCAC could not load your account or client profiles.');
      }

      const status = await statusResponse.json();
      const clientData = await clientsResponse.json();
      presenterDefaults = status.presenter_defaults || {};
      csrfToken = status.csrf_token || '';
      statusElement.textContent = `Signed in as ${status.user || 'ProCAC user'}`;
      tierElement.textContent = status.active_subscription_tier
        ? `Active plan: ${status.active_subscription_tier}`
        : 'No active subscription';

      clients = Array.isArray(clientData.clients) ? clientData.clients : [];
      clientList.replaceChildren();
      if (clients.length === 0) {
        clientList.append(new Option('No saved profiles', ''));
        setMessage('Add a client profile in your ProCAC dashboard first.');
        return;
      }

      clientList.append(new Option('Choose a client profile', ''));
      clients.forEach((client, index) => {
        clientList.append(new Option(
          `${client.proposed_name_1 || client.entity_name} (${client.entity_type})`,
          String(index),
        ));
      });
      clientList.disabled = false;
      fillButton.disabled = false;
    } catch (error) {
      statusElement.textContent = 'Unable to connect to ProCAC.';
      setMessage(
        `Could not reach ${apiOrigin}. Check that Django is running and PROCAC_EXTENSION_ID matches the ID in chrome://extensions.`,
      );
    }
  };

  saveKeyButton.addEventListener('click', () => {
    extensionKey = extensionKeyInput.value.trim();
    chrome.storage.local.set({ extensionKey }, () => {
      const error = chrome.runtime.lastError;
      if (error) {
        setMessage(`Could not save extension key: ${error.message}`);
        return;
      }
      setMessage(extensionKey ? 'Extension key saved.' : 'Extension key removed.');
      loadData();
    });
  });

  clientList.addEventListener('change', () => {
    fillButton.disabled = clientList.value === '';
  });

  loginButton.addEventListener('click', () => {
    chrome.tabs.create({ url: `${apiOrigin}/login/` });
  });

  const waitForTabReady = (tab) => {
    if (tab.status === 'complete') {
      return Promise.resolve(tab);
    }

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(onUpdated);
        reject(new Error('The CAC portal page did not finish loading. Try again.'));
      }, 15000);
      const onUpdated = (tabId, changeInfo, updatedTab) => {
        if (tabId === tab.id && changeInfo.status === 'complete') {
          clearTimeout(timeout);
          chrome.tabs.onUpdated.removeListener(onUpdated);
          resolve(updatedTab);
        }
      };
      chrome.tabs.onUpdated.addListener(onUpdated);
    });
  };

  const sendTabMessage = (tabId, message) => new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(response);
    });
  });

  const injectContentScript = (tabId) => new Promise((resolve, reject) => {
    if (
      !chrome.scripting
      || typeof chrome.scripting.executeScript !== 'function'
    ) {
      reject(new Error(
        'Script injection is unavailable. Reload ProCAC in chrome://extensions and make sure the scripting permission is enabled.',
      ));
      return;
    }

    chrome.scripting.executeScript(
      {
        target: { tabId },
        files: ['content-script.js'],
      },
      () => {
        const error = chrome.runtime.lastError;
        if (error) {
          reject(new Error(`Could not inject the CAC autofill script: ${error.message}`));
          return;
        }
        resolve();
      },
    );
  });

  const ensureContentScript = async (tabId) => {
    try {
      const response = await sendTabMessage(tabId, { type: 'PROCAC_PING' });
      if (response?.ready) {
        return;
      }
    } catch {
      // Inject when the manifest content script has not attached to this tab.
    }
    await injectContentScript(tabId);
    const response = await sendTabMessage(tabId, { type: 'PROCAC_PING' });
    if (!response?.ready) {
      throw new Error('ProCAC could not connect to the content script on this CAC page.');
    }
  };

  const recordInjectionAudit = async (client, result) => {
    const headers = {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    };
    if (extensionKey) {
      headers.Authorization = `Bearer ${extensionKey}`;
    } else if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }

    const response = await fetch(`${apiBase}/injection-audits/`, {
      method: 'POST',
      credentials: extensionKey ? 'omit' : 'include',
      cache: 'no-store',
      headers,
      body: JSON.stringify({
        client_id: client.id,
        status: result.status === 'success' ? 'success' : 'failure',
        fields_populated: Number.isInteger(result.fields_populated)
          ? result.fields_populated
          : 0,
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Audit record failed (${response.status}).`);
    }
  };

  fillButton.addEventListener('click', async () => {
    const client = clients[Number(clientList.value)];
    if (!client) {
      setMessage('Choose a saved client profile first.');
      return;
    }
    let injectionAttemptStarted = false;
    const portalClient = {
      ...client,
      location: {
        state: client.location?.state || client.state || '',
        lga: client.location?.lga || client.lga || '',
      },
      business_activities: {
        principal: client.business_activities?.principal
          || client.principal_activity
          || client.principal_business_activity
          || client.nature_category
          || '',
        specific: client.business_activities?.specific
          || client.specific_activity
          || client.specific_business_activity
          || client.specific_nature
          || '',
      },
    };

    try {
      const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!activeTab?.id || !activeTab.url) {
        throw new Error('Open the CAC portal tab before filling a form.');
      }
      const portalUrl = new URL(activeTab.url);
      if (
        portalUrl.hostname !== 'cac.gov.ng'
        && !portalUrl.hostname.endsWith('.cac.gov.ng')
      ) {
        throw new Error('Open a CAC portal page ending in cac.gov.ng before filling a profile.');
      }

      const tab = await waitForTabReady(activeTab);
      const readyUrl = new URL(tab.url || activeTab.url);
      if (
        readyUrl.hostname !== 'cac.gov.ng'
        && !readyUrl.hostname.endsWith('.cac.gov.ng')
      ) {
        throw new Error('The active tab navigated away from the CAC portal.');
      }
      await ensureContentScript(tab.id);
      injectionAttemptStarted = true;
      const result = await sendTabMessage(tab.id, {
        type: 'PROCAC_FILL_CLIENT',
        client: portalClient,
        presenterDefaults,
      });
      if (!result || !['success', 'failure'].includes(result.status)) {
        throw new Error('The CAC page did not return an injection result.');
      }
      let auditNotice = '';
      try {
        await recordInjectionAudit(client, result);
      } catch (error) {
        auditNotice = ` Audit log was not recorded: ${error.message}`;
      }
      setMessage(`${result.message || 'Profile sent to the CAC form.'}${auditNotice}`);
    } catch (error) {
      let auditNotice = '';
      if (injectionAttemptStarted) {
        try {
          await recordInjectionAudit(client, { status: 'failure', fields_populated: 0 });
        } catch (auditError) {
          auditNotice = ` Audit log was not recorded: ${auditError.message}`;
        }
      }
      const message = error instanceof Error ? error.message : 'Could not fill the CAC form.';
      setMessage(`${message}${auditNotice}`);
    }
  });

  chrome.storage.local.get(['extensionKey'], (result) => {
    const error = chrome.runtime.lastError;
    if (error) {
      setMessage(`Could not load extension settings: ${error.message}`);
      return;
    }
    extensionKey = result.extensionKey || '';
    extensionKeyInput.value = extensionKey;
    loadData();
  });
})();