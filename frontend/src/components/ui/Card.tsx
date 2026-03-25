import * as React from 'react'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-xl border border-border bg-card shadow-sm', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center justify-between px-4 py-3 border-b border-border', className)}
      {...props}
    >
      {typeof children === 'string'
        ? <span className="text-sm font-semibold text-foreground">{children}</span>
        : children}
    </div>
  )
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 py-3', className)} {...props} />
}

export function StatCard({
  label,
  value,
  sub,
  valueClass,
  tooltip,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
  valueClass?: string
  tooltip?: string
}) {
  return (
    <Card className="px-4 py-3">
      <div className="flex items-center gap-1 mb-1">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider leading-tight">{label}</span>
        {tooltip && (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-muted-foreground/40 text-muted-foreground/60 text-[9px] font-bold cursor-default shrink-0 hover:border-muted-foreground/70 hover:text-muted-foreground transition-colors">
                  i
                </span>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-[200px] text-center">
                {tooltip}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>
      <div className={cn('text-lg font-semibold tabular-nums text-foreground truncate', valueClass)}>{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5 truncate">{sub}</div>}
    </Card>
  )
}
