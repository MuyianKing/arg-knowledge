import { useCallback, useEffect, useState } from "react";

import { clientApi, settingsApi } from "./api";
import Connect from "./components/Connect";
import Main from "./components/Main";
import Wizard from "./components/Wizard";
import type { AppSettings } from "./types";

const DEFAULT_SETTINGS: AppSettings = {
  baseUrl: "http://127.0.0.1:8080",
  tenantId: "acme",
  acl: "internal",
  engineRoot: null,
  pythonPath: null,
  modelRoot: null,
  enginePort: 8080,
  qdrantHttpPort: 6333,
  qdrantGrpcPort: 6334,
  setupCompleted: false,
  llmBaseUrl: "",
  llmModelName: "",
  llmModelRevision: "",
  llmTemperature: 0.1,
  llmMaxTokens: 512,
  llmMock: false,
};

type Phase = "boot" | "connect" | "wizard" | "main";

export default function App() {
  const [phase, setPhase] = useState<Phase>("boot");
  const [wizardReturn, setWizardReturn] = useState<Phase>("connect");
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let loaded = DEFAULT_SETTINGS;
      try {
        loaded = await settingsApi.get();
      } catch {
        // Keep defaults; the connect screen lets the user fix the address.
      }
      if (cancelled) return;
      setSettings(loaded);
      try {
        const report = await clientApi.probeConnection();
        if (cancelled) return;
        setPhase(report.ok ? "main" : "connect");
      } catch {
        if (!cancelled) setPhase("connect");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const patchSettings = useCallback(async (patch: Partial<AppSettings>) => {
    try {
      // Read the latest file first: the LLM panel writes settings directly.
      const latest = await settingsApi.get();
      const next = { ...latest, ...patch };
      setSettings(next);
      await settingsApi.save(next);
    } catch (error) {
      console.error(error);
      setSettings((prev) => ({ ...prev, ...patch }));
    }
  }, []);

  const openWizard = (from: Phase) => {
    setWizardReturn(from);
    setPhase("wizard");
  };

  if (phase === "boot") {
    return <div className="splash">正在读取本地配置…</div>;
  }

  if (phase === "wizard") {
    return (
      <Wizard
        settings={settings}
        patchSettings={patchSettings}
        onFinish={() => setPhase("main")}
        onCancel={() => setPhase(wizardReturn)}
      />
    );
  }

  if (phase === "connect") {
    return (
      <Connect
        settings={settings}
        patchSettings={patchSettings}
        onConnected={() => setPhase("main")}
        onOpenWizard={() => openWizard("connect")}
        onSkip={() => setPhase("main")}
      />
    );
  }

  return (
    <Main
      settings={settings}
      patchSettings={patchSettings}
      onOpenWizard={() => openWizard("main")}
      onReconnect={() => setPhase("connect")}
    />
  );
}
