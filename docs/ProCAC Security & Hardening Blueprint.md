# ProCAC Security & Hardening Blueprint

This document outlines the security architecture and multi-layered defense strategy for **ProCAC**, ensuring full protection of sensitive client data (such as National Identification Numbers, director profiles, and corporate registration payloads) and compliance with Nigerian data protection standards.

---

## 1. FastAPI Backend & API Security (The Guardhouse)
The Python backend is the core processor of all client records and must be protected against malicious payloads, automated attacks, and unauthorized access.

* **JWT (JSON Web Tokens) with Expiry:** 
  * Authenticated consultants receive a cryptographically signed JWT upon login.
  * Tokens must have short expiration windows (15–30 minutes) accompanied by secure, rotation-enabled refresh tokens.
* **Strict Pydantic Input Validation:** 
  * FastAPI's built-in Pydantic models automatically sanitize and validate all incoming data fields (e.g., forcing 11-digit regex validation for NINs, proper email formats), blocking SQL injection and XSS attempts at the gateway.
* **Rate Limiting:** 
  * Implement rate limiting (using libraries like `slowapi`) on high-risk endpoints such as `/api/auth/login`, `/api/auth/signup`, and public client intake endpoints to thwart brute-force and DDoS bot spam.

---

## 2. Data Encryption (The Vault)
Safeguarding sensitive consultant and client data both in transit and at rest.

* **HTTPS / TLS 1.3 Enforcement:** 
  * All communications between the client WhatsApp intake form, the consultant dashboard, and the FastAPI server must be encrypted via SSL/TLS certificates.
* **Field-Level Encryption for NINs:** 
  * Ultra-sensitive fields (such as client National Identity Numbers and private phone numbers) must be encrypted in the database using **AES-256 encryption** (via Python's `cryptography` library). Even if the database is dumped, plain-text NINs remain unreadable.
* **Zero CAC Password Policy:** 
  * In alignment with ProCAC's core architecture, **never** store official CAC CRP portal passwords. The system only executes DOM injection on active browser sessions, ensuring zero liability if a consultant's account is compromised externally.

---

## 3. Chrome Extension & DOM Security (The Bridge)
Browser extensions interact directly with live portal DOMs and require strict execution boundaries.

* **Manifest V3 Architecture:** 
  * Build the extension using Manifest V3 to leverage strict Content Security Policies (CSP) that block remote code execution and unverified third-party scripts.
* **Locked CORS Policy on FastAPI:** 
  * Configure CORS middleware on your FastAPI server to restrict requests **exclusively** to your official domain (`procac.ng`) and your specific Chrome Extension ID (`chrome-extension://<your-extension-id>`). Reject all wildcard (`*`) requests.
* **Secure Extension Storage:** 
  * Store consultant session keys and tokens inside `chrome.storage.local` using extension-level encryption rather than vulnerable web cookies or `localStorage`.

---

## 4. Payment Webhook Security (The Cashier)
Securing subscription payments processed via Paystack.

* **HMAC SHA-512 Signature Verification:** 
  * When Paystack sends a webhook notification confirming a consultant's subscription payment (Starter, Standard, Premium, Enterprise), your FastAPI server must verify the incoming `x-paystack-signature` header against your secret webhook key before updating subscription statuses in the database. This prevents fake payment spoofing.

---

## 5. WhatsApp Intake Link Security (The Gateway)
Protecting client intake URLs shared over messaging apps.

* **Cryptographic UUIDs:** 
  * Generate unpredictable, cryptographically secure random tokens for client intake links (e.g., `procac.ng/intake/a9f8-41b2-9c31-e78d`). Never use sequential database IDs (e.g., `/intake/1`, `/intake/2`) which allow malicious scraping.
* **Link Expiration & One-Time Use:** 
  * Configure intake links to expire automatically after a set window (e.g., 48 hours) or self-deactivate immediately after the client successfully submits their registration payload.

---

## Summary Checklist for Deployment
1. [ ] Enforce environment variables (`.env`) for database URLs, JWT secrets, and Paystack API keys.
2. [ ] Enable database automated daily backups with encryption.
3. [ ] Configure strict security headers (HSTS, X-Content-Type-Options) on the FastAPI server.