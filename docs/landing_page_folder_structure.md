# CAC AutoFill Pro - Landing Page Folder Structure

Below is the production-grade folder structure for the **CAC AutoFill Pro** landing page and web application frontend, using **Bootstrap 6** with modern modular organization (Sass/CSS, JS ES modules, components, and extension assets).

```text
cac-autofill-pro/
├── .github/
│   └── workflows/
│       ├── deploy.yml              # CI/CD deployment workflow (e.g., Vercel / Netlify / AWS S3)
│       └── lint-and-test.yml       # Code quality & unit testing pipeline
│
├── public/                         # Static assets served at root
│   ├── favicon.ico
│   ├── favicon-32x32.png
│   ├── apple-touch-icon.png
│   ├── site.webmanifest
│   ├── robots.txt
│   └── assets/
│       ├── images/
│       │   ├── logo/
│       │   │   ├── logo-dark-blue.svg
│       │   │   ├── logo-white.svg
│       │   │   └── favicon-mark.svg
│       │   ├── hero/
│       │   │   ├── dashboard-preview-dark.png
│       │   │   └── extension-popover-demo.png
│       │   ├── features/
│       │   │   ├── bn-autofill-icon.svg
│       │   │   ├── ltd-shareholders-icon.svg
│       │   │   ├── it-trustee-icon.svg
│       │   │   └── nin-ocr-icon.svg
│       │   ├── testimonials/
│       │   │   ├── consultant-1.jpg
│       │   │   └── lawyer-2.jpg
│       │   └── og-image.png        # Open Graph share thumbnail (1200x630)
│       └── fonts/
│           └── inter/              # Local Inter font fallback files
│               ├── Inter-Regular.woff2
│               └── Inter-Bold.woff2
│
├── src/
│   ├── scss/                       # Bootstrap 6 & Custom Theme Styling
│   │   ├── main.scss               # Main Sass entry point
│   │   ├── _variables.scss         # Theme variables (Dark Blue & Meek palette overrides)
│   │   ├── _custom-bootstrap.scss  # Bootstrap 6 module imports
│   │   ├── components/
│   │   │   ├── _navbar.scss        # Dark Blue header navigation styling
│   │   │   ├── _hero.scss          # Hero section styling & portal mock badges
│   │   │   ├── _features.scss      # Feature grids & meek card styling
│   │   │   ├── _pricing.scss       # Subscription matrix styling
│   │   │   ├── _testimonials.scss  # Client reviews & trust badges
│   │   │   └── _footer.scss        # Dark Blue footer navigation
│   │   └── utilities/
│   │       ├── _colors.scss        # Custom dark-blue & meek color utilities
│   │       └── _animations.scss    # Subtle hover transitions & pulsing live indicators
│   │
│   ├── js/                         # JavaScript Modules (ESM)
│   │   ├── main.js                 # Global entry point
│   │   ├── bootstrap.bundle.js     # ESM imports for Bootstrap 6 JS components
│   │   ├── landing/
│   │   │   ├── navbar-scroll.js    # Sticky header transition on scroll
│   │   │   ├── interactive-demo.js # Interactive CAC live form auto-fill simulator on landing page
│   │   │   ├── pricing-toggle.js   # Monthly/Annual pricing switch controller
│   │   │   └── portal-status.js    # Live CAC CRP uptime indicator widget fetcher
│   │   └── utils/
│   │       ├── analytics.js        # Event tracking (Google Analytics / Plausible)
│   │       └── copy-clipboard.js   # Quick copy snippet helper script
│   │
│   └── components/                 # Reusable HTML template partials (if using SSG / Vite / Handlebars)
│       ├── head-meta.html
│       ├── navbar.html
│       ├── hero-section.html
│       ├── feature-bn-ltd-it.html
│       ├── extension-banner.html
│       ├── pricing-plans.html
│       ├── faq-accordion.html
│       └── footer.html
│
├── extension/                      # Chrome / Edge Browser Extension Assets
│   ├── manifest.json               # Chrome Extension Manifest V3 configuration
│   ├── background.js               # Service worker for cross-tab extension messaging
│   ├── content-script.js           # Dynamic CAC portal field injector (`crp.cac.gov.ng`)
│   ├── popup/
│   │   ├── popup.html              # Extension popover UI (Dark Blue header + client dropdown)
│   │   ├── popup.js                # Extension interactive logic
│   │   └── popup.css               # Extension-specific styles
│   └── icons/
│       ├── icon-16.png
│       ├── icon-48.png
│       └── icon-128.png
│
├── .env.example                    # Environment variable template
├── .gitignore                      # Git ignore file list
├── .prettierrc                     # Prettier formatting rules
├── eslint.config.js                # JS code quality rules
├── package.json                    # Node.js dependencies & build scripts
├── README.md                       # Project setup & developer documentation
└── index.html                      # Root landing page HTML template
```

---

## Detailed Directory Explanations

### 1. `src/scss/` (Bootstrap 6 Theme Architecture)
* **`_variables.scss`**: Overrides Bootstrap's default `$primary` brand colors to **Dark Blue (`#0F172A` / `#1E3A8A`)** and configures background surfaces to **Meek Slate (`#F8FAFC` / `#E2E8F0`)**.
* **`_custom-bootstrap.scss`**: Imports only necessary Bootstrap 6 modules (Grid, Navbars, Cards, Buttons, Accordions, Modals) to optimize output bundle size.
* **`components/`**: Modularized SCSS files broken down by landing page section to ensure codebase scalability.

### 2. `src/js/landing/` (Interactive Page Scripts)
* **`interactive-demo.js`**: Drives an embedded live form simulator on the landing page, showing visitors how auto-filling Business Name (BN), Private Limited (LTD), and Incorporated Trustee (IT) forms works before registration.
* **`portal-status.js`**: Fetches real-time status updates from the CAC CRP portal health checker microservice to display an uptime badge on the landing page.

### 3. `extension/` (Browser Extension Context)
* Kept directly within the project repository to allow synchronizing form field mapping changes in `content-script.js` directly alongside frontend landing updates and web app schema releases.

### 4. `public/assets/images/` (Brand & Feature Assets)
* Contains specialized vector graphics and optimized PNG assets tailored for Nigerian legal practitioners, accountants, corporate consultants, and agency operators.