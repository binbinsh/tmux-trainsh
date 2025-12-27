import { Chip, Tooltip, Kbd, Divider } from "@nextui-org/react";
import { Button } from "../ui";
import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  interactiveRecipeApi,
  useInteractiveExecution,
} from "../../lib/tauri-api";
import type { InteractiveExecution } from "../../lib/types";
import { useTerminal } from "../../contexts/TerminalContext";

// ============================================================
// Icons
// ============================================================

function LockIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function UnlockIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 9.9-1" />
    </svg>
  );
}

function StopIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect width="16" height="16" x="4" y="4" rx="2" />
    </svg>
  );
}

function PlayIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polygon points="6 3 20 12 6 21 6 3" />
    </svg>
  );
}

function TerminalIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" x2="20" y1="19" y2="19" />
    </svg>
  );
}

// ============================================================
// Status Badge
// ============================================================

function StatusBadge({ status }: { status: InteractiveExecution["status"] }) {
  const statusConfig: Record<
    InteractiveExecution["status"],
    { color: "default" | "primary" | "secondary" | "success" | "warning" | "danger"; label: string }
  > = {
    pending: { color: "default", label: "Pending" },
    connecting: { color: "primary", label: "Connecting" },
    running: { color: "success", label: "Running" },
    paused: { color: "warning", label: "Paused" },
    waiting_for_input: { color: "secondary", label: "Waiting for Input" },
    completed: { color: "success", label: "Completed" },
    failed: { color: "danger", label: "Failed" },
    cancelled: { color: "default", label: "Cancelled" },
  };

  const config = statusConfig[status] || { color: "default", label: status };

  return (
    <Chip size="sm" color={config.color} variant="flat">
      {config.label}
    </Chip>
  );
}

// ============================================================
// Intervention Lock Indicator
// ============================================================

function InterventionIndicator({
  locked,
  onToggle,
}: {
  locked: boolean;
  onToggle?: () => void;
}) {
  return (
    <Tooltip
      content={
        locked
          ? "Script is sending commands. Wait for unlock to type."
          : "Terminal is unlocked. You can type freely."
      }
    >
      <Button
        size="sm"
        variant={locked ? "flat" : "light"}
        color={locked ? "warning" : "success"}
        isIconOnly
        onPress={onToggle}
        aria-label={locked ? "Input locked" : "Input unlocked"}
      >
        {locked ? (
          <LockIcon className="text-warning" />
        ) : (
          <UnlockIcon className="text-success" />
        )}
      </Button>
    </Tooltip>
  );
}

// ============================================================
// Recipe Terminal Controls Component
// ============================================================

interface RecipeTerminalControlsProps {
  /** Terminal session ID */
  terminalId: string;
  /** Recipe execution ID (if known) */
  executionId?: string | null;
  /** Callback when interrupt is requested */
  onInterrupt?: () => void;
}

export function RecipeTerminalControls({
  terminalId,
  executionId,
  onInterrupt,
}: RecipeTerminalControlsProps) {
  const { setInterventionLocked, getSession } = useTerminal();
  const session = getSession(terminalId);
  
  // Get execution state
  const { data: execution } = useInteractiveExecution(executionId ?? null);
  
  const [isInterrupting, setIsInterrupting] = useState(false);

  // Listen for intervention lock events
  useEffect(() => {
    if (!executionId) return;

    const setupListener = async () => {
      const unlisten = await listen<{ execution_id: string; locked: boolean }>(
        "recipe:intervention_lock_changed",
        (event) => {
          if (event.payload.execution_id === executionId) {
            setInterventionLocked(terminalId, event.payload.locked);
          }
        }
      );
      return unlisten;
    };

    const unlistenPromise = setupListener();
    return () => {
      unlistenPromise.then((unlisten) => unlisten());
    };
  }, [executionId, terminalId, setInterventionLocked]);

  // Handle interrupt
  const handleInterrupt = useCallback(async () => {
    if (!executionId) return;
    
    setIsInterrupting(true);
    try {
      await interactiveRecipeApi.interrupt(executionId);
      onInterrupt?.();
    } catch (e) {
      console.error("[RecipeTerminalControls] Interrupt failed:", e);
    } finally {
      setIsInterrupting(false);
    }
  }, [executionId, onInterrupt]);

  if (!execution) {
    return null;
  }

  const isLocked = session?.interventionLocked ?? execution.intervention_locked;
  const isRunning = execution.status === "running" || execution.status === "connecting";

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="flex items-center gap-2 px-3 py-2 bg-content1/80 backdrop-blur-md border-b border-divider"
      >
        {/* Recipe Info */}
        <div className="flex items-center gap-2">
          <TerminalIcon className="text-primary" />
          <span className="text-sm font-medium">{execution.recipe_name}</span>
        </div>

        <Divider orientation="vertical" className="h-4" />

        {/* Status */}
        <StatusBadge status={execution.status} />

        {/* Current Step */}
        {execution.current_step && (
          <>
            <Divider orientation="vertical" className="h-4" />
            <span className="text-xs text-foreground/60">
              Step: {execution.current_step}
            </span>
          </>
        )}

        <div className="flex-1" />

        {/* Controls */}
        <div className="flex items-center gap-2">
          {/* Intervention Indicator */}
          <InterventionIndicator locked={isLocked} />

          {/* Interrupt Button */}
          {isRunning && (
            <Tooltip content="Send interrupt signal (Ctrl+C)">
              <Button
                size="sm"
                color="danger"
                variant="flat"
                isLoading={isInterrupting}
                onPress={handleInterrupt}
                startContent={!isInterrupting && <StopIcon />}
              >
                Interrupt
              </Button>
            </Tooltip>
          )}

          {/* Keyboard hint */}
          <div className="hidden sm:flex items-center gap-1 text-xs text-foreground/40">
            {isLocked ? (
              <span>Waiting for script...</span>
            ) : (
              <>
                <span>Type freely or</span>
                <Kbd keys={["ctrl"]}>C</Kbd>
                <span>to interrupt</span>
              </>
            )}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}

// ============================================================
// Hook: Use Recipe Terminal
// ============================================================

/**
 * Hook to manage recipe terminal state and events
 */
export function useRecipeTerminal(terminalId: string) {
  const { getSession, setInterventionLocked, addRecipeTerminal } = useTerminal();
  const session = getSession(terminalId);
  
  const executionId = session?.recipeExecutionId;
  const { data: execution, isLoading } = useInteractiveExecution(executionId ?? null);

  // Send data to terminal
  const sendData = useCallback(
    async (data: string) => {
      if (!executionId) return;
      
      // Check if locked
      if (session?.interventionLocked) {
        console.warn("[useRecipeTerminal] Cannot send data while intervention is locked");
        return;
      }
      
      await interactiveRecipeApi.send(executionId, data);
    },
    [executionId, session?.interventionLocked]
  );

  // Send interrupt
  const sendInterrupt = useCallback(async () => {
    if (!executionId) return;
    await interactiveRecipeApi.interrupt(executionId);
  }, [executionId]);

  return {
    session,
    execution,
    isLoading,
    isLocked: session?.interventionLocked ?? false,
    isRecipeTerminal: !!executionId,
    sendData,
    sendInterrupt,
    setInterventionLocked: (locked: boolean) =>
      setInterventionLocked(terminalId, locked),
    addRecipeTerminal,
  };
}

export default RecipeTerminalControls;

