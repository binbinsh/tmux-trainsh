import { Button as NextUIButton, type ButtonProps as NextUIButtonProps } from "@nextui-org/react";
import { motion, type HTMLMotionProps } from "framer-motion";
import { forwardRef, type ElementType } from "react";

type ButtonColor = "default" | "primary" | "secondary" | "success" | "warning" | "danger";
type ButtonVariant = "solid" | "bordered" | "light" | "flat" | "faded" | "shadow" | "ghost";
type ButtonSize = "sm" | "md" | "lg";

export interface DoppioButtonProps<T extends ElementType = "button"> extends Omit<NextUIButtonProps, "ref" | "color" | "variant" | "size"> {
  /** Enable enhanced press animation */
  pressAnimation?: boolean;
  /** Polymorphic `as` prop for rendering as different elements (e.g., Link) */
  as?: T;
  /** Additional props for the polymorphic element */
  to?: string;
  href?: string;
  /** Button color */
  color?: ButtonColor;
  /** Button variant */
  variant?: ButtonVariant;
  /** Button size */
  size?: ButtonSize;
}

/**
 * Doppio Button - A clean, consistent button component
 *
 * Features:
 * - Subtle micro-interactions with spring physics
 * - Clean, minimal styling that works well in both light and dark modes
 * - Consistent sizing and spacing
 */
export const DoppioButton = forwardRef<HTMLButtonElement, DoppioButtonProps<ElementType>>(
  ({
    className = "",
    pressAnimation = true,
    variant = "solid",
    color = "default",
    size = "md",
    isIconOnly,
    as,
    children,
    ...props
  }, ref) => {
    // Base motion variants - subtle spring animation
    const motionProps: HTMLMotionProps<"button"> = pressAnimation ? {
      whileHover: { scale: 1.01 },
      whileTap: { scale: 0.98 },
      transition: {
        type: "spring",
        stiffness: 400,
        damping: 20,
        mass: 0.8
      }
    } : {};

    // Build clean class names based on variant and color
    const getVariantClasses = () => {
      const base = "font-medium transition-all duration-150";

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
        sm: "px-3 h-8 text-xs gap-1.5",
        md: "px-4 h-9 text-sm gap-2",
        lg: "px-5 h-11 text-base gap-2",
      };

      // Clean variant + color styling - no gradients, simpler shadows
      const variantStyles: Record<string, string> = {
        // Solid variants - clean, flat colors
        "solid-primary": `
          bg-primary text-primary-foreground font-medium
          shadow-sm hover:shadow-md hover:bg-primary-600
          active:shadow-none
        `,
        "solid-danger": `
          bg-danger text-danger-foreground font-medium
          shadow-sm hover:shadow-md hover:bg-danger-600
          active:shadow-none
        `,
        "solid-success": `
          bg-success text-success-foreground font-medium
          shadow-sm hover:shadow-md hover:bg-success-600
          active:shadow-none
        `,
        "solid-warning": `
          bg-warning text-warning-foreground font-medium
          shadow-sm hover:shadow-md hover:bg-warning-600
          active:shadow-none
        `,
        "solid-secondary": `
          bg-secondary text-secondary-foreground font-medium
          shadow-sm hover:shadow-md hover:bg-secondary-600
          active:shadow-none
        `,
        "solid-default": `
          bg-default-100 text-foreground font-medium
          hover:bg-default-200
        `,

        // Flat variants - clean glass style
        "flat-primary": `
          bg-primary/10 hover:bg-primary/20
          text-primary font-medium
        `,
        "flat-danger": `
          bg-danger/10 hover:bg-danger/20
          text-danger font-medium
        `,
        "flat-success": `
          bg-success/10 hover:bg-success/20
          text-success font-medium
        `,
        "flat-warning": `
          bg-warning/10 hover:bg-warning/20
          text-warning-600 font-medium
        `,
        "flat-secondary": `
          bg-secondary/10 hover:bg-secondary/20
          text-secondary font-medium
        `,
        "flat-default": `
          bg-default-100 hover:bg-default-200
          text-foreground/80 hover:text-foreground
          font-medium
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

        // Bordered variants - clean outline
        "bordered-primary": `
          bg-transparent hover:bg-primary/5
          text-primary font-medium
          border border-primary/50 hover:border-primary
        `,
        "bordered-danger": `
          bg-transparent hover:bg-danger/5
          text-danger font-medium
          border border-danger/50 hover:border-danger
        `,
        "bordered-default": `
          bg-transparent hover:bg-default-100
          text-foreground font-medium
          border border-default-300 hover:border-default-400
        `,

        // Ghost variants
        "ghost-primary": `
          bg-transparent hover:bg-primary
          text-primary hover:text-primary-foreground
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

      return `${base} ${sizeClass} ${variantClass} rounded-lg`;
    };

    const combinedClassName = `
      ${getVariantClasses()}
      ${className}
    `.trim().replace(/\s+/g, " ");

    // When using a custom `as` element (like Link), don't use motion wrapper
    const shouldAnimate = pressAnimation && !as;

    // Ensure types match NextUIButton expectations
    const buttonColor = color as "default" | "primary" | "secondary" | "success" | "warning" | "danger";
    const buttonVariant = variant as "solid" | "bordered" | "light" | "flat" | "faded" | "shadow" | "ghost";
    const buttonSize = size as "sm" | "md" | "lg";

    return (
      <NextUIButton
        ref={ref}
        as={as ?? (shouldAnimate ? motion.button : undefined)}
        variant={buttonVariant}
        color={buttonColor}
        size={buttonSize}
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
