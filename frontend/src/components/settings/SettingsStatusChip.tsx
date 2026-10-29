type Variant = 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'muted'

type Props = {
  label: string
  variant?: Variant
  title?: string
}

export function SettingsStatusChip({ label, variant = 'neutral', title }: Props) {
  return (
    <span className={`ih-status-chip ih-status-chip--${variant}`} title={title}>
      {label}
    </span>
  )
}
