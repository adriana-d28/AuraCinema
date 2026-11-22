// The top bar shown on every page of the main application.
//
// It contains:
//   - the AuraCinema wordmark (a link back to Discover);
//   - the main navigation: Discover, Recommendations, Watchlist, Profile.
//     Settings is reached from the Profile page, as in the original wireframes.
//     Taste Evolution is NOT part of the first iteration, so it is not listed;
//   - a "Log in" link. Once authentication exists (next frontend phase) this
//     place will hold the signed-in user's menu instead.
//
// On small screens the links are folded behind a "Menu" button. The button
// tells screen readers whether the menu is open (aria-expanded) and which
// element it controls (aria-controls).

import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router'
import styles from './Header.module.css'

// One list drives the navigation, so adding a page later is a one-line change.
const MAIN_NAVIGATION = [
  { to: '/', label: 'Discover' },
  { to: '/recommendations', label: 'Recommendations' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/profile', label: 'Profile' },
] as const

export function Header() {
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the mobile menu after a link is chosen (the new page is shown).
  const closeMenu = () => setMenuOpen(false)

  // Close the mobile menu with the Escape key (expected keyboard behaviour).
  useEffect(() => {
    if (!menuOpen) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [menuOpen])

  return (
    <header className={styles.header}>
      <div className={`container ${styles.inner}`}>
        <Link to="/" className={styles.brand} aria-label="AuraCinema, go to Discover" onClick={closeMenu}>
          <span className={styles.brandAura}>Aura</span>
          <span className={styles.brandCinema}>Cinema</span>
        </Link>

        {/* Only visible on small screens (see Header.module.css). */}
        <button
          type="button"
          className={styles.menuButton}
          aria-expanded={menuOpen}
          aria-controls="main-navigation"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span className={styles.menuIcon} aria-hidden="true" />
          {menuOpen ? 'Close' : 'Menu'}
        </button>

        <nav
          id="main-navigation"
          aria-label="Main"
          className={`${styles.nav} ${menuOpen ? styles.navOpen : ''}`}
        >
          <ul role="list" className={styles.navList}>
            {MAIN_NAVIGATION.map((item) => (
              <li key={item.to}>
                {/*
                  NavLink adds aria-current="page" to the link of the current
                  page; the CSS uses it to draw the burgundy underline.
                  "end" makes Discover ("/") active only on the home page,
                  not on every page that starts with "/".
                */}
                <NavLink to={item.to} end={item.to === '/'} className={styles.navLink} onClick={closeMenu}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <Link to="/login" className={styles.login} onClick={closeMenu}>
            Log in
          </Link>
        </nav>
      </div>
    </header>
  )
}
