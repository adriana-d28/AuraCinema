// Settings: private account management (PLACEHOLDER).
//
// Settings favours clarity over cinematic effects: plain panels and forms.
// Following the original wireframe it has three groups:
//   - Profile information (picture, bio, location)  [needs backend]
//   - Account information (name, email, password)   [needs backend]
//     The API has no endpoints to change these yet; the intermediate backend
//     phase will add them. All fields and "Save changes" are disabled.
//   - Session (log out)                             [later frontend phase]
//     Logging out only means forgetting the login token in the browser, so it
//     needs no backend endpoint. It is enabled together with sign-in.

import { Button } from '../components/ui/Button'
import { Panel } from '../components/ui/Panel'
import { SectionHeading } from '../components/ui/SectionHeading'
import { TextField } from '../components/ui/TextField'
import styles from './SettingsPage.module.css'

export function SettingsPage() {
  return (
    <div className="container page">
      <title>Settings · AuraCinema</title>

      <SectionHeading
        as="h1"
        eyebrow="Private · only you can see this"
        title="Settings"
        description="Manage your profile and account details."
      />

      <div className={styles.layout}>
        <Panel title="Profile information" comingSoon>
          <div className={styles.picture}>
            <div className={styles.picturePreview} aria-hidden="true" />
            <Button variant="secondary" size="sm" disabled>
              Upload picture
            </Button>
          </div>
          <TextField label="Location" placeholder="e.g. Dublin, Ireland" disabled />
          <TextField label="Short bio" placeholder="A few words about your film taste" multiline disabled />
        </Panel>

        <div className={styles.column}>
          {/* A real <form>, so these fields will work with Enter/submit when enabled. */}
          <Panel title="Account information" comingSoon>
            <form className={styles.form} onSubmit={(event) => event.preventDefault()}>
              {/* The panel already shows "Coming soon", so the fields are only disabled. */}
              <TextField label="Name" autoComplete="name" disabled />
              <TextField label="Email" type="email" autoComplete="email" disabled />
              <TextField
                label="New password"
                type="password"
                autoComplete="new-password"
                hint="At least 15 characters."
                disabled
              />
              <div>
                <Button type="submit" disabled>
                  Save changes
                </Button>
              </div>
            </form>
          </Panel>

          <Panel title="Session">
            <p>Log out of AuraCinema on this device.</p>
            <div>
              <Button variant="secondary" disabled>
                Log out
              </Button>
            </div>
            <p className={styles.note}>Available once sign-in is connected in the next phase.</p>
          </Panel>
        </div>
      </div>
    </div>
  )
}
