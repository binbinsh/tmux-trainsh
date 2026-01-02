import { useState } from "react";
import { Terminal, Loader2 } from "lucide-react";
import type { RemoteTmuxSession } from "@/lib/tauri-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export function TmuxSessionSelectModal({
  sessions,
  isOpen,
  onClose,
  onSelect,
  onCreate,
  isLoading,
}: {
  sessions: RemoteTmuxSession[];
  isOpen: boolean;
  onClose: () => void;
  onSelect: (sessionName: string) => void;
  onCreate: (sessionName: string) => void;
  isLoading: boolean;
}) {
  const [newSessionName, setNewSessionName] = useState("");

  const handleCreate = () => {
    const name = newSessionName.trim() || "main";
    onCreate(name);
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Terminal className="h-5 w-5" />
            <DialogTitle>Select Tmux Session</DialogTitle>
          </div>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="text-center py-4">
              <p className="text-muted-foreground mb-4">No tmux sessions running on this host.</p>
              <p className="text-sm text-muted-foreground">A new session will be created when you connect.</p>
            </div>
          ) : (
            <>
              <div>
                <p className="text-sm text-muted-foreground mb-3">
                  Found {sessions.length} existing session{sessions.length > 1 ? "s" : ""}. Select one to attach:
                </p>
                <div className="space-y-1">
                  {sessions.map((s) => (
                    <Button
                      key={s.name}
                      type="button"
                      variant="outline"
                      onClick={() => onSelect(s.name)}
                      className={cn(
                        "w-full h-auto justify-start text-left p-3 rounded-lg border border-border transition-colors",
                        "hover:bg-accent hover:border-accent-foreground/20"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <p className="font-mono font-medium truncate">{s.name}</p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-muted-foreground">
                              {s.windows} window{s.windows !== 1 ? "s" : ""}
                            </span>
                            {s.attached && (
                              <Badge variant="default" className="h-5 text-xs">
                                attached
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    </Button>
                  ))}
                </div>
              </div>
              <Separator />
            </>
          )}

          <div className="space-y-2">
            <Label htmlFor="new-session" className="text-sm font-medium">
              Or create a new session:
            </Label>
            <div className="flex gap-2">
              <Input
                id="new-session"
                placeholder="Session name (default: main)"
                value={newSessionName}
                onChange={(e) => setNewSessionName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                }}
                className="flex-1 font-mono"
              />
              <Button
                onClick={handleCreate}
                className="min-w-[80px]"
              >
                Create
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
