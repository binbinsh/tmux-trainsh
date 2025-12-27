import { Button as NextUIButton, type ButtonProps as NextUIButtonProps } from "@nextui-org/react";
import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef, type ElementType } from "react";

export interface DoppioButtonProps<T extends ElementType = "button"> extends Omit<NextUIButtonProps, "ref"> {
  /** Enable enhanced press animation */
  pressAnimation?: boolean;
  /** Enable glow effect on hover (primary/danger only) */
  glowOnHover?: boolean;
  /** Polymorphic `as` prop for rendering as different elements (e.g., Link) */
  as?: T;
  /** Additional props for the polymorphic element */
  to?: string;
  href?: string;
}

/**
 * Doppio Button - A refined button component with subtle animations
 * 
 * Features:
 * - Micro-interactions with spring physics
 * - Subtle scale and shadow transitions
 * - Glass-morphism styling for flat/light variants
 * - Glow effect for primary buttons
 */
export const DoppioButton = forwardRef<HTMLButtonElement, DoppioButtonProps<ElementType>>(
  ({ 
    className = "", 
    pressAnimation = true, 
    glowOnHover = true,
    variant = "solid",
    color = "default",
    size = "md",
    isIconOnly,
    as,
    children,
    ...props 
  }, ref) => {
    // Base motion variants
    const motionProps: HTMLMotionProps<"button"> = pressAnimation ? {
      whileHover: { scale: 1.02, y: -1 },
      whileTap: { scale: 0.97, y: 0 },
      transition: { 
        type: "spring", 
        stiffness: 400, 
        damping: 17,
        mass: 0.8
      }
    } : {};

    // Build refined class names based on variant and color
    const getVariantClasses = () => {
      const base = "font-medium tracking-wide transition-all duration-200";
      
      // Icon-only buttons get minimal styling
      if (isIconOnly) {
        const iconSizes = {
          sm: "min-w-7 w-7 h-7",
          md: "min-w-9 w-9 h-9",
          lg: "min-w-11 w-11 h-11",
        };
        return `${base} ${iconSizes[size as keyof typeof iconSizes] || iconSizes.md} rounded-lg`;
      }

      // Size-specific padding and text
      const sizes = {
        sm: "px-3.5 h-8 text-xs gap-1.5",
        md: "px-5 h-10 text-sm gap-2",
        lg: "px-6 h-12 text-base gap-2.5",
      };

      // Variant + color specific styling
      const variantStyles: Record<string, string> = {
        // Solid variants - bold with subtle gradient overlay
        "solid-primary": `
          bg-gradient-to-b from-primary-400 to-primary-600 
          text-white font-semibold
          shadow-md shadow-primary/25
          hover:shadow-lg hover:shadow-primary/35
          active:shadow-sm
          border border-primary-500/50
        `,
        "solid-danger": `
          bg-gradient-to-b from-danger-400 to-danger-600
          text-white font-semibold
          shadow-md shadow-danger/25
          hover:shadow-lg hover:shadow-danger/35
          active:shadow-sm
          border border-danger-500/50
        `,
        "solid-success": `
          bg-gradient-to-b from-success-400 to-success-600
          text-white font-semibold
          shadow-md shadow-success/25
          hover:shadow-lg hover:shadow-success/35
          active:shadow-sm
          border border-success-500/50
        `,
        "solid-warning": `
          bg-gradient-to-b from-warning-400 to-warning-600
          text-white font-semibold
          shadow-md shadow-warning/25
          hover:shadow-lg hover:shadow-warning/35
          active:shadow-sm
          border border-warning-500/50
        `,
        "solid-secondary": `
          bg-gradient-to-b from-secondary-400 to-secondary-600
          text-white font-semibold
          shadow-md shadow-secondary/25
          hover:shadow-lg hover:shadow-secondary/35
          active:shadow-sm
          border border-secondary-500/50
        `,
        "solid-default": `
          bg-gradient-to-b from-default-100 to-default-200
          text-foreground font-medium
          shadow-sm
          hover:shadow-md hover:from-default-200 hover:to-default-300
          active:shadow-none
          border border-default-300/50
        `,
        
        // Flat variants - glass-morphism style
        "flat-primary": `
          bg-primary/10 hover:bg-primary/20
          text-primary font-medium
          backdrop-blur-sm
        `,
        "flat-danger": `
          bg-danger/10 hover:bg-danger/20
          text-danger font-medium
          backdrop-blur-sm
        `,
        "flat-success": `
          bg-success/10 hover:bg-success/20
          text-success font-medium
          backdrop-blur-sm
        `,
        "flat-warning": `
          bg-warning/10 hover:bg-warning/20
          text-warning-600 font-medium
          backdrop-blur-sm
        `,
        "flat-secondary": `
          bg-secondary/10 hover:bg-secondary/20
          text-secondary font-medium
          backdrop-blur-sm
        `,
        "flat-default": `
          bg-default-100/80 hover:bg-default-200
          text-foreground/80 hover:text-foreground
          font-medium backdrop-blur-sm
        `,
        
        // Light variants - minimal ghost style
        "light-primary": `
          bg-transparent hover:bg-primary/10
          text-primary/80 hover:text-primary
          font-medium
        `,
        "light-danger": `
          bg-transparent hover:bg-danger/10
          text-danger/80 hover:text-danger
          font-medium
        `,
        "light-default": `
          bg-transparent hover:bg-default-100
          text-foreground/60 hover:text-foreground
          font-medium
        `,
        
        // Bordered variants - refined outline
        "bordered-primary": `
          bg-transparent hover:bg-primary/5
          text-primary font-medium
          border-2 border-primary/50 hover:border-primary
        `,
        "bordered-danger": `
          bg-transparent hover:bg-danger/5
          text-danger font-medium
          border-2 border-danger/50 hover:border-danger
        `,
        "bordered-default": `
          bg-transparent hover:bg-default-100
          text-foreground font-medium
          border-2 border-default-300 hover:border-default-400
        `,

        // Ghost variants
        "ghost-primary": `
          bg-transparent hover:bg-primary
          text-primary hover:text-white
          font-medium
          border border-primary/50
        `,
        "ghost-default": `
          bg-transparent hover:bg-default-200
          text-foreground/70 hover:text-foreground
          font-medium
          border border-default-200
        `,
      };

      const key = `${variant}-${color}`;
      const variantClass = variantStyles[key] || variantStyles[`${variant}-default`] || variantStyles["solid-default"];
      const sizeClass = sizes[size as keyof typeof sizes] || sizes.md;

      return `${base} ${sizeClass} ${variantClass} rounded-xl`;
    };

    // Glow effect for primary/danger solid buttons
    const shouldGlow = glowOnHover && variant === "solid" && (color === "primary" || color === "danger");
    const glowClass = shouldGlow ? `
      relative overflow-visible
      before:absolute before:inset-0 before:rounded-xl
      before:bg-gradient-to-b before:from-white/20 before:to-transparent
      before:opacity-0 hover:before:opacity-100 before:transition-opacity
    ` : "";

    const combinedClassName = `
      ${getVariantClasses()}
      ${glowClass}
      ${className}
    `.trim().replace(/\s+/g, " ");

    // When using a custom `as` element (like Link), don't use motion wrapper
    // as it conflicts with router link behavior
    const shouldAnimate = pressAnimation && !as;

    return (
      <NextUIButton
        ref={ref}
        as={as ?? (shouldAnimate ? motion.button : undefined)}
        variant={variant}
        color={color}
        size={size}
        isIconOnly={isIconOnly}
        className={combinedClassName}
        {...(shouldAnimate ? motionProps : {})}
        {...props}
      >
        {children}
      </NextUIButton>
    );
  }
);

DoppioButton.displayName = "DoppioButton";

// Re-export as Button for easy replacement
export { DoppioButton as Button };

