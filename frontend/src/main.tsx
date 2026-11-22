// Entry point: the first file the browser runs (loaded by index.html).
//
// It loads the global styles (which include the design tokens) and draws the
// <App /> component inside <div id="root"> of index.html.
// StrictMode runs extra checks during development to reveal common mistakes;
// it has no effect on the production build.

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import './styles/global.css'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('The #root element is missing from index.html.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
