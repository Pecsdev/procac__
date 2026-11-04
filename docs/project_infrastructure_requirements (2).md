# CAC AutoFill Pro - Complete Platform & Infrastructure Specification

CAC AutoFill Pro is a specialized SaaS platform designed for Nigerian legal practitioners, accountants, corporate consultants, and agency operators. It automates client data entry directly into the Corporate Affairs Commission (CAC) portals (Business Names, Company Incorporations, and Incorporated Trustees).

---

## 1. System Architecture & Core Stack

### Frontend Application
* **Framework**: React 18.x with Vite 5.x
* **UI & Styling Framework**: Bootstrap 6 (`bootstrap@6.0.0-alpha.1` / native modern CSS variables & Sass modules)
* **Iconography**: `lucide-react` (v0.263+)
* **State & Data Handling**: Zustand / Redux Toolkit (Client profile state management)
* **Language/Runtime**: JavaScript (ES6+) / React JSX (Node.js v20 LTS development environment)

### Extension & In-Browser Automation Engine
* **Target Platforms**: Google Chrome Web Store, Microsoft Edge Add-ons
* **Extension Standard**: Chrome Extensions Manifest V3
* **Scripting**: Native MutationObserver APIs for dynamically loaded Angular/React shadow DOMs on CAC portals (`crp.cac.gov.ng` & `pre.cac.gov.ng`).

---

## 2. Infrastructure & Cloud Deployment

### Web Application & API Hosting
* **Primary Hosting**: Vercel / Netlify / Cloudflare Pages (SPA configuration with all routing fallback to `/index.html`)
* **CDN & Edge Security**: Global CDN distribution with automated SSL/TLS (TLS 1.3) auto-provisioned via Let's Encrypt
* **API Server (Phase 2)**: Node.js (Express/Fastify) or Python (FastAPI) deployed on AWS App Runner / DigitalOcean App Platform

### Database & Client Data Persistence
* **Local MVP Storage**: Browser `localStorage` & `IndexedDB` for client-side templates, pending CAC submissions, and offline session buffers (~5MB–10MB allocation).
* **Production Database (Phase 2)**: PostgreSQL (via Supabase or AWS RDS)
  * **Data Encryption**: AES-256 at rest for sensitive client records (NIN, BVN, RC numbers, passport copies).
  * **Multi-Tenancy Isolation**: Row-Level Security (RLS) ensuring strict data separation between corporate consulting firms.

---

## 3. Platform Modules & Technical Requirements

### A. Browser Extension Module (Manifest V3)
* **Permissions**: `storage`, `activeTab`, `scripting`, `host_permissions` (`https://*.cac.gov.ng/*`)
* **Features**:
  * Real-time field matching for Business Name Registration, Company Directors/Shareholders, and Incorporated Trustee details.
  * Native DOM event dispatching (`input`, `change`, `blur`) to guarantee reactive CAC form validation accepts injected fields.
  * Direct synchronization with the main dashboard for one-click field population.

### B. OCR & Document Extraction Engine
* **Technology**: Tesseract.js (Client-side execution) or AWS Textract / Google Cloud Vision API (Serverless backend).
* **Scope**: Automated extraction of full names, date of birth, addresses, and ID numbers from uploaded NIN slips, Drivers Licenses, and International Passports.
* **Document Generation**: Automated PDF assembly for ready-to-sign CAC attachments (Statutory Declarations, Board Resolutions, Trustee Constitution excerpts).

### C. CAC Portal Health & Anti-Drop Monitor
* **Portal Status Monitor**: Asynchronous ping worker testing CAC CRP portal latency, uptime status, and active session drop rates.
* **Alerting**: Live UI status badge (Green/Yellow/Red) in the consultant dashboard and extension.
* **Auto-Draft Protection**: Client-side background auto-save protecting inputs against session timeouts or portal crashes during peak operational hours.

### D. Role-Based Access Control (RBAC) & Audit Logs
* **Role Hierarchy**:
  * `Owner / Senior Partner`: Managing billing, agency seats, full client registry, and audit logs.
  * `Legal / Compliance Officer`: Form review, verification, and automated CAC injection authorization.
  * `Data Entry / Junior Consultant`: Client profile drafting and document uploads (restricted export privileges).
* **Audit Logger**: Append-only log tracking profile creations, data edits, and CAC portal export timestamps.

---

## 4. Bootstrap 6 Design Setup & Palette

### Design Vision
A professional, modern, high-contrast workspace crafted for high productivity. The interface uses a deep, authorative Dark Blue structural layer combined with soft, low-strain Meek background and surface tones.

### Color Palette Tokens

| Category | Role | Hex Code | Description |
| :--- | :--- | :--- | :--- |
| **Primary** | Dark Blue Header & Action Base | `#1E3A8A` | Primary branding, buttons, active states |
| **Primary Dark** | Navigation Sidebar & Deep Structural UI | `#0F172A` | Background for app sidebars & top bars |
| **Meek Base** | Application Workspace Background | `#F8FAFC` | Muted background reducing visual fatigue |
| **Meek Card** | Form Cards & Content Containers | `#FFFFFF` | High-contrast clean content area |
| **Meek Border** | Subdued Dividers & Inputs | `#E2E8F0` | Soft structural borders |
| **Meek Muted** | Secondary Text & Microcopy | `#64748B` | Labels, timestamps, and metadata |

### Bootstrap 6 Custom CSS & Theme Setup

Using Bootstrap 6 modern CSS tokens and root variables, implement the stylesheet below (`src/styles/theme.css`):

```css
/* CAC AutoFill Pro - Bootstrap 6 Dark Blue & Meek Theme Specification */

:root, :host {
  /* Dark Blue Palette Tokens */
  --bs-primary: #1e3a8a;
  --bs-primary-rgb: 30, 58, 138;
  --bs-dark-blue-deep: #0f172a;
  
  /* Meek & Soft UI Tokens */
  --bs-meek-bg: #f8fafc;
  --bs-meek-card: #ffffff;
  --bs-meek-border: #e2e8f0;
  --bs-meek-text-muted: #64748b;
  --bs-meek-text-main: #0f172a;
  
  /* Global Overrides */
  --bs-body-bg: var(--bs-meek-bg);
  --bs-body-color: var(--bs-meek-text-main);
  --bs-font-sans-serif: 'Inter', system-ui, -apple-system, sans-serif;
  --bs-border-radius: 0.5rem;
  --bs-border-radius-lg: 0.75rem;
}

/* Base Layout & App Container */
body {
  background-color: var(--bs-meek-bg);
  color: var(--bs-meek-text-main);
}

/* Sidebar Navigation (Dark Blue Theme) */
.sidebar-navigation {
  background-color: var(--bs-dark-blue-deep);
  color: #ffffff;
}

.sidebar-navigation .nav-link {
  color: #94a3b8;
  transition: all 0.2s ease-in-out;
}

.sidebar-navigation .nav-link.active,
.sidebar-navigation .nav-link:hover {
  color: #ffffff;
  background-color: rgba(255, 255, 255, 0.08);
  border-left: 3px solid #3b82f6;
}

/* Main Workspace Panels (Meek Card Design) */
.card-meek {
  background-color: var(--bs-meek-card);
  border: 1px solid var(--bs-meek-border);
  border-radius: var(--bs-border-radius-lg);
  box-shadow: 0 1px 3px 0 rgba(15, 23, 42, 0.05);
}

.card-meek .card-header {
  background-color: transparent;
  border-bottom: 1px solid var(--bs-meek-border);
  font-weight: 600;
  color: var(--bs-dark-blue-deep);
}

/* Form Inputs & Controls */
.form-control-meek {
  background-color: #ffffff;
  border: 1px solid var(--bs-meek-border);
  color: var(--bs-meek-text-main);
  border-radius: var(--bs-border-radius);
}

.form-control-meek:focus {
  border-color: var(--bs-primary);
  box-shadow: 0 0 0 0.25rem rgba(30, 58, 138, 0.15);
}

/* Status Indicator Badges */
.badge-portal-online {
  background-color: #dcfce7;
  color: #166534;
}

.badge-portal-warning {
  background-color: #fef9c3;
  color: #854d0e;
}

.badge-portal-offline {
  background-color: #fee2e2;
  color: #991b1b;
}
```

---

## 5. Security & Compliance Guidelines

1. **NDPR / Data Privacy Compliance**: All client registrations involve sensitive personal data (NIN, residential address, signatures). Local storage must be cleared upon user logout.
2. **CSP Rules**: Enforce strict script sources (`script-src 'self'`) to prevent cross-site scripting (XSS) when running auto-fill procedures inside external browser tabs.
3. **CAC Portal Integrity**: Extension code must not bypass CAC official payment gateways or signature validations—only automate repetitive input fields.