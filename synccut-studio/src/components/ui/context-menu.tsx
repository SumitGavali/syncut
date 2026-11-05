import * as React from 'react';
import * as CM from '@radix-ui/react-context-menu';
import { cn } from '@/lib/utils';

export const ContextMenu = CM.Root;
export const ContextMenuTrigger = CM.Trigger;

export const ContextMenuContent = React.forwardRef<
  React.ElementRef<typeof CM.Content>,
  React.ComponentPropsWithoutRef<typeof CM.Content>
>(({ className, ...props }, ref) => (
  <CM.Portal>
    <CM.Content
      ref={ref}
      className={cn(
        'z-50 min-w-[13rem] overflow-hidden rounded-md border border-[#2a2a32] bg-[#141418] p-1 text-[#ededed] shadow-[0_8px_30px_rgba(0,0,0,0.6)]',
        className,
      )}
      {...props}
    />
  </CM.Portal>
));
ContextMenuContent.displayName = 'ContextMenuContent';

export const ContextMenuItem = React.forwardRef<
  React.ElementRef<typeof CM.Item>,
  React.ComponentPropsWithoutRef<typeof CM.Item>
>(({ className, ...props }, ref) => (
  <CM.Item
    ref={ref}
    className={cn(
      'flex cursor-pointer select-none items-center gap-2 rounded px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-[#00E5FF]/15 data-[highlighted]:text-[#00E5FF]',
      className,
    )}
    {...props}
  />
));
ContextMenuItem.displayName = 'ContextMenuItem';

export const ContextMenuLabel = React.forwardRef<
  React.ElementRef<typeof CM.Label>,
  React.ComponentPropsWithoutRef<typeof CM.Label>
>(({ className, ...props }, ref) => (
  <CM.Label ref={ref} className={cn('px-2.5 py-1.5 font-mono text-xs text-[#a1a1aa]', className)} {...props} />
));
ContextMenuLabel.displayName = 'ContextMenuLabel';

export const ContextMenuSeparator = React.forwardRef<
  React.ElementRef<typeof CM.Separator>,
  React.ComponentPropsWithoutRef<typeof CM.Separator>
>(({ className, ...props }, ref) => (
  <CM.Separator ref={ref} className={cn('-mx-1 my-1 h-px bg-[#2a2a32]', className)} {...props} />
));
ContextMenuSeparator.displayName = 'ContextMenuSeparator';
