import { cleanup, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it } from "vitest";
import { Avatar, PersonLink } from "@/components/ui";
import { initials } from "@/lib/format";

afterEach(cleanup);

// Avatars look up photos via SWR; give them an empty photo list instead of the network.
const wrap = (ui: React.ReactNode) => (
  <SWRConfig value={{ fetcher: async () => ({}), provider: () => new Map() }}>{ui}</SWRConfig>
);

describe("people without a name or email (external / anonymous actors)", () => {
  it("initials never throw", () => {
    expect(initials(null)).toBe("?");
    expect(initials(undefined)).toBe("?");
    expect(initials("")).toBe("?");
    expect(initials("Aryan Gupta")).toBe("AG");
  });

  it("Avatar renders a placeholder instead of crashing", () => {
    const { container } = render(wrap(<Avatar name={null} email={null} />));
    expect(container.textContent).toBe("?");
  });

  it("PersonLink labels them as external or anonymous", () => {
    render(wrap(<PersonLink id={null} name={null} email={null} />));
    expect(screen.getByText("External or anonymous")).toBeTruthy();
  });
});
