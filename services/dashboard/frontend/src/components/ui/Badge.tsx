import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-white/10 text-white',
        secondary: 'border-transparent bg-white/5 text-muted-foreground',
        destructive: 'border-transparent bg-red-500/10 text-red-400',
        outline: 'border-white/10 text-muted-foreground',
        success: 'border-transparent bg-green-500/10 text-green-400',
        warning: 'border-transparent bg-yellow-500/10 text-yellow-400',
        info: 'border-transparent bg-blue-500/10 text-blue-400',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
