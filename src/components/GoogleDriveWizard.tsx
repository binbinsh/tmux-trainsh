import { useState } from "react";
import { open } from "@tauri-apps/plugin-shell";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check,
  ExternalLink,
  Copy,
  ArrowRight,
  ArrowLeft,
  Loader2,
} from "lucide-react";
import { gdriveOAuthApi, storageApi } from "@/lib/tauri-api";
import type { StorageCreateInput } from "@/lib/types";
import { copyText } from "@/lib/clipboard";
import { AppIcon } from "@/components/AppIcon";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

// ============================================================
// Step Components
// ============================================================

const WIZARD_STEPS = [
  { id: 1, title: "Create API Project" },
  { id: 2, title: "Enter Credentials" },
  { id: 3, title: "Authorize" },
  { id: 4, title: "Complete" },
];

interface WizardStepProps {
  children: React.ReactNode;
}

function WizardStep({ children }: WizardStepProps) {
  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.2 }}
    >
      {children}
    </motion.div>
  );
}

// ============================================================
// Main Wizard Component
// ============================================================

interface GoogleDriveWizardProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

export function GoogleDriveWizard({
  isOpen,
  onOpenChange,
  onSuccess,
}: GoogleDriveWizardProps) {
  const [step, setStep] = useState(1);
  const [storageName, setStorageName] = useState("Google Drive");

  // Credentials
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  // OAuth flow
  const [authUrl, setAuthUrl] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [tokenJson, setTokenJson] = useState("");

  // Status
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testSuccess, setTestSuccess] = useState(false);

  function resetWizard() {
    setStep(1);
    setStorageName("Google Drive");
    setClientId("");
    setClientSecret("");
    setAuthUrl("");
    setAuthCode("");
    setTokenJson("");
    setError(null);
    setLoading(false);
    setTestSuccess(false);
  }

  function handleClose() {
    resetWizard();
    onOpenChange(false);
  }

  async function handleGenerateAuthUrl() {
    if (!clientId.trim() || !clientSecret.trim()) {
      setError("Please enter both Client ID and Client Secret");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await gdriveOAuthApi.generateAuthUrl(
        clientId.trim(),
        clientSecret.trim()
      );
      setAuthUrl(response.auth_url);
      setStep(3);
    } catch (e) {
      setError(`Failed to generate authorization URL: ${e}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleExchangeCode() {
    if (!authCode.trim()) {
      setError("Please enter the authorization code");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const token = await gdriveOAuthApi.exchangeCode(
        clientId.trim(),
        clientSecret.trim(),
        authCode.trim()
      );
      setTokenJson(token);

      // Test the connection
      const success = await gdriveOAuthApi.testConnection(
        clientId.trim(),
        clientSecret.trim(),
        token
      );

      if (success) {
        setTestSuccess(true);
        setStep(4);
      } else {
        setError("Token exchange succeeded but connection test failed. Please try again.");
      }
    } catch (e) {
      setError(`Failed to complete authorization: ${e}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateStorage() {
    setLoading(true);
    setError(null);

    try {
      const input: StorageCreateInput = {
        name: storageName.trim() || "Google Drive",
        icon: null,
        backend: {
          type: "google_drive",
          client_id: clientId.trim(),
          client_secret: clientSecret.trim(),
          token: tokenJson,
          root_folder_id: null,
        },
        readonly: false,
      };

      await storageApi.create(input);
      handleClose();
      onSuccess();
    } catch (e) {
      setError(`Failed to create storage: ${e}`);
    } finally {
      setLoading(false);
    }
  }

  async function openInBrowser(url: string) {
    try {
      await open(url);
    } catch (e) {
      // Fallback: copy to clipboard
      void copyText(url);
      setError("Could not open browser. URL copied to clipboard.");
    }
  }

  function copyToClipboard(text: string) {
    void copyText(text);
  }

  // ============================================================
  // Render Steps
  // ============================================================

  function renderStep1() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <p className="text-muted-foreground">
            To connect Google Drive, you need to create OAuth credentials in Google Cloud Console.
            Follow these steps:
          </p>

          <Card className="bg-muted/50">
            <CardContent className="space-y-3 pt-6">
              <div className="flex items-start gap-3">
                <Badge variant="default" className="shrink-0">1</Badge>
                <div className="flex-1">
                  <p className="font-medium mb-1">Create a Google Cloud Project</p>
                  <p className="text-sm text-muted-foreground mb-2">
                    Go to Google Cloud Console and create a new project (or use an existing one).
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openInBrowser("https://console.cloud.google.com/projectcreate")}
                  >
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Open Cloud Console
                  </Button>
                </div>
              </div>

              <Separator />

              <div className="flex items-start gap-3">
                <Badge variant="default" className="shrink-0">2</Badge>
                <div className="flex-1">
                  <p className="font-medium mb-1">Enable Google Drive API</p>
                  <p className="text-sm text-muted-foreground mb-2">
                    In the API Library, search for "Google Drive API" and enable it.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openInBrowser("https://console.cloud.google.com/apis/library/drive.googleapis.com")}
                  >
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Enable Drive API
                  </Button>
                </div>
              </div>

              <Separator />

              <div className="flex items-start gap-3">
                <Badge variant="default" className="shrink-0">3</Badge>
                <div className="flex-1">
                  <p className="font-medium mb-1">Configure OAuth Consent Screen</p>
                  <p className="text-sm text-muted-foreground mb-2">
                    Set up the OAuth consent screen. Choose "External" user type, fill in the app name
                    (e.g., "Doppio"), your email, and save.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openInBrowser("https://console.cloud.google.com/auth/overview")}
                  >
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Configure Consent Screen
                  </Button>
                </div>
              </div>

              <Separator />

              <div className="flex items-start gap-3">
                <Badge variant="default" className="shrink-0">4</Badge>
                <div className="flex-1">
                  <p className="font-medium mb-1">Create OAuth Client ID</p>
                  <p className="text-sm text-muted-foreground mb-2">
                    Go to Credentials, click "Create Credentials" → "OAuth client ID".
                    Select <strong>Desktop app</strong> as the application type.
                  </p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => openInBrowser("https://console.cloud.google.com/apis/credentials")}
                  >
                    <ExternalLink className="h-4 w-4 mr-2" />
                    Create Credentials
                  </Button>
                </div>
              </div>

              <Separator />

              <div className="flex items-start gap-3">
                <Badge variant="secondary" className="shrink-0">!</Badge>
                <div className="flex-1">
                  <p className="font-medium text-yellow-600 dark:text-yellow-500 mb-1">Add Yourself as Test User</p>
                  <p className="text-sm text-muted-foreground">
                    Since the app is in testing mode, go to OAuth consent screen → "Test users"
                    and add your Google account email as a test user.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <p className="text-sm text-muted-foreground">
            Once you've created the OAuth Client ID, copy the <strong>Client ID</strong> and{" "}
            <strong>Client Secret</strong>, then proceed to the next step.
          </p>
        </div>
      </WizardStep>
    );
  }

  function renderStep2() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <p className="text-muted-foreground">
            Enter the OAuth credentials you created in the previous step.
          </p>

          <div className="space-y-2">
            <Label htmlFor="storage-name">Storage Name</Label>
            <Input
              id="storage-name"
              placeholder="Google Drive"
              value={storageName}
              onChange={(e) => setStorageName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">A friendly name for this storage location</p>
          </div>

          <Separator />

          <div className="space-y-2">
            <Label htmlFor="client-id">
              Client ID <span className="text-destructive">*</span>
            </Label>
            <Input
              id="client-id"
              placeholder="xxxxxxxx.apps.googleusercontent.com"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">The OAuth 2.0 Client ID from Google Cloud Console</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="client-secret">
              Client Secret <span className="text-destructive">*</span>
            </Label>
            <Input
              id="client-secret"
              type="password"
              placeholder="GOCSPX-xxxxxxxx"
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">The OAuth 2.0 Client Secret from Google Cloud Console</p>
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
      </WizardStep>
    );
  }

  function renderStep3() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <p className="text-muted-foreground">
            Click the button below to open Google's authorization page in your browser.
            Sign in with your Google account and grant access.
          </p>

          <Card className="bg-muted/50">
            <CardContent className="space-y-4 pt-6">
              <div className="flex items-center gap-3">
                <Badge variant="default" className="shrink-0">1</Badge>
                <p className="flex-1">Open the authorization page and sign in</p>
                <Button
                  onClick={() => openInBrowser(authUrl)}
                >
                  <ExternalLink className="h-4 w-4 mr-2" />
                  Open Browser
                </Button>
              </div>

              <Separator />

              <div className="flex items-start gap-3">
                <Badge variant="default" className="shrink-0">2</Badge>
                <div className="flex-1">
                  <p className="mb-2">After authorization, you'll see a page with a code.</p>
                  <p className="text-sm text-muted-foreground">
                    Copy the entire authorization code and paste it below.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-2">
            <Label htmlFor="auth-code">Authorization Code</Label>
            <Textarea
              id="auth-code"
              placeholder="Paste the authorization code here..."
              value={authCode}
              onChange={(e) => setAuthCode(e.target.value)}
              rows={3}
            />
            <p className="text-xs text-muted-foreground">The code shown after you authorize the app</p>
          </div>

          <div className="p-3 bg-yellow-500/10 rounded-lg border border-yellow-500/20">
            <p className="text-sm text-yellow-600 dark:text-yellow-500">
              <strong>Note:</strong> If you see "This app isn't verified" warning, click
              "Advanced" → "Go to [App Name] (unsafe)" to continue. This is normal for
              personal OAuth apps.
            </p>
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
      </WizardStep>
    );
  }

  function renderStep4() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <div className="flex flex-col items-center py-6">
            <div className="w-16 h-16 rounded-full bg-green-500/20 flex items-center justify-center mb-4">
              <Check className="h-8 w-8 text-green-600 dark:text-green-500" />
            </div>
            <h3 className="text-xl font-semibold text-green-600 dark:text-green-500">Authorization Successful!</h3>
            <p className="text-muted-foreground text-center mt-2">
              Your Google Drive is now connected. Click "Create Storage" to save.
            </p>
          </div>

          <Card className="bg-muted/50">
            <CardContent className="pt-6">
              <div className="flex items-center gap-3">
                <AppIcon name="googledrive" className="w-8 h-8" alt="Google Drive" />
                <div className="flex-1">
                  <p className="font-medium">{storageName || "Google Drive"}</p>
                  <p className="text-sm text-muted-foreground">Google Drive</p>
                </div>
                <Badge variant="default">
                  Connected
                </Badge>
              </div>
            </CardContent>
          </Card>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>
      </WizardStep>
    );
  }

  // ============================================================
  // Main Render
  // ============================================================

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <AppIcon name="googledrive" className="w-8 h-8" alt="Google Drive" />
            <DialogTitle>Connect Google Drive</DialogTitle>
          </div>

          {/* Progress indicator */}
          <div className="flex items-center gap-2 mt-4">
            {WIZARD_STEPS.map((s, i) => (
              <div key={s.id} className="flex items-center gap-2">
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                    step > s.id
                      ? "bg-green-500 text-white"
                      : step === s.id
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {step > s.id ? <Check className="h-4 w-4" /> : s.id}
                </div>
                <span
                  className={`text-xs ${
                    step >= s.id ? "text-foreground" : "text-muted-foreground"
                  }`}
                >
                  {s.title}
                </span>
                {i < WIZARD_STEPS.length - 1 && (
                  <div
                    className={`w-8 h-0.5 ${
                      step > s.id ? "bg-green-500" : "bg-muted"
                    }`}
                  />
                )}
              </div>
            ))}
          </div>
        </DialogHeader>

        <div className="py-4">
          <AnimatePresence mode="wait">
            {step === 1 && renderStep1()}
            {step === 2 && renderStep2()}
            {step === 3 && renderStep3()}
            {step === 4 && renderStep4()}
          </AnimatePresence>
        </div>

        <DialogFooter>
          {step > 1 && step < 4 && (
            <Button
              variant="outline"
              onClick={() => {
                setError(null);
                setStep(step - 1);
              }}
              disabled={loading}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
          )}

          <div className="flex-1" />

          <Button variant="ghost" onClick={handleClose} disabled={loading}>
            Cancel
          </Button>

          {step === 1 && (
            <Button
              onClick={() => setStep(2)}
            >
              Next
              <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          )}

          {step === 2 && (
            <Button
              onClick={handleGenerateAuthUrl}
              disabled={loading}
            >
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Continue to Authorization
              <ArrowRight className="h-4 w-4 ml-2" />
            </Button>
          )}

          {step === 3 && (
            <Button
              onClick={handleExchangeCode}
              disabled={!authCode.trim() || loading}
            >
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Complete Authorization
            </Button>
          )}

          {step === 4 && (
            <Button
              onClick={handleCreateStorage}
              disabled={loading}
              className="bg-green-600 hover:bg-green-700 text-white"
            >
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Storage
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
