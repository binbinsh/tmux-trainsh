import { Button } from "@/components/ui";
import { Card, CardContent } from "@/components/ui";
import { Input } from "@/components/ui";
import { Label } from "@/components/ui";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { Skeleton } from "@/components/ui";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui";
import { Loader2 } from "lucide-react";
import { Terminal } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { AppIcon } from "../components/AppIcon";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { copyText } from "../lib/clipboard";
import { open } from "@tauri-apps/plugin-shell";
import {
  getConfig,
  pricingApi,
  saveConfig,
  secretsApi,
  sshKeyCandidates,
  sshSecretKeyCandidates,
  sshPrivateKey,
  sshPublicKey,
  useFetchExchangeRates,
  useColabPricingCalculation,
  usePricingSettings,
  useUpdateColabGpuPricing,
  useUpdateColabSubscription,
  useUpdateDisplayCurrency
} from "../lib/tauri-api";
import type { ColabGpuPricing, Currency, SecretMeta, SecretSuggestion, TrainshConfig, AppThemeName } from "../lib/types";
import { CURRENCIES, formatPriceWithRates, getCurrencySymbol } from "../lib/currency";
import { APP_THEME_OPTIONS, DEFAULT_APP_THEME, applyAppTheme } from "../lib/terminal-themes";
import { cn } from "@/lib/utils";
import { Eye, EyeOff, X, Check } from "lucide-react";

// ============================================================
// Icons
// ============================================================

function IconSettings({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function IconServer({ className }: { className?: string }) {
  return <AppIcon name="vast" className={className} alt="Vast.ai" />;
}

function IconBeaker({ className }: { className?: string }) {
  return <AppIcon name="colab" className={className} alt="Google Colab" />;
}

function IconKey({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 013 3m3 0a6 6 0 01-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1121.75 8.25z" />
    </svg>
  );
}

function IconCopy({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function IconEdit({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
    </svg>
  );
}

function IconTrash({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

// ============================================================
// Section Card Component - Using unified doppio-card style
// ============================================================

type SectionId = "general" | "vast" | "scamalytics" | "colab" | "secrets";

type SectionConfig = {
  id: SectionId;
  title: string;
  subtitle: string;
  icon: SectionIconType;
};

const SECTIONS: SectionConfig[] = [
  { id: "general", title: "General", subtitle: "Appearance and preferences", icon: "settings" },
  { id: "vast", title: "Vast.ai", subtitle: "API and SSH settings", icon: "server" },
  { id: "scamalytics", title: "Scamalytics", subtitle: "IP risk intelligence", icon: "key" },
  { id: "colab", title: "Google Colab", subtitle: "Subscription and GPU pricing", icon: "beaker" },
  { id: "secrets", title: "Secrets", subtitle: "SSH keys and tokens", icon: "key" },
];

type SectionIconType = "settings" | "server" | "beaker" | "key" | "terminal";

function IconTerminal({ className }: { className?: string }) {
  return <Terminal className={className} />;
}

function SectionNavItem({
  section,
  isSelected,
  onClick,
}: {
  section: SectionConfig;
  isSelected: boolean;
  onClick: () => void;
}) {
  const IconComponent = {
    settings: IconSettings,
    server: IconServer,
    beaker: IconBeaker,
    key: IconKey,
    terminal: IconTerminal,
  }[section.icon];

  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 p-3 rounded-lg text-left transition-colors",
        isSelected
          ? "bg-primary/10 text-primary"
          : "hover:bg-muted text-foreground/70 hover:text-foreground"
      )}
    >
      <div className={cn(
        "w-9 h-9 rounded-lg flex items-center justify-center shrink-0",
        isSelected ? "bg-primary/20" : "bg-muted"
      )}>
        <IconComponent className="w-4 h-4" />
      </div>
      <div className="min-w-0">
        <div className="text-sm font-medium truncate">{section.title}</div>
        <div className="text-xs text-foreground/50 truncate">{section.subtitle}</div>
      </div>
    </button>
  );
}

// ============================================================
// Main Settings Page
// ============================================================

const SCAMALYTICS_SIGNUP_URL = "https://scamalytics.com/ip/api/enquiry?monthly_api_calls=5000";

export function SettingsPage() {
  const cfgQuery = useQuery({
    queryKey: ["config"],
    queryFn: getConfig
  });
  const sshKeysQuery = useQuery({
    queryKey: ["sshKeyCandidates"],
    queryFn: sshKeyCandidates
  });
  const sshSecretKeysQuery = useQuery({
    queryKey: ["sshSecretKeyCandidates"],
    queryFn: sshSecretKeyCandidates
  });
  const fetchRates = useFetchExchangeRates();

  const [draft, setDraft] = useState<TrainshConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [isColabDirty, setIsColabDirty] = useState(false);
  const colabSaveRef = useRef<null | (() => Promise<void>)>(null);
  const [selectedSection, setSelectedSection] = useState<SectionId>("general");

  const sshKeyOptions = useMemo(() => {
    const secrets = sshSecretKeysQuery.data ?? [];
    const files = sshKeysQuery.data ?? [];
    return [...secrets, ...files];
  }, [sshKeysQuery.data, sshSecretKeysQuery.data]);

  const handleOpenScamalyticsSignup = useCallback(async (event?: MouseEvent<HTMLAnchorElement>) => {
    event?.preventDefault();
    try {
      await open(SCAMALYTICS_SIGNUP_URL);
    } catch (err) {
      console.error("Failed to open Scamalytics registration:", err);
    }
  }, []);

  useEffect(() => {
    if (cfgQuery.data) {
      setDraft({
        ...cfgQuery.data,
        vast: {
          ...cfgQuery.data.vast,
          ssh_user: cfgQuery.data.vast.ssh_user.trim() || "root",
          ssh_connection_preference: cfgQuery.data.vast.ssh_connection_preference ?? "proxy",
        },
        scamalytics: {
          ...cfgQuery.data.scamalytics,
          user: cfgQuery.data.scamalytics.user?.trim() || null,
          api_key: cfgQuery.data.scamalytics.api_key?.trim() || null,
          host: cfgQuery.data.scamalytics.host.trim() || "https://api11.scamalytics.com/v3/",
        }
      });
    }
  }, [cfgQuery.data]);

  const isDirty = useMemo(() => {
    if (!draft || !cfgQuery.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(cfgQuery.data) || isColabDirty;
  }, [draft, cfgQuery.data, isColabDirty]);

  async function onSave() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const normalized: TrainshConfig = {
        ...draft,
        vast: {
          ...draft.vast,
          ssh_user: draft.vast.ssh_user.trim() || "root",
          ssh_key_path: draft.vast.ssh_key_path?.trim() || null,
          ssh_connection_preference: draft.vast.ssh_connection_preference === "direct" ? "direct" : "proxy",
        },
        scamalytics: {
          ...draft.scamalytics,
          user: draft.scamalytics.user?.trim() || null,
          api_key: draft.scamalytics.api_key?.trim() || null,
          host: draft.scamalytics.host.trim() || "https://api11.scamalytics.com/v3/",
        }
      };
      setDraft(normalized);
      await saveConfig(normalized);
      if (colabSaveRef.current) {
        await colabSaveRef.current();
      }
      setSavedAt(new Date().toLocaleString());
      await cfgQuery.refetch();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }

  const isLoading = cfgQuery.isLoading || !draft;

  if (isLoading) {
    return (
      <div className="doppio-page">
        <div className="doppio-page-content">
          {/* Skeleton toolbar */}
          <div className="termius-toolbar">
            <div className="termius-toolbar-row justify-between">
              <div className="min-w-0">
                <Skeleton className="h-8 w-32 rounded-lg mb-2" />
                <Skeleton className="h-4 w-48 rounded-lg" />
              </div>
              <Skeleton className="h-9 w-24 rounded-lg" />
            </div>
          </div>
          {/* Skeleton two-column layout */}
          <div className="flex gap-6 flex-1 min-h-0">
            {/* Left sidebar skeleton */}
            <div className="w-64 shrink-0 space-y-2">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="flex items-center gap-3 p-3">
                  <Skeleton className="w-9 h-9 rounded-lg shrink-0" />
                  <div className="flex-1">
                    <Skeleton className="h-4 w-20 rounded mb-1" />
                    <Skeleton className="h-3 w-28 rounded" />
                  </div>
                </div>
              ))}
            </div>
            {/* Right content skeleton */}
            <div className="flex-1 doppio-card p-6 space-y-4">
              <Skeleton className="h-6 w-32 rounded-lg" />
              <Skeleton className="h-10 w-full rounded-lg" />
              <Skeleton className="h-10 w-full rounded-lg" />
              <Skeleton className="h-10 w-2/3 rounded-lg" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (cfgQuery.error) {
    return (
      <div className="h-full p-6">
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-destructive">
              Failed to load config: {(cfgQuery.error as Error)?.message ?? "Unknown error"}
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="doppio-page">
      <div className="doppio-page-content">
        <div className="termius-toolbar">
          <div className="termius-toolbar-row justify-between">
            <div className="min-w-0">
              <h1 className="doppio-page-title">Settings</h1>
              <p className="doppio-page-subtitle">Configuration saved locally</p>
            </div>
            <div className="flex items-center gap-3">
              {savedAt && !saveError && (
                <span className="text-xs text-success flex items-center gap-1">
                  <Check className="w-3 h-3" />
                  Saved {savedAt}
                </span>
              )}
              {saveError && (
                <span className="text-xs text-destructive">Failed: {saveError}</span>
              )}
              <Button
                size="sm"
                variant="secondary"
                onClick={() => fetchRates.mutate()}
                disabled={fetchRates.isPending}
              >
                {fetchRates.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                Refresh Rates
              </Button>
              <Button
                size="sm"
                onClick={onSave}
                disabled={!draft || saving || !isDirty}
              >
                {saving && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
                Save
              </Button>
            </div>
          </div>
        </div>

        {/* Two-column layout */}
        <div className="flex gap-6 flex-1 min-h-0">
          {/* Left sidebar - section navigation */}
          <div className="w-64 shrink-0 space-y-1">
            {SECTIONS.map((section) => (
              <SectionNavItem
                key={section.id}
                section={section}
                isSelected={selectedSection === section.id}
                onClick={() => setSelectedSection(section.id)}
              />
            ))}
          </div>

          {/* Right panel - section content */}
          <div className="flex-1 doppio-card p-6 overflow-auto">
            {selectedSection === "general" && (
              <div className="space-y-6">
                <h2 className="text-lg font-semibold">General</h2>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label htmlFor="app-theme">Appearance</Label>
                    <Select
                      value={draft.terminal?.theme ?? DEFAULT_APP_THEME}
                      onValueChange={(value) => {
                        const themeName = value as AppThemeName;
                        setDraft({
                          ...draft,
                          terminal: { ...draft.terminal, theme: themeName }
                        });
                        // Apply theme immediately for preview
                        applyAppTheme(themeName);
                      }}
                    >
                      <SelectTrigger id="app-theme">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {APP_THEME_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            <div className="flex flex-col">
                              <span>{opt.label}</span>
                              <span className="text-xs text-foreground/50">{opt.description}</span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-foreground/50">
                      Choose between light and dark mode. Affects the entire application.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="hf-home">HuggingFace Cache (HF_HOME)</Label>
                    <Input
                      id="hf-home"
                      value={draft.colab.hf_home ?? ""}
                      onChange={(e) =>
                        setDraft({ ...draft, colab: { ...draft.colab, hf_home: e.target.value.trim() ? e.target.value : null } })
                      }
                      placeholder="~/.cache/huggingface"
                    />
                  </div>
                  <DisplayCurrencySection />
                </div>
              </div>
            )}

            {selectedSection === "vast" && (
              <div className="space-y-6">
                <h2 className="text-lg font-semibold">Vast.ai</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="vast-api-key">API Key</Label>
                    <Input
                      id="vast-api-key"
                      type="password"
                      value={draft.vast.api_key ?? ""}
                      onChange={(e) =>
                        setDraft({ ...draft, vast: { ...draft.vast, api_key: e.target.value.trim() ? e.target.value : null } })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="vast-url">Console URL</Label>
                    <Input
                      id="vast-url"
                      value={draft.vast.url}
                      onChange={(e) =>
                        setDraft({ ...draft, vast: { ...draft.vast, url: e.target.value } })
                      }
                    />
                  </div>
                </div>
                <VastPricingSection />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="ssh-user">SSH User</Label>
                    <Input
                      id="ssh-user"
                      value={draft.vast.ssh_user}
                      onChange={(e) =>
                        setDraft({ ...draft, vast: { ...draft.vast, ssh_user: e.target.value || "root" } })
                      }
                      placeholder="root"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-connection">SSH Connection</Label>
                    <Select
                      value={draft.vast.ssh_connection_preference ?? "proxy"}
                      onValueChange={(value) => {
                        setDraft({
                          ...draft,
                          vast: { ...draft.vast, ssh_connection_preference: value === "direct" ? "direct" : "proxy" }
                        });
                      }}
                    >
                      <SelectTrigger id="ssh-connection">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="proxy">Proxy (sshX.vast.ai)</SelectItem>
                        <SelectItem value="direct">Direct (public IP + direct port)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="ssh-key">SSH Key</Label>
                    <Select
                      value={draft.vast.ssh_key_path || ""}
                      onValueChange={(value) => {
                        setDraft({
                          ...draft,
                          vast: { ...draft.vast, ssh_key_path: value?.trim() ? value : null }
                        });
                      }}
                      disabled={
                        (sshKeysQuery.isLoading || sshSecretKeysQuery.isLoading)
                          ? false
                          : sshKeyOptions.length === 0
                      }
                    >
                      <SelectTrigger id="ssh-key">
                        <SelectValue placeholder={
                          sshKeysQuery.isLoading || sshSecretKeysQuery.isLoading
                            ? "Loading..."
                            : "Select a key (secret or ~/.ssh)"
                        } />
                      </SelectTrigger>
                      <SelectContent>
                        {sshKeyOptions.map((value) => {
                          const isSecret = value.startsWith("${secret:") && value.endsWith("}");
                          const label = isSecret ? value.slice("${secret:".length, -1) : (value.split("/").slice(-1)[0] ?? value);
                          return (
                            <SelectItem key={value} value={value}>
                              <span className="font-mono text-sm">{label}</span>
                              <span className="text-foreground/50 text-xs ml-2">
                                {isSecret ? "secret" : value}
                              </span>
                            </SelectItem>
                          );
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            )}

            {selectedSection === "scamalytics" && (
              <div className="space-y-6">
                <h2 className="text-lg font-semibold">Scamalytics</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="scamalytics-user">Account ID</Label>
                    <Input
                      id="scamalytics-user"
                      value={draft.scamalytics.user ?? ""}
                      onChange={(e) =>
                        setDraft({ ...draft, scamalytics: { ...draft.scamalytics, user: e.target.value.trim() ? e.target.value : null } })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="scamalytics-api-key">API Key</Label>
                    <Input
                      id="scamalytics-api-key"
                      type="password"
                      value={draft.scamalytics.api_key ?? ""}
                      onChange={(e) =>
                        setDraft({ ...draft, scamalytics: { ...draft.scamalytics, api_key: e.target.value.trim() ? e.target.value : null } })
                      }
                    />
                  </div>
                </div>
                <p className="text-xs text-foreground/60">
                  Need an API key?{" "}
                  <a
                    href={SCAMALYTICS_SIGNUP_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                    onClick={handleOpenScamalyticsSignup}
                  >
                    Register for a Scamalytics API key
                  </a>
                </p>
              </div>
            )}

            {selectedSection === "colab" && (
              <div className="space-y-6">
                <h2 className="text-lg font-semibold">Google Colab</h2>
                <ColabPricingSection
                  onDirtyChange={setIsColabDirty}
                  registerSave={(saveFn) => {
                    colabSaveRef.current = saveFn;
                  }}
                />
              </div>
            )}

            {selectedSection === "secrets" && (
              <div className="space-y-6">
                <h2 className="text-lg font-semibold">Secrets</h2>
                <p className="text-sm text-foreground/60">SSH keys and tokens stored securely. Use {"{secret:name}"} syntax in skills.</p>
                <SecretsSection />
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

// ============================================================
// Display Currency Section
// ============================================================

function DisplayCurrencySection() {
  const pricingQuery = usePricingSettings();
  const updateDisplayCurrency = useUpdateDisplayCurrency();

  if (pricingQuery.isLoading) {
    return <Loader2 className="w-4 h-4 animate-spin" />;
  }

  if (!pricingQuery.data) {
    return null;
  }

  const displayCurrency = pricingQuery.data.display_currency ?? "USD";
  const updatedAt = pricingQuery.data.exchange_rates.updated_at;

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor="display-currency">Default Currency</Label>
        <Select
          value={displayCurrency}
          onValueChange={async (value) => {
            const selected = value as Currency;
            if (!selected || selected === displayCurrency) return;
            await updateDisplayCurrency.mutateAsync(selected);
          }}
        >
          <SelectTrigger id="display-currency">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CURRENCIES.map((c) => (
              <SelectItem key={c.value} value={c.value}>
                {c.symbol} {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <p className="text-xs text-foreground/50">
        Exchange rates updated: {new Date(updatedAt).toLocaleString()}
      </p>
    </div>
  );
}

// ============================================================
// Vast.ai Pricing Section
// ============================================================

function VastPricingSection() {
  const pricingQuery = useQuery({
    queryKey: ["pricing"],
    queryFn: pricingApi.get
  });

  const settings = pricingQuery.data;

  if (pricingQuery.isLoading) {
    return <Loader2 className="w-4 h-4 animate-spin" />;
  }

  if (!settings?.vast_rates) {
    return null;
  }

  const displayCurrency = settings.display_currency ?? "USD";
  const exchangeRates = settings.exchange_rates;
  const formatRate = (value: number, decimals = 4) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="flex justify-between items-center p-3 bg-muted rounded-lg">
          <span className="text-sm text-foreground/60">Storage</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.storage_per_gb_month)}/GB/mo</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-muted rounded-lg">
          <span className="text-sm text-foreground/60">Egress</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.network_egress_per_gb)}/GB</span>
        </div>
        <div className="flex justify-between items-center p-3 bg-muted rounded-lg">
          <span className="text-sm text-foreground/60">Ingress</span>
          <span className="font-mono text-sm">{formatRate(settings.vast_rates.network_ingress_per_gb)}/GB</span>
        </div>
      </div>
      <p className="text-xs text-foreground/40">
        Default pricing rates apply to storage/egress/ingress. GPU hourly rates are fetched from Vast.ai API per
        instance.
      </p>
    </div>
  );
}

// ============================================================
// Colab Pricing Section (Subscription + GPU Pricing together)
// ============================================================

type ColabPricingSectionProps = {
  onDirtyChange?: (dirty: boolean) => void;
  registerSave?: (saveFn: () => Promise<void>) => void;
};

function ColabPricingSection({ onDirtyChange, registerSave }: ColabPricingSectionProps) {
  const pricingQuery = useQuery({ queryKey: ["pricing"], queryFn: pricingApi.get });
  const calculationQuery = useColabPricingCalculation();
  const updateSubscription = useUpdateColabSubscription();
  const updateGpuPricing = useUpdateColabGpuPricing();

  const [subName, setSubName] = useState("");
  const [subPrice, setSubPrice] = useState("");
  const [subCurrency, setSubCurrency] = useState<Currency>("USD");
  const [subUnits, setSubUnits] = useState("");
  const [gpuList, setGpuList] = useState<ColabGpuPricing[]>([]);
  const [newGpuName, setNewGpuName] = useState("");
  const [newGpuUnits, setNewGpuUnits] = useState("");

  useEffect(() => {
    if (pricingQuery.data) {
      const { subscription, gpu_pricing } = pricingQuery.data.colab;
      setSubName(subscription.name);
      setSubPrice(subscription.price.toString());
      setSubCurrency(subscription.currency);
      setSubUnits(subscription.total_units.toString());
      setGpuList(gpu_pricing);
    }
  }, [pricingQuery.data]);

  const handleSaveSubscription = async () => {
    const price = parseFloat(subPrice);
    const units = parseFloat(subUnits);
    if (isNaN(price) || isNaN(units) || price <= 0 || units <= 0) return;
    await updateSubscription.mutateAsync({
      name: subName.trim() || "Colab Pro",
      price,
      currency: subCurrency,
      total_units: units
    });
  };

  const handleSaveGpuPricing = async () => {
    await updateGpuPricing.mutateAsync(gpuList);
  };

  const handleAddGpu = () => {
    const units = parseFloat(newGpuUnits);
    if (!newGpuName.trim() || isNaN(units) || units <= 0) return;
    setGpuList((prev) => [...prev, { gpu_name: newGpuName.trim(), units_per_hour: units }]);
    setNewGpuName("");
    setNewGpuUnits("");
  };

  const calculation = calculationQuery.data;
  const displayCurrency = pricingQuery.data?.display_currency ?? "USD";
  const exchangeRates = pricingQuery.data?.exchange_rates;
  const formatUsd = (value: number, decimals = 4) =>
    formatPriceWithRates(value, "USD", displayCurrency, exchangeRates, decimals);

  const initialSubscription = pricingQuery.data?.colab.subscription;
  const initialGpuPricing = pricingQuery.data?.colab.gpu_pricing ?? [];

  const isSubscriptionDirty = useMemo(() => {
    if (!initialSubscription) return false;
    const price = Number(subPrice);
    const units = Number(subUnits);
    return (
      subName !== initialSubscription.name ||
      subCurrency !== initialSubscription.currency ||
      price !== initialSubscription.price ||
      units !== initialSubscription.total_units
    );
  }, [initialSubscription, subCurrency, subName, subPrice, subUnits]);

  const isGpuPricingDirty = useMemo(() => {
    if (!pricingQuery.data) return false;
    if (gpuList.length !== initialGpuPricing.length) return true;
    return gpuList.some((gpu, idx) => {
      const original = initialGpuPricing[idx];
      if (!original) return true;
      return (
        gpu.gpu_name !== original.gpu_name ||
        gpu.units_per_hour !== original.units_per_hour
      );
    });
  }, [gpuList, initialGpuPricing, pricingQuery.data]);

  const saveAll = useCallback(async () => {
    if (!pricingQuery.data) return;
    if (isSubscriptionDirty) {
      await handleSaveSubscription();
    }
    if (isGpuPricingDirty) {
      await handleSaveGpuPricing();
    }
  }, [handleSaveSubscription, handleSaveGpuPricing, isSubscriptionDirty, isGpuPricingDirty, pricingQuery.data]);

  useEffect(() => {
    onDirtyChange?.(isSubscriptionDirty || isGpuPricingDirty);
  }, [isSubscriptionDirty, isGpuPricingDirty, onDirtyChange]);

  useEffect(() => {
    registerSave?.(saveAll);
  }, [registerSave, saveAll]);

  if (pricingQuery.isLoading) {
    return <Loader2 className="w-6 h-6 mx-auto animate-spin" />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="space-y-2">
            <Label htmlFor="plan-name">Plan Name</Label>
            <Input
              id="plan-name"
              value={subName}
              onChange={(e) => setSubName(e.target.value)}
              placeholder="Colab Pro"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="plan-price">Price</Label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-foreground/50 text-xs">
                {getCurrencySymbol(subCurrency)}
              </span>
              <Input
                id="plan-price"
                type="number"
                value={subPrice}
                onChange={(e) => setSubPrice(e.target.value)}
                placeholder="11.99"
                className="pl-6"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="plan-currency">Currency</Label>
            <Select
              value={subCurrency}
              onValueChange={(value) => {
                const selected = value as Currency;
                if (selected) setSubCurrency(selected);
              }}
            >
              <SelectTrigger id="plan-currency">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.symbol} {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="compute-units">Compute Units</Label>
            <Input
              id="compute-units"
              type="number"
              value={subUnits}
              onChange={(e) => setSubUnits(e.target.value)}
              placeholder="100"
            />
          </div>
        </div>

        {calculation && (
          <div className="flex justify-between items-center p-3 bg-success/10 rounded-lg">
            <span className="text-sm text-foreground/70">Price per compute unit</span>
            <span className="font-mono font-semibold text-success">
              {formatUsd(calculation.price_per_unit_usd)}
            </span>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <div className="max-h-[280px] overflow-auto border border-border rounded-lg">
          <Table>
            <TableHeader className="bg-muted">
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-left p-3 text-sm font-medium">GPU</TableHead>
                <TableHead className="text-left p-3 text-sm font-medium w-[90px]">Units/Hr</TableHead>
                <TableHead className="text-left p-3 text-sm font-medium w-[100px]">Units/24Hr</TableHead>
                <TableHead className="text-left p-3 text-sm font-medium w-[85px]">{displayCurrency}/Hr</TableHead>
                <TableHead className="text-left p-3 text-sm font-medium w-[95px]">{displayCurrency}/24Hr</TableHead>
                <TableHead className="w-[40px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {gpuList.length === 0 ? (
                <TableRow className="border-border hover:bg-transparent">
                  <TableCell colSpan={6} className="text-center p-4 text-sm text-foreground/50">
                    No GPUs configured
                  </TableCell>
                </TableRow>
              ) : (
                gpuList.map((gpu, idx) => {
                  const calcGpu = calculation?.gpu_prices.find((g) => g.gpu_name === gpu.gpu_name);
                  return (
                    <TableRow key={idx} className="border-border">
                      <TableCell className="p-2">
                        <Input
                          value={gpu.gpu_name}
                          onChange={(e) => {
                            if (e.target.value.trim()) {
                              setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, gpu_name: e.target.value } : g)));
                            }
                          }}
                          className="h-8 font-semibold border-0 border-b border-foreground/20 rounded-none focus-visible:ring-0 focus-visible:border-foreground bg-transparent"
                        />
                      </TableCell>
                      <TableCell className="p-2">
                        <Input
                          type="number"
                          value={gpu.units_per_hour.toString()}
                          onChange={(e) => {
                            const val = parseFloat(e.target.value);
                            if (!isNaN(val) && val > 0) {
                              setGpuList((prev) => prev.map((g, i) => (i === idx ? { ...g, units_per_hour: val } : g)));
                            }
                          }}
                          className="h-8 text-center w-14 border-0 border-b border-foreground/20 rounded-none focus-visible:ring-0 focus-visible:border-foreground bg-transparent"
                        />
                      </TableCell>
                      <TableCell className="p-2 font-mono text-foreground/60">
                        {(gpu.units_per_hour * 24).toFixed(1)}
                      </TableCell>
                      <TableCell className="p-2 font-mono text-success">
                        {calcGpu ? formatUsd(calcGpu.price_usd_per_hour) : "-"}
                      </TableCell>
                      <TableCell className="p-2 font-mono text-warning">
                        {calcGpu ? formatUsd(calcGpu.price_usd_per_hour * 24, 2) : "-"}
                      </TableCell>
                      <TableCell className="p-2">
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => setGpuList((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          <X className="w-4 h-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-end gap-3">
          <div className="flex-1 space-y-2">
            <Label htmlFor="new-gpu-name">New GPU</Label>
            <Input
              id="new-gpu-name"
              value={newGpuName}
              onChange={(e) => setNewGpuName(e.target.value)}
              placeholder="e.g., A100"
            />
          </div>
          <div className="w-28 space-y-2">
            <Label htmlFor="new-gpu-units">Units/Hr</Label>
            <Input
              id="new-gpu-units"
              type="number"
              value={newGpuUnits}
              onChange={(e) => setNewGpuUnits(e.target.value)}
              placeholder="12.29"
            />
          </div>
          <Button
            variant="secondary"
            className="h-10"
            onClick={handleAddGpu}
            disabled={!newGpuName.trim() || !newGpuUnits.trim()}
          >
            Add
          </Button>
        </div>

        {calculation && (
          <p className="text-xs text-foreground/40">
            Based on {calculation.subscription.name} at{" "}
            {formatPriceWithRates(
              calculation.subscription.price,
              calculation.subscription.currency,
              displayCurrency,
              exchangeRates,
              2
            )}{" "}
            for{" "}
            {calculation.subscription.total_units} compute units
          </p>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Secrets Section
// ============================================================

function SecretsSection() {
  const queryClient = useQueryClient();

  const keysQuery = useQuery({
    queryKey: ["sshKeyCandidates"],
    queryFn: sshKeyCandidates
  });
  const secretsQuery = useQuery({ queryKey: ["secrets"], queryFn: secretsApi.list });
  const suggestionsQuery = useQuery({ queryKey: ["secretSuggestions"], queryFn: secretsApi.suggestions });

  const upsertMutation = useMutation({
    mutationFn: secretsApi.upsert,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["secrets"] })
  });
  const deleteMutation = useMutation({
    mutationFn: secretsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["secrets"] })
  });

  const [isOpen, setIsOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editValue, setEditValue] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [showValue, setShowValue] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [sshKeyError, setSshKeyError] = useState<string | null>(null);
  const [sshKeyAction, setSshKeyAction] = useState<{ path: string; kind: "public" | "private" } | null>(null);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const copyNoticeTimer = useRef<number | null>(null);

  const openAddModal = (suggestion?: SecretSuggestion) => {
    setIsEditing(false);
    setEditName(suggestion?.name || "");
    setEditValue("");
    setEditDescription(suggestion?.description || "");
    setShowValue(false);
    setIsOpen(true);
  };

  const openEditModal = async (secret: SecretMeta) => {
    setIsEditing(true);
    setEditName(secret.name);
    setEditDescription(secret.description || "");
    setShowValue(false);
    try {
      const full = await secretsApi.get(secret.name);
      setEditValue(full.value);
    } catch {
      setEditValue("");
    }
    setIsOpen(true);
  };

  const secrets = secretsQuery.data || [];
  const suggestions = suggestionsQuery.data || [];
  const unusedSuggestions = suggestions.filter((s) => !secrets.find((sec) => sec.name === s.name));
  const keyPaths = keysQuery.data || [];
  const showEmptyState = !keysQuery.isLoading && keyPaths.length === 0 && secrets.length === 0;

  const handleCopyKey = async (path: string, kind: "public" | "private") => {
    setSshKeyError(null);
    setSshKeyAction({ path, kind });
    try {
      const key = kind === "public" ? await sshPublicKey(path) : await sshPrivateKey(path);
      await copyText(key);
      const id = `ssh:${kind}:${path}`;
      if (copyNoticeTimer.current) {
        window.clearTimeout(copyNoticeTimer.current);
      }
      setCopyNotice(id);
      copyNoticeTimer.current = window.setTimeout(() => setCopyNotice(null), 1200);
    } catch (e) {
      setSshKeyError(e instanceof Error ? e.message : String(e));
    } finally {
      setSshKeyAction(null);
    }
  };

  useEffect(() => {
    return () => {
      if (copyNoticeTimer.current) {
        window.clearTimeout(copyNoticeTimer.current);
      }
    };
  }, []);

  if (secretsQuery.isLoading) {
    return <Loader2 className="w-6 h-6 mx-auto animate-spin" />;
  }

  return (
    <div className="space-y-4">
      {showEmptyState ? (
        <div className="text-sm text-foreground/50 py-4 text-center">No secrets configured</div>
      ) : (
        <div className="space-y-2">
          {keysQuery.isLoading ? (
            <div className="flex items-center justify-center p-3 bg-muted rounded-lg">
              <Loader2 className="w-4 h-4 animate-spin" />
            </div>
          ) : (
            keyPaths.map((path) => {
              const filename = path.split("/").slice(-1)[0] ?? path;
              const isPublicLoading =
                sshKeyAction?.path === path && sshKeyAction?.kind === "public";
              const isPrivateLoading =
                sshKeyAction?.path === path && sshKeyAction?.kind === "private";
              return (
                <div key={path} className="flex items-center gap-2 p-3 bg-muted rounded-lg">
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-sm truncate">ssh/{filename}</div>
                    <div className="text-xs text-foreground/50 truncate">{path}</div>
                  </div>
                  <div className="flex items-center gap-1">
                    <TooltipProvider>
                      <Tooltip open={copyNotice === `ssh:private:${path}` ? true : undefined}>
                        <TooltipTrigger asChild>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8"
                            disabled={sshKeyAction !== null}
                            onClick={() => handleCopyKey(path, "private")}
                          >
                            {isPrivateLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <IconCopy className="w-4 h-4" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {copyNotice === `ssh:private:${path}` ? "Copied" : "Copy private key"}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                    <TooltipProvider>
                      <Tooltip open={copyNotice === `ssh:public:${path}` ? true : undefined}>
                        <TooltipTrigger asChild>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-8 w-8"
                            disabled={sshKeyAction !== null}
                            onClick={() => handleCopyKey(path, "public")}
                          >
                            {isPublicLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <IconCopy className="w-4 h-4" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {copyNotice === `ssh:public:${path}` ? "Copied" : "Copy public key"}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>
              );
            })
          )}
          {secrets.map((secret) => (
            <div key={secret.name} className="flex items-center gap-2 p-3 bg-muted rounded-lg">
              <div className="flex-1 min-w-0">
                <div className="font-mono text-sm truncate">{secret.name}</div>
                {secret.description && (
                  <div className="text-xs text-foreground/50 truncate">{secret.description}</div>
                )}
              </div>
              <span className="text-xs text-foreground/40">
                {new Date(secret.updated_at).toLocaleDateString()}
              </span>
              <TooltipProvider>
                <Tooltip open={copyNotice === `secret:${secret.name}` ? true : undefined}>
                  <TooltipTrigger asChild>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8"
                      onClick={async () => {
                        await copyText(`\${secret:${secret.name}}`);
                        const id = `secret:${secret.name}`;
                        if (copyNoticeTimer.current) {
                          window.clearTimeout(copyNoticeTimer.current);
                        }
                        setCopyNotice(id);
                        copyNoticeTimer.current = window.setTimeout(() => setCopyNotice(null), 1200);
                      }}
                    >
                      <IconCopy className="w-4 h-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {copyNotice === `secret:${secret.name}` ? "Copied" : "Copy reference"}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8"
                onClick={() => openEditModal(secret)}
              >
                <IconEdit className="w-4 h-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-8 w-8 text-destructive hover:text-destructive"
                onClick={() => setDeleteTarget(secret.name)}
              >
                <IconTrash className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {sshKeyError && <div className="text-xs text-destructive">{sshKeyError}</div>}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => openAddModal()}>
          + Add Secret
        </Button>
        {unusedSuggestions.slice(0, 6).map((s) => (
          <TooltipProvider key={s.name}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button size="sm" variant="outline" onClick={() => openAddModal(s)}>
                  + {s.label}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{s.description}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ))}
      </div>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isEditing ? "Edit Secret" : "Add Secret"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="secret-name">Name</Label>
              <Input
                id="secret-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="github/token"
                readOnly={isEditing}
              />
              <p className="text-xs text-foreground/50">Use slashes</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="secret-value">Value</Label>
              <div className="relative">
                <Input
                  id="secret-value"
                  type={showValue ? "text" : "password"}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  placeholder="Enter API key or token"
                  className="pr-10"
                />
                <Button
                  size="icon"
                  variant="ghost"
                  className="absolute right-0 top-0 h-full"
                  onClick={() => setShowValue(!showValue)}
                >
                  {showValue ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="secret-description">Description (optional)</Label>
              <Input
                id="secret-description"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="What is this secret used for?"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setIsOpen(false)}>Cancel</Button>
            <Button
              disabled={!editName.trim() || !editValue.trim() || upsertMutation.isPending}
              onClick={async () => {
                await upsertMutation.mutateAsync({
                  name: editName.trim(),
                  value: editValue.trim(),
                  description: editDescription.trim() || null
                });
                setIsOpen(false);
              }}
            >
              {upsertMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Secret</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p>Are you sure you want to delete <strong className="font-mono">{deleteTarget}</strong>?</p>
            <p className="text-sm text-foreground/60">
              This will remove it from your OS keychain. Skills that reference this secret will fail.
            </p>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={async () => {
                if (deleteTarget) {
                  await deleteMutation.mutateAsync(deleteTarget);
                  setDeleteTarget(null);
                }
              }}
            >
              {deleteMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
