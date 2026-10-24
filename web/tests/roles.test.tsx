import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RoleList } from "@/components/roles";

afterEach(cleanup);

describe("RoleList", () => {
  it("shows up to two roles inline as chips", () => {
    render(<RoleList roles={["Super Admin", "Groups Admin"]} />);
    expect(screen.getByText("Super Admin")).toBeTruthy();
    expect(screen.getByText("Groups Admin")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("collapses more than two roles into a dropdown listing them all", () => {
    const roles = ["Super Admin", "Groups Admin", "Help Desk Admin", "Mobile Admin"];
    render(<RoleList roles={roles} />);
    const trigger = screen.getByRole("button", { name: /4 admin roles/ });
    expect(trigger.textContent).toContain("Super Admin");
    expect(trigger.textContent).toContain("+3");
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(trigger);
    const panel = screen.getByRole("dialog", { name: "Admin roles" });
    for (const r of roles) expect(panel.textContent).toContain(r);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("stays open while the role list itself is scrolled", () => {
    const roles = Array.from({ length: 14 }, (_, i) => `Role ${i + 1}`);
    render(<RoleList roles={roles} />);
    fireEvent.click(screen.getByRole("button", { name: /14 admin roles/ }));
    const panel = screen.getByRole("dialog", { name: "Admin roles" });
    fireEvent.scroll(panel);
    expect(screen.queryByRole("dialog")).not.toBeNull();
    fireEvent.scroll(window); // page scroll: follows its button (still on screen in jsdom)
    expect(screen.queryByRole("dialog")).not.toBeNull();
  });

  it("renders nothing without roles", () => {
    const { container } = render(<RoleList roles={[]} />);
    expect(container.textContent).toBe("");
  });
});
