import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Icon, Logo, ThemeToggle } from './common'

/** Общая шапка верхнеуровневых страниц (главная / проекты / база знаний). */
export function SiteHeader({ actions }: { actions?: ReactNode }) {
  const cls = ({ isActive }: { isActive: boolean }) =>
    'btn btn-ghost btn-sm ' + (isActive ? '!text-brand' : '')
  return (
    <header className="sticky top-0 z-30 border-b shrink-0"
      style={{ background: 'color-mix(in srgb, var(--c-surface) 88%, transparent)',
        borderColor: 'var(--c-line)', backdropFilter: 'blur(8px)' }}>
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-2">
        <Link to="/" className="flex items-center shrink-0"><Logo /></Link>
        <nav className="flex items-center gap-1 ml-2">
          <NavLink to="/projects" className={cls}>
            <Icon name="doc" className="w-4 h-4" /><span className="hidden sm:inline">Проекты</span>
          </NavLink>
          <NavLink to="/kb" className={cls}>
            <Icon name="book" className="w-4 h-4" /><span className="hidden sm:inline">База знаний</span>
          </NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-1.5">
          <ThemeToggle />
          {actions}
        </div>
      </div>
    </header>
  )
}
