// Shared set-up for every test file (referenced in vite.config.ts).
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom (the fake browser) cannot scroll. React Router's <ScrollRestoration>
// calls window.scrollTo on every page change, so a do-nothing version is
// provided to keep the test output free of "not implemented" warnings.
window.scrollTo = () => {}

// Remove whatever the previous test rendered, so each test starts from an
// empty page and tests cannot affect each other.
afterEach(() => {
  cleanup()
})
