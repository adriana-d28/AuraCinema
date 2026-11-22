// Buttons in two forms that look exactly the same:
//   - <Button>      for actions on the current page (it renders a <button>);
//   - <ButtonLink>  for moving to another page (it renders a router <Link>).
// Using the correct element matters for accessibility: screen readers announce
// "button" and "link" differently, and the keyboard behaves differently too.
//
// Variants:
//   primary   - burgundy, the single main action of an area ("View details")
//   secondary - outlined, for less important actions ("Browse catalogue")
//   ghost     - text only, for quiet actions ("Filters")

import type { ButtonHTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router'
import styles from './Button.module.css'

type ButtonVariant = 'primary' | 'secondary' | 'ghost'
type ButtonSize = 'md' | 'sm'

interface StyleProps {
  variant?: ButtonVariant
  size?: ButtonSize
}

// Joins the CSS classes for a variant and size (shared by both components).
function classesFor(variant: ButtonVariant, size: ButtonSize, extra?: string) {
  return [styles.button, styles[variant], styles[size], extra].filter(Boolean).join(' ')
}

type ButtonProps = StyleProps & ButtonHTMLAttributes<HTMLButtonElement>

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  // Default to "button" so a button inside a form never submits it by accident.
  type = 'button',
  ...rest
}: ButtonProps) {
  return <button type={type} className={classesFor(variant, size, className)} {...rest} />
}

type ButtonLinkProps = StyleProps & LinkProps

export function ButtonLink({ variant = 'primary', size = 'md', className, ...rest }: ButtonLinkProps) {
  return <Link className={classesFor(variant, size, className)} {...rest} />
}
