"use client";

import { ChevronDown, ShieldCheck } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { Chip } from "./ui";

const PANEL_WIDTH = 260;

/** Just below the button, kept inside the viewport horizontally. */
function placeBelow(rect: DOMRect): { top: number; left: number } {
  return { top: rect.bottom + 6, left: Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8)) };
}

/**
 * Admin roles: up to `inline` roles show as chips; more collapse into a
 * "[first role] +N" dropdown listing them all. The list is position: fixed so
 * table scroll containers can't clip it.
 */
export function RoleList({ roles, inline = 2 }: { roles: string[]; inline?: number }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e.type === "keydown" && (e as KeyboardEvent).key !== "Escape") return;
      if (e.type === "mousedown" && (panel.current?.contains(e.target as Node) || button.current?.contains(e.target as Node))) return;
      setOpen(false);
      if (e.type === "keydown") button.current?.focus();
    };
    // Page or table scrolled: keep the list attached to its button; close only once the
    // button is out of view. Scrolling inside the list itself is ignored.
    const follow = (e: Event) => {
      if (panel.current && e.target instanceof Node && panel.current.contains(e.target)) return;
      const rect = button.current?.getBoundingClientRect();
      if (!rect || rect.bottom < 0 || rect.top > window.innerHeight) {
        setOpen(false);
        return;
      }
      setPos(placeBelow(rect));
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
    };
  }, [open]);

  if (!roles.length) return null;
  if (roles.length <= inline) {
    return (
      <span className="flex flex-wrap gap-1">
        {roles.map((r) => (
          <Chip key={r} tone="brand">
            {r}
          </Chip>
        ))}
      </span>
    );
  }

  const toggle = () => {
    if (!open && button.current) setPos(placeBelow(button.current.getBoundingClientRect()));
    setOpen(!open);
  };

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={id}
        aria-label={`${roles.length} admin roles: ${roles.join(", ")}`}
        className="inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand-strong hover:ring-2 hover:ring-brand/30"
      >
        <span className="truncate">{roles[0]}</span>
        <span className="rounded-full bg-brand/15 px-1.5">+{roles.length - 1}</span>
        <ChevronDown size={12} className={open ? "rotate-180 transition" : "transition"} aria-hidden />
      </button>
      {open && pos && (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label="Admin roles"
          style={{ top: pos.top, left: pos.left, width: PANEL_WIDTH }}
          className="fixed z-50 max-h-72 overflow-y-auto rounded-lg border border-line bg-surface p-2 shadow-xl"
        >
          <div className="px-2 pb-1.5 pt-1 text-xs font-semibold uppercase tracking-wide text-ink-3">
            {roles.length} admin roles
          </div>
          <ul>
            {roles.map((r) => (
              <li key={r} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink">
                <ShieldCheck size={14} className="shrink-0 text-brand" aria-hidden />
                {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
