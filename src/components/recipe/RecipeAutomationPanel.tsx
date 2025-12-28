import {
  Chip,
  Progress,
  ScrollShadow,
  Tooltip,
} from "@nextui-org/react";
import { Button } from "../ui";
import { motion } from "framer-motion";
import { useCallback, useState } from "react";
import {
  useInteractiveExecution,
  interactiveRecipeApi,
} from "../../lib/tauri-api";
import type {
  InteractiveExecution,
  InteractiveStepState,
  StepStatus,
} from "../../lib/types";
import { useTerminal } from "../../contexts/TerminalContext";

// ============================================================
// Icons
// ============================================================

function StopIcon({ className }: { className?: string }) {
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
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  );
}

function TerminalIcon({ className }: { className?: string }) {
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
      <polyline points="4 17 10 11 4 5" />
      <line x1="12" x2="20" y1="19" y2="19" />
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

function XIcon({ className }: { className?: string }) {
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
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
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

function LockIcon({ className }: { className?: string }) {
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
      <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
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

function PlayIcon({ className }: { className?: string }) {
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
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

// ============================================================
// Status Badge
// ============================================================

function ExecutionStatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    { color: "default" | "primary" | "secondary" | "success" | "warning" | "danger"; icon: React.ReactNode }
  > = {
    pending: { color: "default", icon: <ClockIcon /> },
    running: { color: "primary", icon: <LoaderIcon /> },
    paused: { color: "warning", icon: <ClockIcon /> },
    completed: { color: "success", icon: <CheckIcon /> },
    failed: { color: "danger", icon: <XIcon /> },
    cancelled: { color: "default", icon: <StopIcon /> },
    connecting: { color: "primary", icon: <LoaderIcon /> },
    waiting_for_input: { color: "secondary", icon: <ClockIcon /> },
  };

  const cfg = config[status] || { color: "default", icon: null };

  return (
    <Chip size="sm" color={cfg.color} variant="flat" startContent={cfg.icon}>
      {status.replace(/_/g, " ")}
    </Chip>
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
      className={`flex items-center gap-2 py-1.5 px-2 rounded-md transition-colors ${
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

// ============================================================
// Current Recipe Detail View
// ============================================================

interface CurrentRecipeViewProps {
  execution: InteractiveExecution;
}

function CurrentRecipeView({ execution }: CurrentRecipeViewProps) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const { setInterventionLocked } = useTerminal();

  const stepsCompleted = execution.steps.filter((s) => s.status === "success").length;
  const stepsFailed = execution.steps.filter((s) => s.status === "failed").length;
  const progress =
    execution.steps.length > 0
      ? ((stepsCompleted + stepsFailed) / execution.steps.length) * 100
      : 0;

  const handleInterrupt = useCallback(async () => {
    setActionLoading("interrupt");
    try {
      await interactiveRecipeApi.interrupt(execution.id);
    } finally {
      setActionLoading(null);
    }
  }, [execution.id]);

  const handlePause = useCallback(async () => {
    setActionLoading("pause");
    try {
      await interactiveRecipeApi.pause(execution.id);
    } finally {
      setActionLoading(null);
    }
  }, [execution.id]);

  const handleResume = useCallback(async () => {
    setActionLoading("resume");
    try {
      await interactiveRecipeApi.resume(execution.id);
    } finally {
      setActionLoading(null);
    }
  }, [execution.id]);

  const handleCancel = useCallback(async () => {
    setActionLoading("cancel");
    try {
      await interactiveRecipeApi.cancel(execution.id);
    } finally {
      setActionLoading(null);
    }
  }, [execution.id]);

  const handleToggleLock = useCallback(async () => {
    setActionLoading("lock");
    try {
      const newLocked = !execution.intervention_locked;
      await interactiveRecipeApi.setLock(execution.id, newLocked);
      // Also update local terminal session state
      setInterventionLocked(execution.terminal_id, newLocked);
    } finally {
      setActionLoading(null);
    }
  }, [execution.id, execution.intervention_locked, execution.terminal_id, setInterventionLocked]);

  const isActive =
    execution.status === "running" ||
    execution.status === "connecting";
  
  const isPaused = execution.status === "paused";

  const isCompleted = execution.status === "completed" || execution.status === "failed" || execution.status === "cancelled";

  // Find current step index
  const currentStepIndex = execution.steps.findIndex((s) => s.status === "running");
  const currentProgress =
    execution.current_step && execution.step_progress
      ? execution.step_progress[execution.current_step]
      : undefined;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-divider">
        <div className="flex items-start justify-between gap-2 mb-2">
          <h3 className="text-sm font-semibold truncate flex-1">{execution.recipe_name}</h3>
        </div>
        
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <ExecutionStatusBadge status={execution.status} />
          {execution.intervention_locked && (
            <Chip size="sm" variant="flat" color="warning" startContent={<LockIcon />}>
              Locked
            </Chip>
          )}
          {currentProgress && (
            <Chip size="sm" variant="flat" color="primary" className="max-w-full truncate">
              {currentProgress}
            </Chip>
          )}
        </div>

        {/* Control Buttons */}
        {!isCompleted && (
          <div className="flex items-center gap-1">
            {isActive && (
              <Tooltip content="Pause">
                <Button
                  size="sm"
                  isIconOnly
                  variant="flat"
                  color="warning"
                  isLoading={actionLoading === "pause"}
                  onPress={handlePause}
                >
                  <PauseIcon />
                </Button>
              </Tooltip>
            )}
            {isPaused && (
              <Tooltip content="Resume">
                <Button
                  size="sm"
                  isIconOnly
                  variant="flat"
                  color="success"
                  isLoading={actionLoading === "resume"}
                  onPress={handleResume}
                >
                  <PlayIcon />
                </Button>
              </Tooltip>
            )}
            {(isActive || isPaused) && (
              <>
                <Tooltip content="Send Ctrl+C">
                  <Button
                    size="sm"
                    isIconOnly
                    variant="flat"
                    color="danger"
                    isLoading={actionLoading === "interrupt"}
                    onPress={handleInterrupt}
                  >
                    <StopIcon />
                  </Button>
                </Tooltip>
                <div className="flex-1" />
                <Tooltip content="Cancel execution">
                  <Button
                    size="sm"
                    variant="flat"
                    color="danger"
                    isLoading={actionLoading === "cancel"}
                    onPress={handleCancel}
                  >
                    Cancel
                  </Button>
                </Tooltip>
              </>
            )}
          </div>
        )}
      </div>

      {/* Progress */}
      {!isCompleted && (
        <div className="px-3 py-2 border-b border-divider">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs text-foreground/60">Progress</span>
            <span className="text-xs font-medium">
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
            <p className="text-xs text-danger mt-1">{stepsFailed} step(s) failed</p>
          )}
        </div>
      )}

      {/* Input Status / Lock Control */}
      {isActive && (
        <div className="px-3 py-2 border-b border-divider">
          {execution.status === "waiting_for_input" ? (
            <>
              <div className="flex items-center gap-2 p-2 bg-secondary/10 rounded-lg">
                <div className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
                <span className="text-xs font-medium text-secondary">Waiting for your input</span>
              </div>
              <p className="text-[10px] text-foreground/50 mt-1 text-center">
                Command may need password or confirmation - type in the terminal
              </p>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant={execution.intervention_locked ? "flat" : "bordered"}
                color={execution.intervention_locked ? "warning" : "default"}
                startContent={execution.intervention_locked ? <LockIcon /> : <TerminalIcon />}
                isLoading={actionLoading === "lock"}
                onPress={handleToggleLock}
                className="w-full"
              >
                {execution.intervention_locked ? "Unlock Intervention" : "Lock Intervention"}
              </Button>
              <p className="text-[10px] text-foreground/50 mt-1 text-center">
                {execution.intervention_locked 
                  ? "Script is in control - your input is blocked" 
                  : "You can type in the terminal"}
              </p>
            </>
          )}
        </div>
      )}

      {/* Steps List */}
      <ScrollShadow className="flex-1 overflow-y-auto">
        <div className="py-2">
          <p className="text-xs font-medium text-foreground/60 px-3 mb-1">Steps</p>
          <div className="px-1">
            {execution.steps.map((step, index) => (
              <StepItem
                key={step.step_id}
                step={step}
                isActive={index === currentStepIndex}
              />
            ))}
          </div>
        </div>
      </ScrollShadow>

      {/* Footer */}
      <div className="p-2 border-t border-divider text-[10px] text-foreground/40">
        Started {new Date(execution.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })}
        {execution.completed_at && (
          <> • Ended {new Date(execution.completed_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}</>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Empty State Component
// ============================================================

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-4">
      <div className="w-12 h-12 rounded-full bg-content2/50 flex items-center justify-center mb-3">
        <TerminalIcon className="w-5 h-5 text-foreground/30" />
      </div>
      <p className="text-sm font-medium text-foreground/50 mb-1">No Recipe</p>
      <p className="text-xs text-foreground/40">
        This terminal is not running a recipe automation
      </p>
    </div>
  );
}

// ============================================================
// Main Panel Component (Always visible when rendered)
// ============================================================

export function RecipeAutomationPanel() {
  const { sessions, activeId, hasActiveRecipe } = useTerminal();
  
  // Get the active terminal session
  const activeSession = sessions.find((s) => s.id === activeId);
  
  // Get the recipe execution for the active terminal (if any)
  const executionId = activeSession?.recipeExecutionId ?? null;
  const { data: execution, isLoading } = useInteractiveExecution(executionId);

  return (
    <motion.div
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: 280, opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className="h-full flex flex-col border-l border-divider bg-content1/50 overflow-hidden"
    >
      {/* Content */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {!hasActiveRecipe ? (
          <EmptyState />
        ) : isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <LoaderIcon className="w-6 h-6 text-primary" />
          </div>
        ) : execution ? (
          <CurrentRecipeView execution={execution} />
        ) : (
          <EmptyState />
        )}
      </div>
    </motion.div>
  );
}

export default RecipeAutomationPanel;
