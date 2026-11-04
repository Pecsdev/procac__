(() => {
  const getCSRFToken = (fallbackToken) => {
    const cookie = document.cookie
      .split(";")
      .map((value) => value.trim())
      .find((value) => value.startsWith("csrftoken="));
    return cookie
      ? decodeURIComponent(cookie.slice("csrftoken=".length))
      : fallbackToken;
  };
  const form = document.getElementById("signup-form");
  const button = document.getElementById("signup-submit");
  const errorContainer = document.getElementById("signup-error");

  if (!form || !button || !errorContainer) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorContainer.hidden = true;

    if (!form.reportValidity()) {
      return;
    }

    const formData = new FormData(form);
    const password = formData.get("password1");
    const confirmPassword = formData.get("password2");
    if (typeof password !== "string" || password.length < 8) {
      errorContainer.textContent =
        "Password must be at least 8 characters long.";
      errorContainer.hidden = false;
      return;
    }
    if (password !== confirmPassword) {
      errorContainer.textContent = "The passwords do not match.";
      errorContainer.hidden = false;
      return;
    }

    const csrfToken = getCSRFToken(
      form.querySelector('[name="csrfmiddlewaretoken"]')?.value,
    );
    const submitLabel = button.querySelector("span");
    const originalLabel = submitLabel?.textContent || button.textContent.trim();
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.innerHTML =
      '<span class="signup-spinner" role="status" aria-hidden="true"></span><span>Sending verification code...</span>';

    try {
      const signupResponse = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
          Accept: "application/json",
        },
        body: JSON.stringify({
          full_name: formData.get("full_name"),
          accreditation_number: formData.get("accreditation_number"),
          email: formData.get("email"),
          phone_number: formData.get("phone_number"),
          firm_name: formData.get("firm_name"),
          password1: password,
          password2: confirmPassword,
        }),
      });
      const signupResult = await signupResponse.json();
      if (!signupResponse.ok) {
        const validationMessages = Object.values(signupResult.errors || {})
          .flatMap((errors) => errors.map((error) => error.message))
          .filter(Boolean);
        throw new Error(
          validationMessages.join(" ") ||
            signupResult.error ||
            "Unable to create your account. Please check your details and try again.",
        );
      }
      if (!signupResult.verification_required || !signupResult.verify_url) {
        throw new Error(
          "Unable to start email verification. Please try again.",
        );
      }
      window.location.assign(signupResult.verify_url);
    } catch (error) {
      errorContainer.textContent =
        error instanceof Error
          ? error.message
          : "Unable to create your account. Please try again.";
      errorContainer.hidden = false;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.innerHTML = `<i class="fa-solid fa-user-plus" aria-hidden="true"></i><span>${originalLabel}</span><i class="fa-solid fa-arrow-right" aria-hidden="true"></i>`;
    }
  });
})();
