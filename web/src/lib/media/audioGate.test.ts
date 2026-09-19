import { describe, expect, it, vi } from "vitest";
import { AudioGate } from "./audioGate";

describe("AudioGate", () => {
  it("cancels active output and remains muted on call entry", () => {
    const gate = new AudioGate();
    const cancel = vi.fn();
    gate.requestResume(); gate.acceptResume(2); gate.registerActiveOutput(cancel);
    gate.silence();
    expect(cancel).toHaveBeenCalledOnce();
    expect(gate.isAllowed()).toBe(false);
    expect(gate.isResumeRequested()).toBe(false);
  });

  it("only permits the explicitly accepted mode revision", () => {
    const gate = new AudioGate();
    gate.requestResume(); gate.acceptResume(4);
    expect(gate.permits(4)).toBe(true);
    expect(gate.permits(3)).toBe(false);
    gate.silence();
    expect(gate.permits(4)).toBe(false);
  });
});
