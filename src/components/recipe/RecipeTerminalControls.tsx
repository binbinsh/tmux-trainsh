import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { cn } from "@/lib/utils";
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
      className={cn(
        "flex items-center gap-2 py-1 px-2 rounded-md transition-colors",
        isActive ? "bg-primary/10" : "hover:bg-muted/50"
      )}
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
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          onClick={onToggle}
          disabled={!onToggle}
          aria-label={locked ? "Input locked" : "Input unlocked"}
          className={locked ? "text-warning hover:text-warning" : "text-success hover:text-success"}
        >
          {locked ? <LockIcon /> : <UnlockIcon />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>
        {locked
          ? "Script is sending commands. Wait for unlock to type."
          : "Terminal is unlocked. You can type freely."}
      </TooltipContent>
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
  const { setInterventionLocked, getSession, skillDetailsExpanded, toggleSkillDetails } = useTerminal();
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
        className="flex flex-col bg-background/80 backdrop-blur-md border-b border-border"
      >
        {/* Top bar - always visible */}
        <div className="flex items-center gap-2 px-3 py-2">
          {/* Recipe Info */}
          <div className="flex items-center gap-2">
            <TerminalIcon className="text-primary" />
            <span className="text-sm font-medium">{execution.recipe_name}</span>
          </div>

          <Separator orientation="vertical" className="h-4" />

          {/* Status */}
          <StatusBadge status={execution.status} />

          {/* Progress indicator (compact) */}
          {!isCompleted && (
            <>
              <Separator orientation="vertical" className="h-4" />
              <span className="text-xs text-muted-foreground">
                {stepsCompleted}/{execution.steps.length}
              </span>
            </>
          )}

          {/* Current Step */}
          {execution.current_step && (
            <>
              <Separator orientation="vertical" className="h-4" />
              <span className="text-xs text-muted-foreground truncate max-w-32">
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
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={handlePause}
                    disabled={isPausing || isResuming || isInterrupting || isCancelling}
                    className="text-warning hover:text-warning"
                    aria-label="Pause execution"
                  >
                    {isPausing ? <LoaderIcon className="w-4 h-4" /> : <PauseIcon />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Pause execution</TooltipContent>
              </Tooltip>
            )}
            {isPaused && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={handleResume}
                    disabled={isPausing || isResuming || isInterrupting || isCancelling}
                    className="text-success hover:text-success"
                    aria-label="Resume execution"
                  >
                    {isResuming ? <LoaderIcon className="w-4 h-4" /> : <PlayIcon />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Resume execution</TooltipContent>
              </Tooltip>
            )}

            {/* Interrupt Button */}
            {isRunning && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={handleInterrupt}
                    disabled={isPausing || isResuming || isInterrupting || isCancelling}
                    className="text-warning hover:text-warning"
                    aria-label="Send interrupt signal (Ctrl+C)"
                  >
                    {isInterrupting ? <LoaderIcon className="w-4 h-4" /> : <StopIcon />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Send interrupt signal (Ctrl+C)</TooltipContent>
              </Tooltip>
            )}

            {/* Cancel Button */}
            {isActive && (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={handleCancel}
                    disabled={isPausing || isResuming || isInterrupting || isCancelling}
                    aria-label="Cancel recipe execution"
                  >
                    {isCancelling ? <LoaderIcon className="w-4 h-4" /> : <XIcon className="w-4 h-4" />}
                    Cancel
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Cancel recipe execution</TooltipContent>
              </Tooltip>
            )}

            {/* Toggle expand button */}
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={toggleSkillDetails}
                  aria-label={skillDetailsExpanded ? "Show less (⌘])" : "Show more (⌘])"}
                >
                  {skillDetailsExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                {skillDetailsExpanded ? "Show less (⌘])" : "Show more (⌘])"}
              </TooltipContent>
            </Tooltip>
          </div>
        </div>

        {/* Expanded details panel */}
        <AnimatePresence>
          {skillDetailsExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden border-t border-border"
            >
              <div className="flex gap-4 px-3 py-2">
                {/* Progress bar */}
                {!isCompleted && (
                  <div className="w-48 flex flex-col justify-center">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-muted-foreground">Progress</span>
                      <span className="text-[10px] font-medium">
                        {stepsCompleted}/{execution.steps.length}
                      </span>
                    </div>
                    <Progress
                      value={progress}
                      className="max-w-full"
                      trackClassName={stepsFailed > 0 ? "bg-danger/20" : undefined}
                      indicatorClassName={stepsFailed > 0 ? "bg-danger" : undefined}
                    />
                    {stepsFailed > 0 && (
                      <p className="text-[10px] text-danger mt-0.5">{stepsFailed} failed</p>
                    )}
                  </div>
                )}

                {/* Steps list */}
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] font-medium text-muted-foreground mb-1">Steps</p>
                  <ScrollArea className="max-h-32">
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1">
                      {execution.steps.map((step, index) => (
                        <StepItem
                          key={step.step_id}
                          step={step}
                          isActive={index === currentStepIndex}
                        />
                      ))}
                    </div>
                  </ScrollArea>
                </div>

                {/* Keyboard hint */}
                <div className="flex flex-col justify-center text-[10px] text-muted-foreground">
                  {isLocked ? (
                    <span>Waiting for script...</span>
                  ) : (
                    <>
                      <span>Type freely or</span>
                      <span className="inline-flex items-center gap-1">
                        <kbd className="inline-flex h-5 items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium">Ctrl</kbd>
                        <kbd className="inline-flex h-5 items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-[10px] font-medium">C</kbd>
                      </span>
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
 * Hook to manage skill terminal state and events
 */
export function useRecipeTerminal(terminalId: string) {
  const { getSession, setInterventionLocked, addSkillTerminal } = useTerminal();
  const session = getSession(terminalId);

  const executionId = session?.skillExecutionId;
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
    addSkillTerminal,
  };
}

export default RecipeTerminalControls;
