import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-xl text-sm font-medium transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-raydium-purple focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:
          'bg-gradient-to-r from-raydium-purple to-raydium-blue text-white hover:opacity-90 shadow-neon-purple',
        destructive:
          'bg-red-500/20 text-red-400 border border-red-500/40 hover:bg-red-500/30 hover:shadow-neon-pink',
        outline:
          'border border-raydium-purple/30 bg-raydium-card/50 hover:bg-raydium-purple/20 hover:border-raydium-purple/50 hover:shadow-neon-purple',
        secondary:
          'bg-raydium-card text-foreground border border-white/10 hover:bg-raydium-cardHover hover:border-raydium-cyan/30',
        ghost: 'hover:bg-raydium-purple/10 hover:text-raydium-purpleLight',
        link: 'text-raydium-purpleLight underline-offset-4 hover:underline',
        glow: 'bg-gradient-to-r from-raydium-purple to-raydium-cyan text-white animate-pulse-glow shadow-neon-purple',
        neon: 'bg-raydium-purple/20 text-raydium-purpleLight border border-raydium-purple/50 hover:bg-raydium-purple/30 hover:border-raydium-purple hover:shadow-neon-purple',
        'neon-cyan': 'bg-raydium-cyan/20 text-raydium-cyanLight border border-raydium-cyan/50 hover:bg-raydium-cyan/30 hover:border-raydium-cyan hover:shadow-neon-cyan',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 rounded-lg px-3',
        lg: 'h-11 rounded-xl px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
