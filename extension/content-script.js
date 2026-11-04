(() => {
  if (globalThis.__procacContentScriptReady) {
    return;
  }
  globalThis.__procacContentScriptReady = true;

  const isCacPortal = (hostname) => (
    hostname === 'cac.gov.ng' || hostname.endsWith('.cac.gov.ng')
  );

  const setValue = (element, value) => {
    if (!element || element.disabled || !value) {
      return false;
    }
    const prototype = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
    if (setter) {
      setter.call(element, value);
    } else {
      element.value = value;
    }
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };

  const findByLabel = (pattern, selector) => {
    const labels = Array.from(document.querySelectorAll('label'));
    for (const label of labels) {
      if (!pattern.test(label.textContent || '')) {
        continue;
      }
      const control = label.control
        || label.querySelector(selector)
        || label.parentElement?.querySelector(selector);
      if (control) {
        return control;
      }
    }
    return null;
  };

  const findField = (selectors, pattern, fallbackSelector = 'input, textarea') => (
    document.querySelector(selectors)
    || findByLabel(pattern, fallbackSelector)
  );

  const fillSelect = (select, value) => {
    if (!(select instanceof HTMLSelectElement) || !value || select.disabled) {
      return false;
    }

    const normalize = (text) => text.trim().replace(/\s+/g, ' ').toLowerCase();
    const expected = normalize(value);
    const option = Array.from(select.options).find((candidate) => (
      normalize(candidate.value) === expected
      || normalize(candidate.textContent || '') === expected
    ));
    if (!option) {
      return false;
    }

    const setter = Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      'value',
    )?.set;
    if (setter) {
      setter.call(select, option.value);
    } else {
      select.value = option.value;
    }
    select.dispatchEvent(new Event('input', { bubbles: true }));
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };

  const findSelect = (selectors, pattern, excludedPattern = null) => {
    const labels = Array.from(document.querySelectorAll('label'));
    for (const label of labels) {
      const text = label.textContent || '';
      if (!pattern.test(text) || (excludedPattern && excludedPattern.test(text))) {
        continue;
      }
      const control = label.control || label.parentElement?.querySelector('select');
      if (control instanceof HTMLSelectElement) {
        return control;
      }
    }
    const candidates = Array.from(document.querySelectorAll(selectors));
    const selectedBySelector = candidates.find((candidate) => (
      candidate instanceof HTMLSelectElement
      && (!excludedPattern || !excludedPattern.test(
        [
          candidate.name,
          candidate.id,
          ...Array.from(candidate.labels || [])
            .map((label) => label.textContent || ''),
        ].join(' '),
      ))
    ));
    if (selectedBySelector) {
      return selectedBySelector;
    }
    return null;
  };

  const findMatchingOption = (select, value) => {
    const expected = value.trim().replace(/\s+/g, ' ').toLowerCase();
    return Array.from(select.options).some((option) => (
      option.textContent?.trim().replace(/\s+/g, ' ').toLowerCase() === expected
      || option.value.trim().toLowerCase() === expected
    ));
  };

  const waitForOption = (select, value, timeout = 2500) => {
    if (!select || findMatchingOption(select, value)) {
      return Promise.resolve(Boolean(select));
    }
    return new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        if (findMatchingOption(select, value)) {
          observer.disconnect();
          clearTimeout(timer);
          resolve(true);
        }
      });
      observer.observe(select, { childList: true, subtree: true });
      const timer = setTimeout(() => {
        observer.disconnect();
        resolve(findMatchingOption(select, value));
      }, timeout);
    });
  };

  const optionSignature = (select) => (
    Array.from(select?.options || [])
      .map((option) => `${option.value}\u0000${option.textContent || ''}`)
      .join('\u0001')
  );

  const waitForDependentOption = (selectors, pattern, value, previousSignature, timeout = 3500) => (
    new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        const select = findSelect(selectors, pattern);
        if (
          select
          && optionSignature(select) !== previousSignature
          && findMatchingOption(select, value)
        ) {
          observer.disconnect();
          clearTimeout(timer);
          resolve(select);
        }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
      const timer = setTimeout(() => {
        observer.disconnect();
        const select = findSelect(selectors, pattern);
        resolve(
          select
          && optionSignature(select) !== previousSignature
          && findMatchingOption(select, value)
          ? select
          : null,
        );
      }, timeout);
    })
  );

  const fillEntityType = (entityType) => {
    const select = findSelect(
      'select[name*="entity" i], select[id*="entity" i], select[name*="company" i], select[id*="company" i]',
      /entity|company|registration type/i,
    );
    const aliases = {
      BN: ['bn', 'business name', 'business'],
      LTD: ['ltd', 'limited', 'private company'],
      IT: ['it', 'incorporated trustee', 'trustee'],
    }[entityType];
    if (!select || !aliases) {
      return false;
    }
    const option = Array.from(select.options).find((candidate) => {
      const optionText = `${candidate.value} ${candidate.textContent}`.toLowerCase();
      return aliases.some((alias) => optionText.includes(alias));
    });
    return option ? fillSelect(select, option.textContent || option.value) : false;
  };

  const fillClient = async (client, presenterDefaults = {}) => {
    const filled = [];
    const missing = [];
    const fields = [
      [
        'entity name',
        client.entity_name,
        'input[name*="proposed" i], input[id*="proposed" i], input[name*="business" i], input[id*="business" i], input[name*="company" i], input[id*="company" i], input[name*="entity" i], input[id*="entity" i], input[placeholder*="Mekus & Sons" i]',
        /business name|proposed name|company name|entity name|mekus\s*&?\s*sons/i,
      ],
      [
        'NIN',
        client.nin,
        'input[name*="nin" i], input[id*="nin" i]',
        /national identification|\bnin\b/i,
      ],
      [
        'email',
        client.email,
        'input[type="email"], input[name*="email" i], input[id*="email" i]',
        /email/i,
      ],
      [
        'objectives',
        client.objectives,
        'textarea[name*="objective" i], textarea[id*="objective" i], textarea[name*="nature" i], textarea[id*="nature" i], textarea[name*="description" i], textarea[id*="description" i]',
        /objective|nature of business|description/i,
      ],
    ];

    for (const [label, value, selectors, labelPattern] of fields) {
      if (!value) {
        continue;
      }
      const field = findField(selectors, labelPattern);
      if (setValue(field, value)) {
        filled.push(label);
      }
    }

    const presenterFields = [
      ['presenter email', presenterDefaults.email, /presenter.{0,30}email|email.{0,30}presenter/i],
      ['presenter phone', presenterDefaults.phone, /presenter.{0,30}phone|phone.{0,30}presenter/i],
    ];
    for (const [label, value, labelPattern] of presenterFields) {
      if (!value) {
        continue;
      }
      const field = findByLabel(labelPattern, 'input, select');
      const filledValue = field instanceof HTMLSelectElement
        ? fillSelect(field, value)
        : setValue(field, value);
      if (filledValue) {
        filled.push(label);
      }
    }

    if (client.entity_name && !filled.includes('entity name')) {
      const nameField = findByLabel(
        /business name|proposed name|company name|entity name/i,
        'input',
      ) || document.querySelector('input[name*="name" i], input[id*="name" i]');
      if (setValue(nameField, client.entity_name)) {
        filled.push('entity name');
      }
    }

    if (fillEntityType(client.entity_type)) {
      filled.push('entity type');
    }

    const location = client.location || {};
    const state = String(location.state || client.state || presenterDefaults.state || '').trim();
    const lga = String(location.lga || client.lga || presenterDefaults.lga || '').trim();
    const stateSelect = findSelect(
      'select[name="state" i], select[id="state" i], select[name*="state" i], select[id*="state" i]',
      /state/i,
      /presenter|lga|local government/i,
    );
    if (state) {
      if (stateSelect && fillSelect(stateSelect, state)) {
        filled.push('state');
        await new Promise((resolve) => setTimeout(resolve, 150));
        if (lga) {
          const lgaSelect = findSelect(
            'select[name="lga" i], select[id="lga" i], select[name*="lga" i], select[id*="lga" i], select[name*="localgovernment" i], select[id*="localgovernment" i]',
            /lga|local government area/i,
          );
          if (
            lgaSelect
            && await waitForOption(lgaSelect, lga, 3500)
            && fillSelect(lgaSelect, lga)
          ) {
            filled.push('LGA');
          } else {
            missing.push('LGA');
          }
        }
      } else {
        missing.push('state');
        if (lga) missing.push('LGA');
      }
    } else if (lga) {
      missing.push('state');
      missing.push('LGA');
    }

    const activities = client.business_activities || {};
    const principalActivity = String(
      activities.principal
        || client.principal_activity
        || client.principal_business_activity
        || client.nature_category
        || '',
    ).trim();
    const specificActivity = String(
      activities.specific
        || client.specific_activity
        || client.specific_business_activity
        || client.specific_nature
        || '',
    ).trim();
    const principalSelect = findSelect(
      'select[name="principalActivity" i], select[id*="principal" i], select[name*="principal" i]',
      /principal business activity/i,
      /specific/i,
    );
    const specificSelectSelectors =
      'select[name="specificActivity" i], select[id*="specific" i], select[name*="specific" i]';
    const specificSelectPattern = /specific business activity/i;
    if (principalActivity) {
      const specificSelect = specificActivity
        ? findSelect(specificSelectSelectors, specificSelectPattern)
        : null;
      const previousSpecificOptions = optionSignature(specificSelect);
      const specificOptionUpdate = specificSelect
        ? waitForDependentOption(
          specificSelectSelectors,
          specificSelectPattern,
          specificActivity,
          previousSpecificOptions,
        )
        : Promise.resolve(null);
      if (principalSelect && fillSelect(principalSelect, principalActivity)) {
        filled.push('principal business activity');
        if (specificActivity) {
          const updatedSpecificSelect = await specificOptionUpdate;
          if (updatedSpecificSelect && fillSelect(updatedSpecificSelect, specificActivity)) {
            filled.push('specific business activity');
          } else {
            missing.push('specific business activity');
          }
        }
      } else {
        missing.push('principal business activity');
        if (specificActivity) missing.push('specific business activity');
      }
    }
    return { filled, missing };
  };

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id) {
      return false;
    }

    if (message?.type === 'PROCAC_PING' && isCacPortal(location.hostname)) {
      sendResponse({ ready: true });
      return false;
    }

    if (
      message?.type !== 'PROCAC_FILL_CLIENT'
      || !isCacPortal(location.hostname)
      || !message.client
      || typeof message.client.entity_name !== 'string'
    ) {
      return false;
    }

    fillClient(message.client, message.presenterDefaults).then(({ filled, missing }) => {
      sendResponse({
        status: missing.length === 0 && filled.length > 0 ? 'success' : 'failure',
        fields_populated: filled.length,
        message: [
          filled.length ? `Filled: ${filled.join(', ')}.` : 'No matching CAC form fields were filled.',
          missing.length ? `Could not match: ${missing.join(', ')}.` : '',
          'Review the fields before submitting on the portal. No submission was made.',
        ].filter(Boolean).join(' '),
      });
    }).catch(() => {
      sendResponse({
        status: 'failure',
        fields_populated: 0,
        message: 'Could not match the saved profile to this form. No submission was made.',
      });
    });
    return true;
  });
})();