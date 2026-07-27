/**
 * Change-tracking tests.
 *
 * This drives the save button and the close-confirmation prompt, so "how many fields
 * changed" has to be exact - an off-by-one shows up as a button offering to save
 * nothing, or a prompt that never appears.
 */

import { describe, expect, it, vi } from "vitest";

vi.mock("@/telegram", () => ({ setClosingConfirmation: vi.fn() }));

import { setClosingConfirmation } from "@/telegram";
import { useDirtyState } from "./useDirtyState";

describe("useDirtyState", () => {
  it("starts clean", () => {
    const form = useDirtyState({ a: 1, b: "x" });

    expect(form.isDirty.value).toBe(false);
    expect(form.changedFields.value).toEqual([]);
  });

  it("reports only the fields that differ", () => {
    const form = useDirtyState({ a: 1, b: "x", c: true });

    form.draft.value.a = 2;
    form.draft.value.c = false;

    expect(form.changedFields.value).toEqual(["a", "c"]);
    expect(form.isDirty.value).toBe(true);
  });

  it("goes clean again when a value is edited back", () => {
    const form = useDirtyState({ a: 1 });

    form.draft.value.a = 2;
    form.draft.value.a = 1;

    expect(form.isDirty.value).toBe(false);
  });

  it("compares nested objects by value, not by reference", () => {
    const form = useDirtyState<{ perms: Record<string, boolean> }>({
      perms: { can_pin_messages: true },
    });

    // A fresh object with identical contents is not a change.
    form.draft.value.perms = { can_pin_messages: true };
    expect(form.isDirty.value).toBe(false);

    form.draft.value.perms = { can_pin_messages: false };
    expect(form.isDirty.value).toBe(true);
  });

  it("does not alias the draft to the caller's object", () => {
    const initial = { a: 1 };
    const form = useDirtyState(initial);

    form.draft.value.a = 99;

    expect(initial.a).toBe(1);
  });

  it("reset returns the draft to the baseline", () => {
    const form = useDirtyState({ a: 1, b: "x" });

    form.draft.value.a = 2;
    form.reset();

    expect(form.draft.value).toEqual({ a: 1, b: "x" });
    expect(form.isDirty.value).toBe(false);
  });

  it("commit adopts the saved values as the new baseline", () => {
    const form = useDirtyState({ a: 1 });

    form.draft.value.a = 2;
    form.commit({ a: 2 });

    expect(form.isDirty.value).toBe(false);
    expect(form.draft.value.a).toBe(2);
  });

  it("commit clears the closing confirmation", () => {
    const form = useDirtyState({ a: 1 });

    form.commit({ a: 1 });

    expect(setClosingConfirmation).toHaveBeenCalledWith(false);
  });
});
