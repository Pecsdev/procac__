(() => {
  const getCSRFToken = () => {
    const cookie = document.cookie
      .split(';')
      .map((value) => value.trim())
      .find((value) => value.startsWith('csrftoken='));
    if (cookie) {
      return decodeURIComponent(cookie.slice('csrftoken='.length));
    }
    return document.querySelector('#payment-csrf-token [name="csrfmiddlewaretoken"]')?.value;
  };
  const csrfToken = getCSRFToken();

  if (!csrfToken) {
    return;
  }

  document.querySelectorAll('[data-subscribe-plan]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (button.disabled) {
        return;
      }

      const plan = button.dataset.subscribePlan;
      const errorContainer = document.querySelector(
        button.dataset.paymentErrorTarget || '#payment-error',
      );
      const errorMessage = errorContainer?.querySelector(
        '[data-payment-error-message], #payment-error-message',
      );
      const loginLink = errorContainer?.querySelector(
        '[data-payment-login-link], #payment-login-link',
      );
      if (!errorContainer || !errorMessage) {
        return;
      }

      const originalContent = button.innerHTML;
      const originalWidth = button.offsetWidth;
      errorContainer.hidden = true;
      if (loginLink) {
        loginLink.hidden = true;
      }
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.style.minWidth = `${originalWidth}px`;
      button.innerHTML = '<span class="checkout-spinner" role="status" aria-hidden="true"></span>Starting checkout...';

      try {
        const response = await fetch('/api/payments/initialize/', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'Accept': 'application/json',
          },
          body: JSON.stringify({ plan }),
        });
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
          throw new Error('The payment service returned an unexpected response. Please try again.');
        }

        const result = await response.json();
        if (response.status === 401) {
          errorMessage.textContent = result.error || 'Please sign in to start a subscription.';
          if (loginLink) {
            loginLink.hidden = false;
          }
          errorContainer.hidden = false;
          return;
        }
        if (!response.ok) {
          throw new Error(result.error || 'Unable to start checkout. Please try again.');
        }

        const authorizationUrl = new URL(result.authorization_url);
        if (
          authorizationUrl.protocol !== 'https:'
          || authorizationUrl.hostname !== 'checkout.paystack.com'
        ) {
          throw new Error('The payment service returned an invalid checkout link.');
        }
        window.location.href = authorizationUrl.href;
      } catch (error) {
        errorMessage.textContent = error instanceof Error
          ? error.message
          : 'Unable to start checkout. Please try again.';
        errorContainer.hidden = false;
      } finally {
        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.style.minWidth = '';
        button.innerHTML = originalContent;
      }
    });
  });
})();
