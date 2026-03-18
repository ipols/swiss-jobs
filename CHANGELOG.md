# Changelog

## Week of March 18, 2026

### New Features

- **AI Exposure Treemap** — Initial release: interactive treemap visualizing AI exposure across 406 Swiss occupations
- **Multilingual Support** — Full French and German translations with language selector alongside English
- **GitHub Pages Deployment** — CI/CD workflow for automatic deployment on push to `main`

### Bug Fixes

- **Locale-aware number formatting** (#1) — Fixed number abbreviations for FR/DE locales. Now correctly shows "Md"/"Mio." (FR) and "Mrd."/"Mio." (DE) instead of hardcoded English "B" and "M". All number formatting consolidated through `formatNumber()`

### Other Improvements

- Polished copy: clearer title, intro text, and terminology
- Added author credit to footer
- Updated README with i18n documentation and translation pipeline steps
- Added screenshot to README
