import {
  Card,
  CardBody,
  Chip,
  Divider,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  Progress,
  Spinner,
  Textarea,
} from "@nextui-org/react";
import { Button } from "./ui";
import { AppIcon } from "./AppIcon";
import { open } from "@tauri-apps/plugin-shell";
import { useState } from "react";
import { copyText } from "../lib/clipboard";
import { gdriveOAuthApi, storageApi } from "../lib/tauri-api";
import type { StorageCreateInput } from "../lib/types";
import { motion, AnimatePresence } from "framer-motion";

// ============================================================
// Icons
// ============================================================

function IconCheck() {
  return (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function IconExternalLink() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
    </svg>
  );
}

function IconCopy() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
    </svg>
  );
}

function IconArrowRight() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
    </svg>
  );
}

function IconArrowLeft() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

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
          <p className="text-foreground/80">
            To connect Google Drive, you need to create OAuth credentials in Google Cloud Console.
            Follow these steps:
          </p>
          
          <Card className="bg-content2">
            <CardBody className="space-y-3">
              <div className="flex items-start gap-3">
                <Chip size="sm" color="primary" variant="flat">1</Chip>
                <div>
                  <p className="font-medium">Create a Google Cloud Project</p>
                  <p className="text-sm text-foreground/60">
                    Go to Google Cloud Console and create a new project (or use an existing one).
                  </p>
                  <Button
                    size="sm"
                    variant="flat"
                    className="mt-2"
                    endContent={<IconExternalLink />}
                    onPress={() => openInBrowser("https://console.cloud.google.com/projectcreate")}
                  >
                    Open Cloud Console
                  </Button>
                </div>
              </div>
              
              <Divider />
              
              <div className="flex items-start gap-3">
                <Chip size="sm" color="primary" variant="flat">2</Chip>
                <div>
                  <p className="font-medium">Enable Google Drive API</p>
                  <p className="text-sm text-foreground/60">
                    In the API Library, search for "Google Drive API" and enable it.
                  </p>
                  <Button
                    size="sm"
                    variant="flat"
                    className="mt-2"
                    endContent={<IconExternalLink />}
                    onPress={() => openInBrowser("https://console.cloud.google.com/apis/library/drive.googleapis.com")}
                  >
                    Enable Drive API
                  </Button>
                </div>
              </div>
              
              <Divider />
              
              <div className="flex items-start gap-3">
                <Chip size="sm" color="primary" variant="flat">3</Chip>
                <div>
                  <p className="font-medium">Configure OAuth Consent Screen</p>
                  <p className="text-sm text-foreground/60">
                    Set up the OAuth consent screen. Choose "External" user type, fill in the app name
                    (e.g., "Doppio"), your email, and save.
                  </p>
                  <Button
                    size="sm"
                    variant="flat"
                    className="mt-2"
                    endContent={<IconExternalLink />}
                    onPress={() => openInBrowser("https://console.cloud.google.com/auth/overview")}
                  >
                    Configure Consent Screen
                  </Button>
                </div>
              </div>
              
              <Divider />
              
              <div className="flex items-start gap-3">
                <Chip size="sm" color="primary" variant="flat">4</Chip>
                <div>
                  <p className="font-medium">Create OAuth Client ID</p>
                  <p className="text-sm text-foreground/60">
                    Go to Credentials, click "Create Credentials" → "OAuth client ID".
                    Select <strong>Desktop app</strong> as the application type.
                  </p>
                  <Button
                    size="sm"
                    variant="flat"
                    className="mt-2"
                    endContent={<IconExternalLink />}
                    onPress={() => openInBrowser("https://console.cloud.google.com/apis/credentials")}
                  >
                    Create Credentials
                  </Button>
                </div>
              </div>
              
              <Divider />
              
              <div className="flex items-start gap-3">
                <Chip size="sm" color="warning" variant="flat">!</Chip>
                <div>
                  <p className="font-medium text-warning">Add Yourself as Test User</p>
                  <p className="text-sm text-foreground/60">
                    Since the app is in testing mode, go to OAuth consent screen → "Test users"
                    and add your Google account email as a test user.
                  </p>
                </div>
              </div>
            </CardBody>
          </Card>
          
          <p className="text-sm text-foreground/60">
            Once you've created the OAuth Client ID, copy the <strong>Client ID</strong> and 
            <strong> Client Secret</strong>, then proceed to the next step.
          </p>
        </div>
      </WizardStep>
    );
  }

  function renderStep2() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <p className="text-foreground/80">
            Enter the OAuth credentials you created in the previous step.
          </p>
          
          <Input labelPlacement="inside" label="Storage Name"
          placeholder="Google Drive"
          value={storageName}
          onValueChange={setStorageName}
          description="A friendly name for this storage location" />
          
          <Divider />
          
          <Input labelPlacement="inside" label="Client ID"
          placeholder="xxxxxxxx.apps.googleusercontent.com"
          value={clientId}
          onValueChange={setClientId}
          isRequired
          description="The OAuth 2.0 Client ID from Google Cloud Console" />
          
          <Input labelPlacement="inside" label="Client Secret"
          type="password"
          placeholder="GOCSPX-xxxxxxxx"
          value={clientSecret}
          onValueChange={setClientSecret}
          isRequired
          description="The OAuth 2.0 Client Secret from Google Cloud Console" />
          
          {error && (
            <p className="text-sm text-danger">{error}</p>
          )}
        </div>
      </WizardStep>
    );
  }

  function renderStep3() {
    return (
      <WizardStep>
        <div className="space-y-4">
          <p className="text-foreground/80">
            Click the button below to open Google's authorization page in your browser.
            Sign in with your Google account and grant access.
          </p>
          
          <Card className="bg-content2">
            <CardBody className="space-y-4">
              <div className="flex items-center gap-3">
                <Chip size="sm" color="primary" variant="flat">1</Chip>
                <p className="flex-1">Open the authorization page and sign in</p>
                <Button
                  color="primary"
                  endContent={<IconExternalLink />}
                  onPress={() => openInBrowser(authUrl)}
                >
                  Open Browser
                </Button>
              </div>
              
              <Divider />
              
              <div className="flex items-start gap-3">
                <Chip size="sm" color="primary" variant="flat">2</Chip>
                <div className="flex-1">
                  <p className="mb-2">After authorization, you'll see a page with a code.</p>
                  <p className="text-sm text-foreground/60">
                    Copy the entire authorization code and paste it below.
                  </p>
                </div>
              </div>
            </CardBody>
          </Card>
          
          <Textarea labelPlacement="inside" label="Authorization Code"
          placeholder="Paste the authorization code here..."
          value={authCode}
          onValueChange={setAuthCode}
          minRows={2}
          maxRows={4}
          description="The code shown after you authorize the app" />
          
          <div className="p-3 bg-warning/10 rounded-lg border border-warning/20">
            <p className="text-sm text-warning">
              <strong>Note:</strong> If you see "This app isn't verified" warning, click 
              "Advanced" → "Go to [App Name] (unsafe)" to continue. This is normal for 
              personal OAuth apps.
            </p>
          </div>
          
          {error && (
            <p className="text-sm text-danger">{error}</p>
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
            <div className="w-16 h-16 rounded-full bg-success/20 flex items-center justify-center mb-4">
              <IconCheck />
            </div>
            <h3 className="text-xl font-semibold text-success">Authorization Successful!</h3>
            <p className="text-foreground/60 text-center mt-2">
              Your Google Drive is now connected. Click "Create Storage" to save.
            </p>
          </div>
          
          <Card className="bg-content2">
            <CardBody>
              <div className="flex items-center gap-3">
                <AppIcon name="googledrive" className="w-8 h-8" alt="Google Drive" />
                <div>
                  <p className="font-medium">{storageName || "Google Drive"}</p>
                  <p className="text-sm text-foreground/60">Google Drive</p>
                </div>
                <Chip color="success" variant="flat" size="sm" className="ml-auto">
                  Connected
                </Chip>
              </div>
            </CardBody>
          </Card>
          
          {error && (
            <p className="text-sm text-danger">{error}</p>
          )}
        </div>
      </WizardStep>
    );
  }

  // ============================================================
  // Main Render
  // ============================================================

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
      size="2xl"
      scrollBehavior="inside"
      isDismissable={!loading}
    >
      <ModalContent>
        {() => (
          <>
            <ModalHeader className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <AppIcon name="googledrive" className="w-8 h-8" alt="Google Drive" />
                <span>Connect Google Drive</span>
              </div>
              
              {/* Progress indicator */}
              <div className="flex items-center gap-2 mt-2">
                {WIZARD_STEPS.map((s, i) => (
                  <div key={s.id} className="flex items-center gap-2">
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                        step > s.id
                          ? "bg-success text-white"
                          : step === s.id
                          ? "bg-primary text-white"
                          : "bg-content3 text-foreground/60"
                      }`}
                    >
                      {step > s.id ? <IconCheck /> : s.id}
                    </div>
                    <span
                      className={`text-xs ${
                        step >= s.id ? "text-foreground" : "text-foreground/40"
                      }`}
                    >
                      {s.title}
                    </span>
                    {i < WIZARD_STEPS.length - 1 && (
                      <div
                        className={`w-8 h-0.5 ${
                          step > s.id ? "bg-success" : "bg-content3"
                        }`}
                      />
                    )}
                  </div>
                ))}
              </div>
            </ModalHeader>
            
            <ModalBody>
              <AnimatePresence mode="wait">
                {step === 1 && renderStep1()}
                {step === 2 && renderStep2()}
                {step === 3 && renderStep3()}
                {step === 4 && renderStep4()}
              </AnimatePresence>
            </ModalBody>
            
            <ModalFooter>
              {step > 1 && step < 4 && (
                <Button
                  variant="flat"
                  startContent={<IconArrowLeft />}
                  onPress={() => {
                    setError(null);
                    setStep(step - 1);
                  }}
                  isDisabled={loading}
                >
                  Back
                </Button>
              )}
              
              <div className="flex-1" />
              
              <Button variant="flat" onPress={handleClose} isDisabled={loading}>
                Cancel
              </Button>
              
              {step === 1 && (
                <Button
                  color="primary"
                  endContent={<IconArrowRight />}
                  onPress={() => setStep(2)}
                >
                  Next
                </Button>
              )}
              
              {step === 2 && (
                <Button
                  color="primary"
                  endContent={<IconArrowRight />}
                  onPress={handleGenerateAuthUrl}
                  isLoading={loading}
                >
                  Continue to Authorization
                </Button>
              )}
              
              {step === 3 && (
                <Button
                  color="primary"
                  onPress={handleExchangeCode}
                  isLoading={loading}
                  isDisabled={!authCode.trim()}
                >
                  Complete Authorization
                </Button>
              )}
              
              {step === 4 && (
                <Button
                  color="success"
                  onPress={handleCreateStorage}
                  isLoading={loading}
                >
                  Create Storage
                </Button>
              )}
            </ModalFooter>
          </>
        )}
      </ModalContent>
    </Modal>
  );
}
