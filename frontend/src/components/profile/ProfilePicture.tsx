// The signed-in user's profile picture, or a neutral silhouette when there is none.
//
// The picture is private (owner-only), so it is served by an authenticated
// endpoint. An <img src="..."> cannot send the login token, so the image is
// fetched with the token (GET /users/me/picture), turned into a temporary
// local URL (URL.createObjectURL) and that URL is released when it is no
// longer shown. user.picture_updated_at changes on every upload or removal,
// so the image is fetched again exactly when it changed.

import { useEffect, useState } from 'react'
import { useAuth } from '../../auth/authContext'
import { getPicture } from '../../services/api/users'
import styles from './ProfilePicture.module.css'

interface ProfilePictureProps {
  size?: 'lg' | 'sm'
}

export function ProfilePicture({ size = 'lg' }: ProfilePictureProps) {
  const { token, user } = useAuth()
  const version = user?.picture_updated_at ?? null
  // The URL is remembered together with the version it belongs to, so an old
  // picture is never shown after a change.
  const [loaded, setLoaded] = useState<{ version: string; url: string } | null>(null)

  useEffect(() => {
    if (!token || version === null) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    getPicture(token, controller.signal)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        setLoaded({ version, url: objectUrl })
      })
      // On failure the silhouette stays: the picture is decorative here.
      .catch(() => undefined)
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [token, version])

  const url = loaded !== null && loaded.version === version ? loaded.url : null

  return (
    <div className={`${styles.picture} ${styles[size]}`}>
      {url ? (
        <img src={url} alt="Your profile picture" />
      ) : (
        <svg viewBox="0 0 48 48" focusable="false" aria-hidden="true">
          <circle cx="24" cy="18" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M9 41c2.5-8 8.5-12 15-12s12.5 4 15 12" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      )}
    </div>
  )
}
