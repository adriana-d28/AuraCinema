// The shared frame of the main application: header on top, footer at the
// bottom, and the current page in between.
//
// <Outlet /> is the "slot" where React Router places the page that matches
// the address (Discover, Watchlist, ...). The header and footer therefore
// stay in place, and only the middle part changes when the user navigates.

import { Outlet, ScrollRestoration } from 'react-router'
import { Footer } from './Footer'
import { Header } from './Header'
import styles from './AppLayout.module.css'

export function AppLayout() {
  return (
    <div className={styles.shell}>
      {/*
        "Skip to main content": the first thing keyboard users reach with Tab.
        It lets them jump past the navigation. It is only visible when focused.
      */}
      <a href="#main-content" className={styles.skipLink}>
        Skip to main content
      </a>
      <Header />
      {/* tabIndex={-1} lets the skip link move the keyboard focus here. */}
      <main id="main-content" tabIndex={-1} className={styles.main}>
        <Outlet />
      </main>
      <Footer />
      {/* Scrolls to the top when a new page opens (and back to the old position on "Back"). */}
      <ScrollRestoration />
    </div>
  )
}
