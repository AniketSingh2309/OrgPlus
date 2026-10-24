import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CapabilitiesCtx, Feature, LockedCard } from "@/components/feature";
import type { Capabilities, FeatureInfo } from "@/lib/types";

afterEach(cleanup);

const feature = (over: Partial<FeatureInfo> = {}): FeatureInfo => ({
  enabled: false,
  status: "locked",
  reason: "HTTP 403",
  requires: "Business Plus or above (Google Vault)",
  title: "Legal hold status",
  description: "Users under legal hold.",
  how_to_enable: "https://support.google.com/vault/answer/2462365",
  page: "/m/vault",
  paid: true,
  cards: [{ id: "legal-hold", title: "Legal holds", description: "Who is under hold and how many matters are open." }],
  checked_at: null,
  ...over,
});

const caps = (features: Record<string, FeatureInfo>): Capabilities => ({
  edition: "Business Standard",
  tier: "free",
  badge: "Business Standard · Free features",
  detected_at: null,
  licensing_error: null,
  sku_breakdown: {},
  licences_total: null,
  licences_assigned: null,
  features,
  changes: [],
});

function renderWith(features: Record<string, FeatureInfo>, hideLocked = false) {
  return render(
    <CapabilitiesCtx.Provider value={{ caps: caps(features), hideLocked }}>
      <Feature name="vault">
        <p>secret content</p>
      </Feature>
    </CapabilitiesCtx.Provider>,
  );
}

describe("LockedCard", () => {
  it("shows the title, requirement chip, one-line description and how-to link", () => {
    render(<LockedCard feature={feature()} />);
    expect(screen.getByRole("region", { name: "Legal hold status (locked)" })).toBeTruthy();
    expect(screen.getByText("Needs Business Plus or above")).toBeTruthy();
    expect(screen.getByText("Who is under hold and how many matters are open.")).toBeTruthy();
    const link = screen.getByRole("link", { name: /How to enable/ }) as HTMLAnchorElement;
    expect(link.href).toBe("https://support.google.com/vault/answer/2462365");
  });

  it("explains non-locked statuses", () => {
    render(<LockedCard feature={feature({ status: "not_configured", reason: "no BigQuery project/dataset given" })} />);
    expect(screen.getByText("Not set up")).toBeTruthy();
    expect(screen.getByText(/no BigQuery project/)).toBeTruthy();
  });
});

describe("<Feature>", () => {
  it("renders children when the capability is on", () => {
    renderWith({ vault: feature({ enabled: true, status: "on" }) });
    expect(screen.getByText("secret content")).toBeTruthy();
  });

  it("renders a locked card instead of children when locked", () => {
    renderWith({ vault: feature() });
    expect(screen.queryByText("secret content")).toBeNull();
    expect(screen.getByText("Needs Business Plus or above")).toBeTruthy();
  });

  it("renders nothing when locked and 'hide locked features' is on", () => {
    const { container } = renderWith({ vault: feature() }, true);
    expect(container.textContent).toBe("");
  });
});
