import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium',
  {
    variants: {
      variant: {
        default: 'bg-secondary text-secondary-foreground border-border',
        green:   'bg-emerald-50 text-emerald-700 border-emerald-200',
        yellow:  'bg-amber-50 text-amber-700 border-amber-200',
        red:     'bg-rose-50 text-rose-700 border-rose-200',
        blue:    'bg-sky-50 text-sky-700 border-sky-200',
        purple:  'bg-violet-50 text-violet-700 border-violet-200',
        outline: 'bg-transparent text-muted-foreground border-border',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
