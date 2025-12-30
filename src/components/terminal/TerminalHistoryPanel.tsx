import { Button, Chip, Select, SelectItem, Spinner } from "@nextui-org/react";
import { motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  termHistoryInfo,
  termHistoryRange,
  termHistorySteps,
  type TermHistoryStep,
} from "../../lib/tauri-api";
import { useTerminal } from "../../contexts/TerminalContext";

const HISTORY_CHUNK_BYTES = 256 * 1024;
const SCROLL_TOP_THRESHOLD = 48;
const ANSI_REGEX = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
const OSC_REGEX = /\x1b\][^\x07]*\x07/g;

function stripAnsi(text: string) {
  return text.replace(OSC_REGEX, "").replace(ANSI_REGEX, "");
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  for (const unit of units) {
    if (value < 1024) return `${value.toFixed(1)} ${unit}`;
    value /= 1024;
  }
  return `${value.toFixed(1)} PB`;
}

export function TerminalHistoryPanel() {
  const { activeId, historyPanelVisible, setHistoryPanelVisible } = useTerminal();
  const [chunks, setChunks] = useState<string[]>([]);
  const [historySize, setHistorySize] = useState(0);
  const [rangeStart, setRangeStart] = useState(0);
  const [startOffset, setStartOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [steps, setSteps] = useState<TermHistoryStep[]>([]);
  const [selectedStep, setSelectedStep] = useState("__all__");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const restoreScrollRef = useRef<{ height: number; top: number } | null>(null);

  const stepOptions = useMemo(() => {
    if (steps.length === 0) return [];
    return steps.map((step) => {
      const statusLabel = step.status ? ` · ${step.status}` : "";
      const exitLabel = step.exitCode != null ? ` (${step.exitCode})` : "";
      return {
        key: step.stepId,
        label: `#${step.stepIndex + 1} ${step.stepId}${statusLabel}${exitLabel}`,
      };
    });
  }, [steps]);

  const loadRangeTail = useCallback(async (id: string, start: number, end: number) => {
    const offset = Math.max(start, end - HISTORY_CHUNK_BYTES);
    const limit = Math.max(0, end - offset);
    if (limit === 0) {
      setChunks([]);
      setStartOffset(offset);
      setHasMore(false);
      return;
    }
    setIsLoading(true);
    try {
      const chunk = await termHistoryRange({
        id,
        offset,
        limit,
      });
      setChunks([stripAnsi(chunk.data)]);
      setStartOffset(offset);
      setHasMore(offset > start);
      requestAnimationFrame(() => {
        const container = scrollRef.current;
        if (container) {
          container.scrollTop = container.scrollHeight;
        }
      });
    } catch (error) {
      console.error("[TerminalHistory] Failed to load history:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const refreshHistory = useCallback(async () => {
    if (!activeId) return;
    try {
      const info = await termHistoryInfo(activeId);
      setHistorySize(info.sizeBytes);
      setRangeStart(0);
      setSelectedStep("__all__");
      const stepList = await termHistorySteps(activeId);
      setSteps(stepList);
      await loadRangeTail(activeId, 0, info.sizeBytes);
    } catch (error) {
      console.error("[TerminalHistory] Failed to refresh:", error);
    }
  }, [activeId, loadRangeTail]);

  useEffect(() => {
    if (!historyPanelVisible) return;
    void refreshHistory();
  }, [historyPanelVisible, refreshHistory]);

  useEffect(() => {
    if (!activeId) return;
    if (!historyPanelVisible) return;
    const range =
      selectedStep === "__all__"
        ? { start: 0, end: historySize }
        : (() => {
            const step = steps.find((item) => item.stepId === selectedStep);
            if (!step) return { start: 0, end: historySize };
            return { start: step.startOffset, end: step.endOffset };
          })();
    setRangeStart(range.start);
    void loadRangeTail(activeId, range.start, range.end);
  }, [activeId, historyPanelVisible, selectedStep, steps, historySize, loadRangeTail]);

  const loadOlder = useCallback(async () => {
    if (!activeId || isLoading || !hasMore) return;
    const newOffset = Math.max(rangeStart, startOffset - HISTORY_CHUNK_BYTES);
    const limit = startOffset - newOffset;
    if (limit <= 0) {
      setHasMore(false);
      return;
    }
    const container = scrollRef.current;
    if (container) {
      restoreScrollRef.current = {
        height: container.scrollHeight,
        top: container.scrollTop,
      };
    }
    setIsLoading(true);
    try {
      const chunk = await termHistoryRange({
        id: activeId,
        offset: newOffset,
        limit,
      });
      setChunks((prev) => [stripAnsi(chunk.data), ...prev]);
      setStartOffset(newOffset);
      setHasMore(newOffset > rangeStart);
    } catch (error) {
      console.error("[TerminalHistory] Failed to load older history:", error);
    } finally {
      setIsLoading(false);
    }
  }, [activeId, hasMore, isLoading, rangeStart, startOffset]);

  useEffect(() => {
    const restore = restoreScrollRef.current;
    const container = scrollRef.current;
    if (!restore || !container) return;
    const nextHeight = container.scrollHeight;
    container.scrollTop = restore.top + (nextHeight - restore.height);
    restoreScrollRef.current = null;
  }, [chunks]);

  const handleScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container || isLoading || !hasMore) return;
    if (container.scrollTop <= SCROLL_TOP_THRESHOLD) {
      void loadOlder();
    }
  }, [hasMore, isLoading, loadOlder]);

  if (!historyPanelVisible) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 16 }}
      transition={{ duration: 0.15 }}
      className="absolute inset-3 z-20 bg-[var(--term-card)] border border-[var(--term-border)] rounded-2xl shadow-[var(--term-shadow-strong)] backdrop-blur-xl flex flex-col overflow-hidden"
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-divider/60">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-foreground/60">History</span>
          <Chip size="sm" variant="flat" className="text-xs">
            {formatBytes(historySize)}
          </Chip>
          {isLoading && chunks.length === 0 ? (
            <div className="flex items-center gap-2 text-xs text-foreground/60">
              <Spinner size="sm" />
              Loading...
            </div>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <Select labelPlacement="inside" size="sm"
          selectedKeys={new Set([selectedStep])}
          onSelectionChange={(keys) => {
            const key = Array.from(keys)[0];
            setSelectedStep(typeof key === "string" ? key : "__all__");
          }}
          className="min-w-[220px]"
          aria-label="History Range"><SelectItem key="__all__">All Output</SelectItem>
          {stepOptions.map((step) => (
            <SelectItem key={step.key}>{step.label}</SelectItem>
          ))}</Select>
          <Button size="sm" variant="flat" onPress={() => setHistoryPanelVisible(false)}>
            Close
          </Button>
        </div>
      </div>
      <div className="flex-1 min-h-0 bg-[var(--term-card-muted)]">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full overflow-auto px-4 py-3 font-mono text-xs leading-5 text-foreground/80 select-text"
        >
          {chunks.length === 0 && !isLoading ? (
            <div className="text-sm text-foreground/50">No history yet.</div>
          ) : (
            <pre className="whitespace-pre-wrap break-words">{chunks.join("")}</pre>
          )}
          {isLoading && chunks.length > 0 ? (
            <div className="mt-3 text-xs text-foreground/50">Loading more...</div>
          ) : null}
        </div>
      </div>
    </motion.div>
  );
}
