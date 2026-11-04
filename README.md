# ProCAC Django app

## Run locally

From the project root, activate the virtual environment and start Django:

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. The frontend pages are routed as `/`, `/login/`,
`/signup/`, `/dashboard/`, `/intake/`, and `/admin-panel/`.

Install dependencies into the virtual environment with:

```powershell
python -m pip install -r requirements.txt
```

## Paystack payments

Set these variables in the project-root `.env` file. Keep this file private and
never commit it:

```text
PAYSTACK_PUBLIC_KEY=pk_test_...
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_CALLBACK_URL=
```

Paystack signs webhook bodies with `PAYSTACK_SECRET_KEY`; the signature is
verified using the untouched raw request body. `PAYSTACK_CALLBACK_URL` is
optional; the dashboard URL is used when it is empty.
The authenticated initialization endpoint is `POST /api/payments/initialize/`
with JSON such as `{"plan":"standard"}`. Configure Paystack to send event
notifications to `/api/payments/paystack-webhook/`. Successful signed
`charge.success` events update the matching subscription to successful only
when the amount and currency match the stored payment.

Run migrations after adding the payment model:

```powershell
python manage.py migrate
```

## Chrome extension connection

The extension popup calls Django at `http://127.0.0.1:8000` and includes the
browser session credentials. To enable credentialed CORS only for this
extension, load `extension/` in Chrome, enable Developer mode at
`chrome://extensions`, and copy the ProCAC extension ID. Set it in the
project-root `.env` file:

```text
PROCAC_EXTENSION_ID=your_32_character_chrome_extension_id
```

Install updated dependencies with `python -m pip install -r requirements.txt`,
then restart Django. CORS is restricted to that extension origin and the
extension API routes. The session cookie uses cross-site settings only when
the extension ID is configured. Do not enable allow-all CORS for these APIs:
they return private client profiles.

## Frontend files

- HTML templates: `frontend/templates/frontend/`
- Static assets: `frontend/static/frontend/assets/`
- Frontend source (JavaScript and Sass): `frontend/static/frontend/src/`
- Django settings and URL configuration: `config/`