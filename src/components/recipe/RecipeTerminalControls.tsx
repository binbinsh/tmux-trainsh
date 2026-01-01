import { Chip, Tooltip, Kbd, Divider, Progress, ScrollShadow } from "@nextui-org/react";
import { Button } from "../ui";
import { motion, AnimatePresence } from "framer-motion";
import { useCallback, useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  interactiveRecipeApi,
  useInteractiveExecution,
} from "../../lib/tauri-api";
import type { InteractiveExecution, InteractiveStepState, StepStatus } from "../../lib/types";
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

function XIcon({ className }: { className?: string }) {
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
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
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

function ChevronDownIcon({ className }: { className?: string }) {
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
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function ChevronUpIcon({ className }: { className?: string }) {
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
      <path d="m18 15-6-6-6 6" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function ClockIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  );
}

function LoaderIcon({ className }: { className?: string }) {
  return (
    <svg
      className={`${className} animate-spin`}
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

function PauseIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="6" y="4" width="4" height="16" />
      <rect x="14" y="4" width="4" height="16" />
    </svg>
  );
}

// ============================================================
// Step Status Icon
// ============================================================

function StepStatusIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "success":
      return <CheckIcon className="text-success" />;
    case "failed":
      return <XIcon className="text-danger" />;
    case "running":
      return <LoaderIcon className="text-primary" />;
    case "pending":
    case "waiting":
      return <ClockIcon className="text-foreground/40" />;
    case "skipped":
      return <span className="text-foreground/40 text-xs">—</span>;
    case "retrying":
      return <LoaderIcon className="text-warning" />;
    case "cancelled":
      return <StopIcon className="text-foreground/40" />;
    default:
      return null;
  }
}

// ============================================================
// Step Item Component
// ============================================================

function StepItem({ step, isActive }: { step: InteractiveStepState; isActive: boolean }) {
  const displayName = step.name ?? step.step_id;

  return (
    <div
      className={`flex items-center gap-2 py-1 px-2 rounded-md transition-colors ${
        isActive ? "bg-primary/10" : "hover:bg-content2/50"
      }`}
    >
      <div className="flex-shrink-0">
        <StepStatusIcon status={step.status} />
      </div>
      <div className="flex-1 min-w-0">
        <p className={`text-xs truncate ${isActive ? "font-medium text-foreground" : "text-foreground/70"}`}>
          {displayName}
        </p>
      </div>
    </div>
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
  /** Callback when cancel is requested */
  onCancel?: () => void;
}

export function RecipeTerminalControls({
  terminalId,
  executionId,
  onInterrupt,
  onCancel,
}: RecipeTerminalControlsProps) {
  const { setInterventionLocked, getSession, recipeDetailsExpanded, toggleRecipeDetails } = useTerminal();
  const session = getSession(terminalId);

  // Get execution state
  const { data: execution } = useInteractiveExecution(executionId ?? null);

  const [isInterrupting, setIsInterrupting] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [isPausing, setIsPausing] = useState(false);
  const [isResuming, setIsResuming] = useState(false);

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

  // Handle cancel
  const handleCancel = useCallback(async () => {
    if (!executionId) return;

    setIsCancelling(true);
    try {
      await interactiveRecipeApi.cancel(executionId);
      onCancel?.();
    } catch (e) {
      console.error("[RecipeTerminalControls] Cancel failed:", e);
    } finally {
      setIsCancelling(false);
    }
  }, [executionId, onCancel]);

  // Handle pause
  const handlePause = useCallback(async () => {
    if (!executionId) return;

    setIsPausing(true);
    try {
      await interactiveRecipeApi.pause(executionId);
    } catch (e) {
      console.error("[RecipeTerminalControls] Pause failed:", e);
    } finally {
      setIsPausing(false);
    }
  }, [executionId]);

  // Handle resume
  const handleResume = useCallback(async () => {
    if (!executionId) return;

    setIsResuming(true);
    try {
      await interactiveRecipeApi.resume(executionId);
    } catch (e) {
      console.error("[RecipeTerminalControls] Resume failed:", e);
    } finally {
      setIsResuming(false);
    }
  }, [executionId]);

  if (!execution) {
    return null;
  }

  const isLocked = session?.interventionLocked ?? execution.intervention_locked;
  const isRunning = execution.status === "running" || execution.status === "connecting" || execution.status === "pending";
  const isPaused = execution.status === "paused";
  const isWaitingForInput = execution.status === "waiting_for_input";
  const isActive = isRunning || isPaused || isWaitingForInput;
  const isCompleted = execution.status === "completed" || execution.status === "failed" || execution.status === "cancelled";

  // Progress calculations
  const stepsCompleted = execution.steps.filter((s) => s.status === "success").length;
  const stepsFailed = execution.steps.filter((s) => s.status === "failed").length;
  const progress = execution.steps.length > 0
    ? ((stepsCompleted + stepsFailed) / execution.steps.length) * 100
    : 0;
  const currentStepIndex = execution.steps.findIndex((s) => s.status === "running");

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        className="flex flex-col bg-content1/80 backdrop-blur-md border-b border-divider"
      >
        {/* Top bar - always visible */}
        <div className="flex items-center gap-2 px-3 py-2">
          {/* Recipe Info */}
          <div className="flex items-center gap-2">
            <TerminalIcon className="text-primary" />
            <span className="text-sm font-medium">{execution.recipe_name}</span>
          </div>

          <Divider orientation="vertical" className="h-4" />

          {/* Status */}
          <StatusBadge status={execution.status} />

          {/* Progress indicator (compact) */}
          {!isCompleted && (
            <>
              <Divider orientation="vertical" className="h-4" />
              <span className="text-xs text-foreground/60">
                {stepsCompleted}/{execution.steps.length}
              </span>
            </>
          )}

          {/* Current Step */}
          {execution.current_step && (
            <>
              <Divider orientation="vertical" className="h-4" />
              <span className="text-xs text-foreground/60 truncate max-w-32">
                {execution.current_step}
              </span>
            </>
          )}

          <div className="flex-1" />

          {/* Controls */}
          <div className="flex items-center gap-2">
            {/* Intervention Indicator */}
            <InterventionIndicator locked={isLocked} />

            {/* Pause/Resume Button */}
            {isRunning && (
              <Tooltip content="Pause execution">
                <Button
                  size="sm"
                  color="warning"
                  variant="flat"
                  isIconOnly
                  isLoading={isPausing}
                  onPress={handlePause}
                >
                  <PauseIcon />
                </Button>
              </Tooltip>
            )}
            {isPaused && (
              <Tooltip content="Resume execution">
                <Button
                  size="sm"
                  color="success"
                  variant="flat"
                  isIconOnly
                  isLoading={isResuming}
                  onPress={handleResume}
                >
                  <PlayIcon />
                </Button>
              </Tooltip>
            )}

            {/* Interrupt Button */}
            {isRunning && (
              <Tooltip content="Send interrupt signal (Ctrl+C)">
                <Button
                  size="sm"
                  color="warning"
                  variant="flat"
                  isIconOnly
                  isLoading={isInterrupting}
                  onPress={handleInterrupt}
                >
                  <StopIcon />
                </Button>
              </Tooltip>
            )}

            {/* Cancel Button */}
            {isActive && (
              <Tooltip content="Cancel recipe execution">
                <Button
                  size="sm"
                  color="danger"
                  variant="flat"
                  isLoading={isCancelling}
                  onPress={handleCancel}
                  startContent={!isCancelling && <XIcon />}
                >
                  Cancel
                </Button>
              </Tooltip>
            )}

            {/* Toggle expand button */}
            <Tooltip content={recipeDetailsExpanded ? "Show less (⌘])" : "Show more (⌘])"}>
              <Button
                size="sm"
                variant="light"
                isIconOnly
                onPress={toggleRecipeDetails}
              >
                {recipeDetailsExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
              </Button>
            </Tooltip>
          </div>
        </div>

        {/* Expanded details panel */}
        <AnimatePresence>
          {recipeDetailsExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t border-divider"
            >
              <div className="flex gap-4 px-3 py-2">
                {/* Progress bar */}
                {!isCompleted && (
                  <div className="w-48 flex flex-col justify-center">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-foreground/50">Progress</span>
                      <span className="text-[10px] font-medium">
                        {stepsCompleted}/{execution.steps.length}
                      </span>
                    </div>
                    <Progress
                      size="sm"
                      value={progress}
                      color={stepsFailed > 0 ? "danger" : "primary"}
                      className="max-w-full"
                    />
                    {stepsFailed > 0 && (
                      <p className="text-[10px] text-danger mt-0.5">{stepsFailed} failed</p>
                    )}
                  </div>
                )}

                {/* Steps list */}
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] font-medium text-foreground/50 mb-1">Steps</p>
                  <ScrollShadow className="max-h-32" hideScrollBar>
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1">
                      {execution.steps.map((step, index) => (
                        <StepItem
                          key={step.step_id}
                          step={step}
                          isActive={index === currentStepIndex}
                        />
                      ))}
                    </div>
                  </ScrollShadow>
                </div>

                {/* Keyboard hint */}
                <div className="flex flex-col justify-center text-[10px] text-foreground/40">
                  {isLocked ? (
                    <span>Waiting for script...</span>
                  ) : (
                    <>
                      <span>Type freely or</span>
                      <Kbd keys={["ctrl"]} className="text-[10px]">C</Kbd>
                      <span>to interrupt</span>
                    </>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
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

