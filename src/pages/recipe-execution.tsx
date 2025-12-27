import {
  Card,
  CardBody,
  Chip,
  Divider,
  Progress,
  Spinner,
  Tooltip,
} from "@nextui-org/react";
import { Button } from "../components/ui";
import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import {
  listenRecipeEvents,
  useCancelExecution,
  usePauseExecution,
  useRecipeExecution,
  useResumeExecution,
  useRetryStep,
  useSkipStep,
} from "../lib/tauri-api";
import type { ExecutionStatus, RecipeEvent, StepExecution, StepStatus } from "../lib/types";

// Icons
function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function IconPause() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25v13.5m-7.5-13.5v13.5" />
    </svg>
  );
}

function IconPlay() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
    </svg>
  );
}

function IconStop() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 7.5A2.25 2.25 0 017.5 5.25h9a2.25 2.25 0 012.25 2.25v9a2.25 2.25 0 01-2.25 2.25h-9a2.25 2.25 0 01-2.25-2.25v-9z" />
    </svg>
  );
}

function IconRefresh() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
    </svg>
  );
}

function IconSkip() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 8.688c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062A1.125 1.125 0 013 16.81V8.688zM12.75 8.688c0-.864.933-1.405 1.683-.977l7.108 4.062a1.125 1.125 0 010 1.953l-7.108 4.062a1.125 1.125 0 01-1.683-.977V8.688z" />
    </svg>
  );
}

function IconCopy() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  
  return (
    <Tooltip content={copied ? "Copied!" : "Copy to clipboard"}>
      <Button
        isIconOnly
        size="sm"
        variant="flat"
        onPress={handleCopy}
        className="absolute top-2 right-2 opacity-60 hover:opacity-100"
      >
        {copied ? <IconCheck /> : <IconCopy />}
      </Button>
    </Tooltip>
  );
}

function getStatusColor(status: StepStatus | ExecutionStatus): "default" | "primary" | "secondary" | "success" | "warning" | "danger" {
  switch (status) {
    case "success":
    case "completed":
      return "success";
    case "running":
      return "primary";
    case "failed":
      return "danger";
    case "paused":
    case "retrying":
    case "waiting":
      return "warning";
    case "skipped":
    case "cancelled":
      return "default";
    default:
      return "default";
  }
}

function getStatusLabel(status: StepStatus | ExecutionStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function StepStatusIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "success":
      return <span className="text-success">✓</span>;
    case "failed":
      return <span className="text-danger">✗</span>;
    case "running":
      return <Spinner size="sm" />;
    case "waiting":
      return <span className="text-warning">⏳</span>;
    case "pending":
      return <span className="text-foreground/40">○</span>;
    case "skipped":
      return <span className="text-foreground/40">⊘</span>;
    case "retrying":
      return <span className="text-warning">↻</span>;
    case "cancelled":
      return <span className="text-foreground/40">⊗</span>;
    default:
      return <span className="text-foreground/40">?</span>;
  }
}

function IconChevronDown({ className }: { className?: string }) {
  return (
    <svg className={className || "w-4 h-4"} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

function StepCard({ step, onRetry, onSkip }: {
  step: StepExecution;
  onRetry: () => void;
  onSkip: () => void;
}) {
  const [isExpanded, setIsExpanded] = useState(step.status === "running" || step.status === "failed");
  const canRetry = step.status === "failed";
  const canSkip = step.status === "pending" || step.status === "waiting" || step.status === "failed";
  const hasLogs = step.error || step.output;
  
  return (
    <Card className={`border ${
      step.status === "running" ? "border-primary" :
      step.status === "failed" ? "border-danger" :
      step.status === "success" ? "border-success/50" :
      "border-divider"
    }`}>
      <CardBody className="p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className="mt-1">
              <StepStatusIcon status={step.status} />
            </div>
            <div className="flex-1 min-w-0">
              {/* Header - clickable to expand/collapse */}
              <div 
                className={`flex items-center gap-2 ${hasLogs ? 'cursor-pointer' : ''}`}
                onClick={() => hasLogs && setIsExpanded(!isExpanded)}
              >
                {hasLogs && (
                  <IconChevronDown className={`w-4 h-4 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
                )}
                <span className="font-mono text-sm">{step.step_id}</span>
                <Chip size="sm" color={getStatusColor(step.status)} variant="flat">
                  {getStatusLabel(step.status)}
                </Chip>
                {step.retry_attempt > 0 && (
                  <Chip size="sm" variant="flat">
                    Attempt {step.retry_attempt + 1}
                  </Chip>
                )}
                {!isExpanded && hasLogs && (
                  <span className="text-xs text-foreground/40 ml-2">
                    (click to expand logs)
                  </span>
                )}
              </div>
              
              {step.progress && (
                <div className="mt-2">
                  <Progress
                    size="sm"
                    value={step.progress.percent ?? 0}
                    color="primary"
                    className="max-w-xs"
                  />
                  {step.progress.message && (
                    <p className="text-xs text-foreground/60 mt-1">{step.progress.message}</p>
                  )}
                </div>
              )}
              
              {/* Collapsible logs section */}
              {isExpanded && (
                <>
                  {step.error && (
                    <div className="mt-2 p-3 rounded bg-danger/10 text-danger text-sm font-mono max-h-96 overflow-auto whitespace-pre-wrap select-text cursor-text relative">
                      <CopyButton text={step.error} />
                      {step.error}
                    </div>
                  )}
                  
                  {step.output && (
                    <div className="mt-2 p-3 rounded bg-black/90 text-green-400 text-sm font-mono max-h-96 overflow-auto whitespace-pre-wrap select-text cursor-text relative">
                      <CopyButton text={step.output} />
                      {step.output}
                    </div>
                  )}
                </>
              )}
              
              <div className="flex items-center gap-4 mt-2 text-xs text-foreground/60">
                {step.started_at && (
                  <span>Started: {new Date(step.started_at).toLocaleTimeString()}</span>
                )}
                {step.completed_at && (
                  <span>Completed: {new Date(step.completed_at).toLocaleTimeString()}</span>
                )}
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-1">
            {canRetry && (
              <Tooltip content="Retry this step">
                <Button
                  isIconOnly
                  size="sm"
                  variant="flat"
                  onPress={onRetry}
                >
                  <IconRefresh />
                </Button>
              </Tooltip>
            )}
            {canSkip && (
              <Tooltip content="Skip this step">
                <Button
                  isIconOnly
                  size="sm"
                  variant="flat"
                  onPress={onSkip}
                >
                  <IconSkip />
                </Button>
              </Tooltip>
            )}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function RecipeExecutionPage() {
  const params = useParams({ from: "/recipes/executions/$id" });
  const executionId = params.id;
  
  const executionQuery = useRecipeExecution(executionId);
  const pauseMutation = usePauseExecution();
  const resumeMutation = useResumeExecution();
  const cancelMutation = useCancelExecution();
  const retryMutation = useRetryStep();
  const skipMutation = useSkipStep();
  
  // Listen for real-time events and refetch on updates
  useEffect(() => {
    let unlisten: (() => void) | null = null;
    
    listenRecipeEvents((event) => {
      if ("execution_id" in event && event.execution_id === executionId) {
        // Refetch execution data when steps complete or fail
        if (event.type === "step_completed" || event.type === "step_failed" || 
            event.type === "execution_completed" || event.type === "execution_failed") {
          executionQuery.refetch();
        }
      }
    }).then(fn => {
      unlisten = fn;
    });
    
    return () => {
      if (unlisten) unlisten();
    };
  }, [executionId, executionQuery]);
  
  const execution = executionQuery.data;
  
  // Auto-refetch while running
  useEffect(() => {
    if (execution?.status === "running") {
      const interval = setInterval(() => {
        executionQuery.refetch();
      }, 2000); // Refresh every 2 seconds while running
      return () => clearInterval(interval);
    }
  }, [execution?.status, executionQuery]);
  
  if (executionQuery.isLoading || !execution) {
    return (
      <div className="h-full flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }
  
  const isRunning = execution.status === "running";
  const isPaused = execution.status === "paused";
  const isFinished = execution.status === "completed" || execution.status === "failed" || execution.status === "cancelled";
  
  const completedSteps = execution.steps.filter(s => s.status === "success").length;
  const totalSteps = execution.steps.length;
  const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;
  
  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between p-4 border-b border-divider bg-content1">
        <div className="flex items-center gap-4">
          <Button as={Link} to="/recipes" isIconOnly variant="flat" size="sm">
            <IconArrowLeft />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold">{execution.recipe_name}</h1>
              <Chip color={getStatusColor(execution.status)} variant="flat">
                {getStatusLabel(execution.status)}
              </Chip>
            </div>
            <p className="text-sm text-foreground/60">
              Started {new Date(execution.created_at).toLocaleString()}
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {isRunning && (
            <Button
              variant="flat"
              startContent={<IconPause />}
              onPress={() => pauseMutation.mutate(executionId)}
              isLoading={pauseMutation.isPending}
            >
              Pause
            </Button>
          )}
          
          {isPaused && (
            <Button
              color="primary"
              variant="flat"
              startContent={<IconPlay />}
              onPress={() => resumeMutation.mutate(executionId)}
              isLoading={resumeMutation.isPending}
            >
              Resume
            </Button>
          )}
          
          {(isRunning || isPaused) && (
            <Button
              color="danger"
              variant="flat"
              startContent={<IconStop />}
              onPress={() => cancelMutation.mutate(executionId)}
              isLoading={cancelMutation.isPending}
            >
              Cancel
            </Button>
          )}
        </div>
      </header>
      
      {/* Progress Bar */}
      <div className="px-6 py-4 border-b border-divider">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Progress</span>
          <span className="text-sm text-foreground/60">
            {completedSteps}/{totalSteps} steps completed
          </span>
        </div>
        <Progress
          size="md"
          value={progress}
          color={execution.status === "failed" ? "danger" : "primary"}
        />
      </div>
      
      {/* Content */}
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-4xl mx-auto space-y-4">
          {/* Error Message */}
          {execution.error && (
            <Card className="border border-danger/50 bg-danger/5">
              <CardBody className="p-4">
                <h3 className="font-semibold text-danger mb-2">Execution Failed</h3>
                <p className="text-sm">{execution.error}</p>
              </CardBody>
            </Card>
          )}
          
          {/* Steps */}
          {execution.steps.map((step) => (
            <StepCard
              key={step.step_id}
              step={step}
              onRetry={() => retryMutation.mutate({ executionId, stepId: step.step_id })}
              onSkip={() => skipMutation.mutate({ executionId, stepId: step.step_id })}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

