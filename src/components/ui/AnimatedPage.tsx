import { motion, type Variants } from "framer-motion";
import { type ReactNode } from "react";

/**
 * Page transition variants
 * Subtle fade + slight vertical slide for smooth page transitions
 */
const pageVariants: Variants = {
  initial: {
    opacity: 0,
    y: 8,
  },
  animate: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.2,
      ease: [0.25, 0.1, 0.25, 1], // Custom ease curve for smooth feel
    },
  },
  exit: {
    opacity: 0,
    y: -4,
    transition: {
      duration: 0.15,
      ease: [0.25, 0.1, 0.25, 1],
    },
  },
};

interface AnimatedPageProps {
  children: ReactNode;
  /** Optional custom className for the wrapper */
  className?: string;
  /** Disable animation (useful for terminal page which has its own animation handling) */
  disabled?: boolean;
}

/**
 * AnimatedPage - Wrapper component for page transitions
 *
 * Provides smooth fade + slide animations when navigating between pages.
 * Uses framer-motion with optimized spring physics for natural feel.
 */
export function AnimatedPage({ children, className = "", disabled = false }: AnimatedPageProps) {
  if (disabled) {
    return <div className={`h-full ${className}`}>{children}</div>;
  }

  return (
    <motion.div
      variants={pageVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      className={`h-full ${className}`}
    >
      {children}
    </motion.div>
  );
}

/**
 * Stagger container for animating lists of items
 */
const staggerContainerVariants: Variants = {
  initial: {},
  animate: {
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.1,
    },
  },
};

const staggerItemVariants: Variants = {
  initial: {
    opacity: 0,
    y: 10,
  },
  animate: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.2,
      ease: [0.25, 0.1, 0.25, 1],
    },
  },
};

interface StaggerContainerProps {
  children: ReactNode;
  className?: string;
}

/**
 * StaggerContainer - Container for staggered list animations
 */
export function StaggerContainer({ children, className = "" }: StaggerContainerProps) {
  return (
    <motion.div
      variants={staggerContainerVariants}
      initial="initial"
      animate="animate"
      className={className}
    >
      {children}
    </motion.div>
  );
}

interface StaggerItemProps {
  children: ReactNode;
  className?: string;
}

/**
 * StaggerItem - Individual item in a staggered list
 */
export function StaggerItem({ children, className = "" }: StaggerItemProps) {
  return (
    <motion.div variants={staggerItemVariants} className={className}>
      {children}
    </motion.div>
  );
}
